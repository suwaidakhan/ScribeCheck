"""The 100-row failure sheet, SPEC section 6.

Every column is filled except `failure_code`, `severity` and `note`. Those
three are the reason this benchmark is worth publishing under a person's name,
and a guess from a model would contaminate the one part of it that has to be a
human judgment. This module will not write them and should not be changed to.

Run:  python -m src.failures
"""

from __future__ import annotations

import difflib
import html
import json
import sys

import pandas as pd

from src import config
from src.findings import excerpt_around, findings_for, select_findings
from src.lexicon import load as load_lexicon
from src.score import normalize

FAILURE_SHEET_ROWS = 100
EXCERPT_WIDTH = 15

# SPEC section 6, in priority order. Every drug substitution first, then every
# dosage value error, then every negation flip, then worst-WER clips to fill.
PRIORITY = [
    ("drug_substitution", "DRUG-SUB candidate"),
    ("dose_value_error", "DOSE-VAL candidate"),
    ("negation_lost", "NEG-FLIP candidate"),
]

SHEET_COLUMNS = [
    "finding_id",
    "clip_id",
    "provider",
    "accent",
    "tier",
    "domain",
    "kind",
    "expected",
    "heard",
    "weight",
    "ref_excerpt",
    "hyp_excerpt",
    "auto_flag",
    "needs_listen",
    "failure_code",
    "severity",
    "note",
]

# How many findings a human is asked to judge. Every row is one error, so this
# is a count of judgments rather than of clips.
SHEET_SIZE = 150

CODE_DEFINITIONS = [
    ("DRUG-SUB", "one real drug transcribed as a different real drug"),
    ("DRUG-DEL", "drug name dropped or corrupted into a non-word"),
    ("DOSE-VAL", "numeric value changed"),
    ("DOSE-UNIT", "unit changed, value intact"),
    ("DOSE-MISS", "the dose is gone: no number and unit survived in its place"),
    ("NEG-FLIP", "negation lost or inverted"),
    ("TERM-CORRUPT", "clinical term corrupted into a plausible-reading wrong term"),
    ("PHON-ACCENT", "error traceable to accent phonology (verify by listening)"),
    ("BENIGN", "a real error, but no clinical meaning changes"),
    ("NO-ERROR", "the detector was wrong, nothing is wrong with this transcription"),
]

SEVERITY_DEFINITIONS = [
    (
        "S1",
        "could change a clinical action if unreviewed (wrong drug, wrong value, flipped negation)",
    ),
    ("S2", "misleading, likely caught by a reader"),
    ("S3", "cosmetic"),
]


def select_failures(scores: pd.DataFrame, n: int = FAILURE_SHEET_ROWS) -> pd.DataFrame:
    """Pick the n failures worth a human's time, in SPEC's priority order.

    Within each priority band the rows are interleaved across providers and
    tiers rather than taken in table order. A sheet of 100 rows drawn from the
    worst provider would say nothing about whether the others are safer, and
    the tier comparison is the benchmark's question.
    """
    frame = scores.copy()

    # A clip transcribed correctly is not a failure, and putting one on the
    # sheet spends a human's attention on a row with nothing to label. The
    # fill band is "worst WER", which only means anything among clips that got
    # something wrong.
    error_columns = [
        column
        for column in (
            "drug_substitution",
            "drug_deletion",
            "dose_value_error",
            "dose_unit_error",
            "dose_missing",
            "negation_lost",
        )
        if column in frame.columns
    ]
    has_error = frame["wer"].fillna(0) > 0
    for column in error_columns:
        has_error = has_error | (frame[column] > 0)
    frame = frame[has_error]

    frame["_band"] = len(PRIORITY)
    frame["auto_flag"] = ""
    for band, (column, label) in enumerate(PRIORITY):
        if column not in frame.columns:
            continue
        hits = (frame[column] > 0) & (frame["_band"] == len(PRIORITY))
        frame.loc[hits, "_band"] = band
        frame.loc[hits, "auto_flag"] = label
    frame.loc[frame["auto_flag"] == "", "auto_flag"] = "high WER"

    picked: list[pd.DataFrame] = []
    taken = 0
    for band in range(len(PRIORITY) + 1):
        if taken >= n:
            break
        in_band = frame[frame["_band"] == band]
        if in_band.empty:
            continue
        spread = _interleave(in_band)
        chunk = spread.head(n - taken)
        picked.append(chunk)
        taken += len(chunk)

    if not picked:
        return frame.head(0).drop(columns=["_band"])
    return pd.concat(picked).drop(columns=["_band"]).reset_index(drop=True)


def _interleave(frame: pd.DataFrame) -> pd.DataFrame:
    """Round-robin across (provider, tier) so no single group dominates.

    Within a group the worst WER comes first, so the rows a human sees are the
    worst examples from each corner rather than the worst examples overall.
    """
    ordered = frame.sort_values(
        ["provider", "tier", "wer"], ascending=[True, True, False]
    )
    queues = [group for _, group in ordered.groupby(["provider", "tier"], sort=True)]
    rows: list[pd.Series] = []
    position = 0
    while any(position < len(queue) for queue in queues):
        for queue in queues:
            if position < len(queue):
                rows.append(queue.iloc[position])
        position += 1
    return pd.DataFrame(rows)


def mark_diff(reference: str, hypothesis: str) -> tuple[str, str]:
    """Wrap the differing tokens on each side in asterisks.

    Both sides are returned together because a substitution is only legible as
    a pair: "*metformin*" against "*metronidazole*" is the finding, and either
    one alone is just a word.
    """
    ref_tokens = str(reference).split()
    hyp_tokens = str(hypothesis).split()
    matcher = difflib.SequenceMatcher(None, ref_tokens, hyp_tokens, autojunk=False)

    marked_ref = list(ref_tokens)
    marked_hyp = list(hyp_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for index in range(i1, i2):
            marked_ref[index] = f"*{ref_tokens[index]}*"
        for index in range(j1, j2):
            marked_hyp[index] = f"*{hyp_tokens[index]}*"
    return " ".join(marked_ref), " ".join(marked_hyp)


def drug_evidence(reference: str, hypothesis: str, lexicon: set[str]) -> dict:
    """Which words in this row are known drugs, on both sides.

    DRUG-SUB against DRUG-DEL turns on one question: is the word that replaced
    the drug itself a drug? That has a right answer, it sits in the openFDA
    directory, and the scorer already consults it. Leaving the labeller to
    recall whether "glatropin" is a real medicine made a factual lookup feel
    like a judgment call and would have put noise into one of the two headline
    metrics.

    So the fact is surfaced and the judgment is not. Nothing here suggests a
    code or a severity. Both remain empty for a human to fill.
    """
    from src.entities import find_drug_mentions
    from src.score import normalize

    ref = normalize(str(reference))
    hyp = normalize(str(hypothesis))
    return {
        "expected": find_drug_mentions(ref, lexicon),
        "heard_known": find_drug_mentions(hyp, lexicon),
    }


def excerpt(marked: str, width: int = EXCERPT_WIDTH) -> str:
    """About `width` words centred on the first marked token."""
    tokens = marked.split()
    if len(tokens) <= width:
        return marked
    centre = next(
        (i for i, token in enumerate(tokens) if token.startswith("*")), len(tokens) // 2
    )
    half = width // 2
    start = max(0, centre - half)
    return " ".join(tokens[start : start + width + 1])


def build() -> pd.DataFrame:
    """Write taxonomy/failure_taxonomy.csv and taxonomy/labeling.html.

    One row per finding rather than per clip. A clip with three errors produces
    three rows, each centred on its own entity and each carrying its own code
    and severity, because a single dropdown cannot describe three errors and a
    single excerpt cannot show them.

    The sheet is a stratified sample with inclusion weights, so a rate computed
    from the labelled rows describes the whole population of findings rather
    than the sheet. See docs/PRD_EVAL_V2.md W2, W3, W5 and W6.
    """
    manifest = pd.read_csv(config.MANIFEST).set_index("clip_id")
    transcripts = _cached_text()
    if not transcripts:
        raise SystemExit(
            "No cached transcripts in data/cache/. Run `python -m src.transcribe` "
            "first, which needs the four API keys in .env."
        )

    lexicon = load_lexicon()
    rows = []
    for (provider, clip_id), heard in transcripts.items():
        if clip_id not in manifest.index:
            continue
        reference = normalize(str(manifest.loc[clip_id, "transcript"]))
        hypothesis = normalize(str(heard))
        for finding in findings_for(reference, hypothesis, lexicon):
            rows.append(
                {
                    **finding,
                    "clip_id": clip_id,
                    "provider": provider,
                    "accent": manifest.loc[clip_id, "accent"],
                    "tier": manifest.loc[clip_id, "tier"],
                    "domain": manifest.loc[clip_id, "domain"],
                }
            )

    population = pd.DataFrame(rows)
    print(f"{len(population)} findings across {len(transcripts)} transcripts.")
    selected = select_findings(population, target=SHEET_SIZE, seed=config.SEED)

    sheet_rows = []
    for finding_id, (_, row) in enumerate(selected.iterrows(), start=1):
        reference = normalize(str(manifest.loc[row["clip_id"], "transcript"]))
        hypothesis = normalize(str(transcripts[(row["provider"], row["clip_id"])]))
        shown_ref, shown_hyp = excerpt_around(
            reference, hypothesis, int(row["ref_index"])
        )
        sheet_rows.append(
            {
                "finding_id": finding_id,
                "clip_id": row["clip_id"],
                "provider": row["provider"],
                "accent": row["accent"],
                "tier": row["tier"],
                "domain": row["domain"],
                "kind": row["kind"],
                "weight": float(row["weight"]),
                "expected": row["expected"],
                "heard": row["heard"],
                "weight": round(float(row["weight"]), 4),
                "ref_excerpt": shown_ref,
                "hyp_excerpt": shown_hyp,
                "auto_flag": f"{row['kind']} candidate",
                "needs_listen": "",
                "failure_code": "",  # Suwaid's.
                "severity": "",  # Suwaid's.
                "note": "",  # Suwaid's.
            }
        )

    sheet = pd.DataFrame(sheet_rows, columns=SHEET_COLUMNS)
    config.TAXONOMY.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(config.TAXONOMY / "failure_taxonomy.csv", index=False)
    config.RESULTS.mkdir(parents=True, exist_ok=True)
    population.to_csv(config.RESULTS / "all_findings.csv", index=False)
    _write_labeling_page(sheet, manifest)

    print(f"Wrote {len(sheet)} rows to {config.TAXONOMY / 'failure_taxonomy.csv'}")
    print(f"Wrote {config.RESULTS / 'all_findings.csv'} ({len(population)} findings)")
    print(f"Wrote {config.TAXONOMY / 'labeling.html'}")
    print("\nSampling, so a rate can be computed from the labels:")
    for kind, group in selected.groupby("kind"):
        n = len(population[population.kind == kind])
        print(f"  {kind:10s} {len(group):3d} of {n:3d}   weight {group.weight.iloc[0]:.2f}")
    print_instructions()
    return sheet


def _cached_text() -> dict[tuple[str, str], str]:
    """(provider, clip_id) to transcribed text, from the response cache."""
    texts: dict[tuple[str, str], str] = {}
    for provider_dir in sorted(config.CACHE.glob("*")):
        if not provider_dir.is_dir() or provider_dir.name.startswith("_"):
            continue
        for path in sorted(provider_dir.glob("*.json")):
            record = json.loads(path.read_text())
            texts[(record["provider"], record["clip_id"])] = record.get("text", "")
    return texts


def print_instructions() -> None:
    """SPEC prompt 05 task 4: 8 lines or fewer, definitions verbatim."""
    print("\nLabeling, 100 rows, about 3 to 4 hours:")
    print(
        "  Open taxonomy/labeling.html, play each clip, read reference against hypothesis."
    )
    print("  Pick one code and one severity per row, then Export to download the CSV.")
    print(
        "  Codes: "
        + "; ".join(f"{code} {meaning}" for code, meaning in CODE_DEFINITIONS)
    )
    print(
        "  Severity: "
        + "; ".join(f"{code} {meaning}" for code, meaning in SEVERITY_DEFINITIONS)
    )
    print(
        "  Ask of each row: would this change what a clinician does, if nobody caught it?"
    )
    print("  Save the export over taxonomy/failure_taxonomy.csv when finished.")


def _write_labeling_page(sheet: pd.DataFrame, manifest: pd.DataFrame) -> None:
    """A single self-contained page: audio, diff, dropdowns, CSV export."""
    try:
        lexicon = load_lexicon()
    except Exception:
        # The page is still usable without the directory lookup, just harder to
        # label. Losing the whole page over it would be worse.
        lexicon = set()

    payload = []
    for _, row in sheet.iterrows():
        # Read the evidence off the excerpts, which are what the labeller sees
        # and which centre on the changed words by construction.
        plain = lambda text: str(text).replace("*", "")
        evidence = drug_evidence(
            plain(row["ref_excerpt"]), plain(row["hyp_excerpt"]), lexicon
        )
        payload.append(
            {
                "finding_id": int(row["finding_id"]),
                "clip_id": row["clip_id"],
                "provider": row["provider"],
                "accent": row["accent"],
                "tier": row["tier"],
                "domain": row["domain"],
                "ref": row["ref_excerpt"],
                "hyp": row["hyp_excerpt"],
                "flag": row["auto_flag"],
                "kind": row["kind"],
                "weight": float(row["weight"]),
                "expected": row["expected"],
                "heard_entity": row["heard"],
                "expected_drugs": evidence["expected"],
                "heard_drugs": evidence["heard_known"],
            }
        )

    (config.TAXONOMY / "labeling.html").write_text(
        _LABELING_TEMPLATE.replace("__ROWS__", json.dumps(payload, indent=1))
        .replace("__CODES__", json.dumps([code for code, _ in CODE_DEFINITIONS]))
        .replace(
            "__SEVERITIES__", json.dumps([code for code, _ in SEVERITY_DEFINITIONS])
        )
        .replace(
            "__CODE_HELP__",
            html.escape("; ".join(f"{c}: {m}" for c, m in CODE_DEFINITIONS)),
        )
        .replace(
            "__SEVERITY_HELP__",
            html.escape("; ".join(f"{c}: {m}" for c, m in SEVERITY_DEFINITIONS)),
        )
    )


_LABELING_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ScribeCheck failure taxonomy</title>
<style>
  :root { --bg:#fbfaf7; --fg:#1c1c1a; --line:#dcd8ce; --mark:#b23c17; --ok:#2f6b4f;
          --muted:#6b675e; --panel:#f2efe8; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16171a; --fg:#e8e6e1; --line:#33353a; --mark:#ff8a5c; --ok:#6fce9f;
            --muted:#9a968d; --panel:#1e2024; }
  }
  body { background:var(--bg); color:var(--fg); font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         margin:0; padding:24px; }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
           padding:12px 0; margin-bottom:16px; z-index:5; }
  h1 { font-size:20px; margin:0 0 6px; }
  .bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:13px; }
  .status { color:var(--muted); flex:1; min-width:220px; }
  .card { border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:14px; }
  .card.done { border-color:var(--ok); }
  .tags { font-size:12px; text-transform:uppercase; letter-spacing:.05em; opacity:.7; margin-bottom:8px; }
  .text { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; margin:6px 0; }
  .label { font-size:12px; opacity:.7; }
  mark { background:none; color:var(--mark); font-weight:700; }
  audio { width:100%; margin:8px 0; }
  select, input[type=text] { font-size:15px; padding:6px; background:var(--bg); color:var(--fg);
           border:1px solid var(--line); border-radius:5px; }
  select { margin-right:10px; }
  input[type=text] { width:min(360px,80%); }
  button { font-size:14px; padding:7px 13px; border-radius:6px; border:1px solid var(--line);
           background:var(--panel); color:var(--fg); cursor:pointer; }
  button.primary { background:var(--fg); color:var(--bg); }
  .done-tag { color:var(--ok); font-weight:600; font-size:13px; margin-left:6px; }
  .help { font-size:12px; opacity:.7; margin-top:4px; }
  .listen { font-size:13px; margin-left:4px; user-select:none; }
  .drugs { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px;
           background:var(--panel); border-radius:6px; padding:8px 10px; margin:8px 0; }
  .drugs b { color:var(--mark); }
  mark.judged { color:var(--bg); background:var(--mark); padding:1px 5px;
                border-radius:3px; font-weight:700; }
  .caveat { display:block; font-family:-apple-system,BlinkMacSystemFont,sans-serif;
            font-size:11px; color:var(--muted); margin-top:4px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:4px; }
</style>
</head>
<body>
<header>
  <h1>ScribeCheck failure taxonomy</h1>
  <div class="bar">
    <span class="status">
      <strong id="progress">0</strong> of <strong id="total">0</strong> labeled.
      <span id="saved"></span>
    </span>
    <button id="next">Next unlabeled</button>
    <button id="import">Import CSV</button>
    <button id="export" class="primary">Export CSV</button>
    <button id="clear">Clear</button>
    <input type="file" id="file" accept=".csv" hidden>
  </div>
  <div class="help">
    Work saves to this browser automatically as you type, so you can close the tab
    and pick up here. Export writes the CSV you keep; Import restores from one, which
    is how you move to another browser or machine.
  </div>
</header>
<div id="rows"></div>
<p class="help">Codes &mdash; __CODE_HELP__</p>
<p class="help">Severity &mdash; __SEVERITY_HELP__</p>
<script>
const ROWS = __ROWS__;
const CODES = __CODES__;
const SEVERITIES = __SEVERITIES__;
const STORAGE_KEY = "scribecheck-labels-v1";

// Keyed on clip and provider rather than row number, so labels survive the
// sheet being regenerated. Row order is a presentation detail; the pair is the
// identity of the thing being judged.
const keyOf = (r) => r.clip_id + "|" + r.provider + "|" + r.finding_id;

let state = {};

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    state = saved.labels || {};
    return saved.at || null;
  } catch (e) {
    // A corrupt entry must not take the page down with it: an unusable
    // restore is recoverable, a blank screen is not.
    console.warn("could not restore saved labels", e);
    state = {};
    return null;
  }
}

function save() {
  const at = new Date().toISOString();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ at, labels: state }));
    showSaved(at);
  } catch (e) {
    // Private browsing and a full quota both land here. Say so plainly rather
    // than letting hours of labelling vanish silently at the end.
    document.getElementById("saved").textContent =
      "NOT SAVING to this browser (" + e.name + "). Export often.";
  }
}

function showSaved(at) {
  const d = new Date(at);
  document.getElementById("saved").textContent =
    "Saved " + d.toLocaleTimeString() + ".";
}

function isDone(k) {
  return Boolean(state[k] && state[k].failure_code && state[k].severity);
}

function refresh() {
  let n = 0;
  for (const r of ROWS) {
    const k = keyOf(r);
    const card = document.getElementById("card-" + r.finding_id);
    const tag = document.getElementById("done-" + r.finding_id);
    if (isDone(k)) {
      n++;
      card.classList.add("done");
      tag.textContent = "labeled";
    } else {
      card.classList.remove("done");
      tag.textContent = "";
    }
  }
  document.getElementById("progress").textContent = n;
  document.getElementById("total").textContent = ROWS.length;
}

function markup(text) {
  // [[x]] is the entity this row is asking about. *x* is an ordinary diff.
  return String(text)
    .replace(/\[\[([^\]]+)\]\]/g, '<mark class="judged">$1</mark>')
    .replace(/\*([^*]+)\*/g, "<mark>$1</mark>");
}

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Whether a word is a real drug is a lookup, not a judgment, so the answer is
// shown rather than left to the labeller's pharmacology. It is what separates
// DRUG-SUB from DRUG-DEL: a drug replaced by another real drug reads as a
// valid sentence, a drug replaced by a non-word does not. Deliberately states
// the fact and suggests neither a code nor a severity.
function drugLine(r) {
  const expected = r.expected_drugs || [];
  const heard = r.heard_drugs || [];
  if (!expected.length && !heard.length) return "";
  const survived = expected.filter((d) => heard.includes(d));
  const arrived = heard.filter((d) => !expected.includes(d));
  const bits = [];
  if (expected.length)
    bits.push("expected <b>" + expected.map(escapeHtml).join(", ") + "</b>");
  if (survived.length)
    bits.push("survived <b>" + survived.map(escapeHtml).join(", ") + "</b>");
  if (arrived.length)
    bits.push("a different real drug appears: <b>" +
              arrived.map(escapeHtml).join(", ") + "</b>");
  if (expected.length && !heard.length)
    bits.push("no known drug in what was heard");
  return `<div class="drugs"><span class="label">drugs&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>` +
         bits.join(" &middot; ") +
         `<span class="caveat">checked against the openFDA prescription directory, ` +
         `which is partial: a word missing from it is probably not a drug, not certainly</span></div>`;
}

document.getElementById("rows").innerHTML = ROWS.map((r) => `
  <div class="card" id="card-${r.finding_id}">
    <div class="tags">#${r.finding_id} &middot; ${escapeHtml(r.provider)} &middot; ${escapeHtml(r.accent)}
      &middot; tier ${escapeHtml(r.tier)} &middot; ${escapeHtml(r.domain)} &middot; ${escapeHtml(r.flag)}</div>
    <audio controls preload="none" src="../data/audio/${encodeURIComponent(r.clip_id)}.wav"></audio>
    <div class="text"><span class="label">reference&nbsp;</span>${markup(escapeHtml(r.ref))}</div>
    <div class="text"><span class="label">heard&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>${markup(escapeHtml(r.hyp))}</div>
    <div class="drugs"><span class="label">this row&nbsp;</span>
      <b>${escapeHtml(r.kind)}</b> &middot; expected <b>${escapeHtml(r.expected)}</b>${
        r.heard_entity ? " &middot; heard <b>" + escapeHtml(r.heard_entity) + "</b>"
                       : " &middot; nothing recognisable in its place"}
      <span class="caveat">one error per row. Judge only the highlighted entity;
        other differences on the line belong to their own rows.</span></div>
    <div class="controls">
      <select data-row="${r.finding_id}" data-field="failure_code">
        <option value="">code...</option>
        ${CODES.map((c) => `<option value="${c}">${c}</option>`).join("")}
      </select>
      <select data-row="${r.finding_id}" data-field="severity">
        <option value="">severity...</option>
        ${SEVERITIES.map((s) => `<option value="${s}">${s}</option>`).join("")}
      </select>
      <input type="text" data-row="${r.finding_id}" data-field="note" placeholder="note (optional)">
      <label class="listen">
        <input type="checkbox" data-row="${r.finding_id}" data-field="needs_listen"> needs a listen
      </label>
      <span class="done-tag" id="done-${r.finding_id}"></span>
    </div>
  </div>`).join("");

const byRowId = {};
for (const r of ROWS) byRowId[r.finding_id] = r;

function restoreInputs() {
  for (const el of document.querySelectorAll("[data-row]")) {
    const r = byRowId[el.dataset.row];
    const saved = state[keyOf(r)];
    if (!saved) continue;
    const v = saved[el.dataset.field];
    if (v === undefined) continue;
    if (el.type === "checkbox") el.checked = Boolean(v);
    else el.value = v;
  }
}

document.getElementById("rows").addEventListener("input", (e) => {
  const rowId = e.target.dataset.row;
  if (!rowId) return;
  const r = byRowId[rowId];
  const k = keyOf(r);
  state[k] = state[k] || {};
  state[k][e.target.dataset.field] =
    e.target.type === "checkbox" ? e.target.checked : e.target.value;
  save();
  refresh();
});

document.getElementById("next").addEventListener("click", () => {
  const target = ROWS.find((r) => !isDone(keyOf(r)));
  if (!target) {
    alert("All " + ROWS.length + " rows are labeled.");
    return;
  }
  document.getElementById("card-" + target.finding_id)
    .scrollIntoView({ behavior: "smooth", block: "center" });
});

// Must stay in the same order as the row built below, or the export writes
// values under the wrong headings.
const HEADER = ["finding_id","clip_id","provider","accent","tier","domain",
                "kind","expected","heard","weight","ref_excerpt","hyp_excerpt",
                "auto_flag","needs_listen","failure_code","severity","note"];

document.getElementById("export").addEventListener("click", () => {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [HEADER.join(",")];
  for (const r of ROWS) {
    const s = state[keyOf(r)] || {};
    lines.push([r.finding_id, r.clip_id, r.provider, r.accent, r.tier, r.domain,
                r.kind, r.expected, r.heard_entity, r.weight,
                r.ref, r.hyp, r.flag,
                s.needs_listen ? "yes" : "",
                s.failure_code || "", s.severity || "", s.note || ""].map(esc).join(","));
  }
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "failure_taxonomy.csv";
  link.click();
  URL.revokeObjectURL(url);
});

// Minimal RFC 4180 reader: enough for our own export, which is the only file
// this is asked to read. Handles quoted fields, doubled quotes and newlines
// inside a field, because the excerpt columns contain commas.
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.length > 1);
}

document.getElementById("import").addEventListener("click", () =>
  document.getElementById("file").click());

document.getElementById("file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const rows = parseCsv(String(reader.result));
    if (!rows.length) { alert("That file has no rows."); return; }
    const head = rows[0];
    const col = (name) => head.indexOf(name);
    const iClip = col("clip_id"), iProv = col("provider"), iCode = col("failure_code");
    if (iClip < 0 || iProv < 0 || iCode < 0) {
      alert("That does not look like a ScribeCheck export: no clip_id, provider and failure_code columns.");
      return;
    }
    const iSev = col("severity"), iNote = col("note"), iListen = col("needs_listen");
    let restored = 0, skipped = 0;
    for (const r of rows.slice(1)) {
      const clip = r[iClip], prov = r[iProv];
      if (!clip || !prov) { skipped++; continue; }
      const k = clip + "|" + prov;
      const entry = {
        failure_code: r[iCode] || "",
        severity: iSev >= 0 ? r[iSev] || "" : "",
        note: iNote >= 0 ? r[iNote] || "" : "",
        needs_listen: iListen >= 0 && r[iListen] === "yes",
      };
      if (entry.failure_code || entry.severity || entry.note || entry.needs_listen) {
        state[k] = entry;
        restored++;
      }
    }
    save();
    restoreInputs();
    refresh();
    alert("Restored " + restored + " labeled rows." +
          (skipped ? " Skipped " + skipped + " rows with no clip_id or provider." : ""));
  };
  reader.readAsText(file);
  e.target.value = "";
});

document.getElementById("clear").addEventListener("click", () => {
  const n = ROWS.filter((r) => isDone(keyOf(r))).length;
  if (!confirm("Delete all " + n + " labels saved in this browser? Export first if you want them.")) return;
  state = {};
  localStorage.removeItem(STORAGE_KEY);
  for (const el of document.querySelectorAll("[data-row]")) {
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  }
  document.getElementById("saved").textContent = "Cleared.";
  refresh();
});

const restoredAt = load();
restoreInputs();
refresh();
if (restoredAt) showSaved(restoredAt);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
    sys.exit(0)
