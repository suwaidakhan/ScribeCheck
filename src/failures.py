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
import re
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
    # `detector` or `human`. The errors the labeller finds that the detector
    # never reported are the detector's measured false-negative rate, which is
    # a better artifact than the sheet on its own, so the export has to keep
    # them apart rather than blend them.
    "source",
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
    (
        "ASR-COLLAPSE",
        "the whole transcription failed, this is not an entity-level error",
    ),
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

    ref = normalize(unmark(str(reference)))
    hyp = normalize(unmark(str(hypothesis)))
    return {
        "expected": find_drug_mentions(ref, lexicon),
        "heard_known": find_drug_mentions(hyp, lexicon),
    }


def unmark(text: str) -> str:
    """Strip the page's own highlight marks back off the text.

    The judged entity arrives wrapped as `[[metformin]]`, which is not a token
    any lexicon contains, so the drug lookup silently returned nothing for the
    one word the labeller most needed named. The line exists to separate
    DRUG-SUB from DRUG-DEL and it was blank on exactly those rows.
    """
    return (
        re.sub(r"\[\[(?:[\d,]+\|)?", "", str(text)).replace("]]", "").replace("*", "")
    )


def marked_reference(reference: str, positions: list[int]) -> str:
    """Number every judged entity in the full reference to match its finding.

    A card can carry ten findings against one sentence. Reading order does not
    identify them, because the sheet is a stratified sample and arrives ordered
    by kind, so the highlight has to say which finding below is asking about it.
    A position of -1 marks nothing, which is what ASR-COLLAPSE wants: the thing
    that failed is the sentence, not a word in it.
    """
    tokens = reference.split()
    numbers: dict[int, list[int]] = {}
    for number, index in enumerate(positions, start=1):
        if 0 <= index < len(tokens):
            numbers.setdefault(index, []).append(number)
    for index, found in numbers.items():
        label = ",".join(str(number) for number in found)
        tokens[index] = f"[[{label}|{tokens[index]}]]"
    return " ".join(tokens)


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
    whole: dict[tuple[str, str], list[str]] = {}
    judged: dict[tuple[str, str], list[int]] = {}
    for finding_id, (_, row) in enumerate(selected.iterrows(), start=1):
        reference = normalize(str(manifest.loc[row["clip_id"], "transcript"]))
        hypothesis = normalize(str(transcripts[(row["provider"], row["clip_id"])]))
        shown_ref, shown_hyp = excerpt_around(
            reference, hypothesis, int(row["ref_index"])
        )
        # The card shows the transcript once, so it is collected per clip and
        # provider here, along with the position of every entity a finding on
        # that card is asking about.
        pair = (row["provider"], row["clip_id"])
        whole.setdefault(pair, [reference, hypothesis])
        judged.setdefault(pair, []).append(
            -1 if row["kind"] == "ASR-COLLAPSE" else int(row["ref_index"])
        )
        sheet_rows.append(
            {
                "finding_id": finding_id,
                "source": "detector",
                "clip_id": row["clip_id"],
                "provider": row["provider"],
                "accent": row["accent"],
                "tier": row["tier"],
                "domain": row["domain"],
                "kind": row["kind"],
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

    texts = {
        pair: (marked_reference(reference, judged[pair]), hypothesis)
        for pair, (reference, hypothesis) in whole.items()
    }

    sheet = pd.DataFrame(sheet_rows, columns=SHEET_COLUMNS)
    config.TAXONOMY.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(config.TAXONOMY / "failure_taxonomy.csv", index=False)
    config.RESULTS.mkdir(parents=True, exist_ok=True)
    population.to_csv(config.RESULTS / "all_findings.csv", index=False)
    _write_labeling_page(sheet, texts)

    print(f"Wrote {len(sheet)} rows to {config.TAXONOMY / 'failure_taxonomy.csv'}")
    print(f"{len(sheet)} findings on {len(texts)} transcripts, one card each")
    print(f"Wrote {config.RESULTS / 'all_findings.csv'} ({len(population)} findings)")
    print(f"Wrote {config.TAXONOMY / 'labeling.html'}")
    print("\nSampling, so a rate can be computed from the labels:")
    for kind, group in selected.groupby("kind"):
        n = len(population[population.kind == kind])
        print(
            f"  {kind:10s} {len(group):3d} of {n:3d}   weight {group.weight.iloc[0]:.2f}"
        )
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
    print("\nLabeling, about 3 to 4 hours:")
    print(
        "  Open taxonomy/labeling.html. One card per recording: play it, read it once,"
        " then judge each finding listed under it."
    )
    print(
        "  Pick one code and one severity per finding. Anything wrong that has no"
        " finding, add with 'Add an error I found'. Then Export."
    )
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


def _write_labeling_page(
    sheet: pd.DataFrame,
    texts: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> None:
    """A card per recording: audio, transcript once, every finding under it.

    The sheet is one row per finding, which is right for the CSV and wrong for
    the screen. Clip 8132758125fa0e31 arrived as rows 1, 7, 10, 12, 19, 24, 25,
    59, 83 and 88, so the same reference was read ten times before ten separate
    dropdowns. Grouping keeps the per-finding judgment and drops the rereading.

    `texts` carries the full transcript for a clip and provider, already marked
    with the numbered entities. Without it the card falls back to the first
    finding's excerpt, which is worse but still labellable.
    """
    try:
        lexicon = load_lexicon()
    except Exception:
        # The page is still usable without the directory lookup, just harder to
        # label. Losing the whole page over it would be worse.
        lexicon = set()

    cards = []
    for (clip_id, provider), group in sheet.groupby(
        ["clip_id", "provider"], sort=False
    ):
        findings = []
        for position, (_, row) in enumerate(group.iterrows(), start=1):
            # Read the evidence off the excerpts, which centre on the changed
            # words by construction.
            evidence = drug_evidence(row["ref_excerpt"], row["hyp_excerpt"], lexicon)
            findings.append(
                {
                    "finding_id": int(row["finding_id"]),
                    "position": position,
                    "source": row["source"],
                    "kind": row["kind"],
                    "flag": row["auto_flag"],
                    "weight": float(row["weight"]),
                    "expected": row["expected"],
                    "heard_entity": row["heard"],
                    "ref_excerpt": row["ref_excerpt"],
                    "hyp_excerpt": row["hyp_excerpt"],
                    "expected_drugs": evidence["expected"],
                    "heard_drugs": evidence["heard_known"],
                }
            )
        first = group.iloc[0]
        shown = (texts or {}).get(
            (provider, clip_id), (first["ref_excerpt"], first["hyp_excerpt"])
        )
        cards.append(
            {
                "clip_id": clip_id,
                "provider": provider,
                "accent": first["accent"],
                "tier": first["tier"],
                "domain": first["domain"],
                "ref": shown[0],
                "hyp": shown[1],
                "findings": findings,
            }
        )

    (config.TAXONOMY / "labeling.html").write_text(
        _LABELING_TEMPLATE.replace("__CARDS__", json.dumps(cards, indent=1))
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
  .card { border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:18px; }
  .card.done { border-color:var(--ok); }
  .tags { font-size:12px; text-transform:uppercase; letter-spacing:.05em; opacity:.7; margin-bottom:8px; }
  .text { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; margin:6px 0; }
  .label { font-size:12px; opacity:.7; }
  mark { background:none; color:var(--mark); font-weight:700; }
  audio { width:100%; margin:8px 0; }
  .legacy { background:#fff4e5; border:1px solid #e0a458; border-radius:6px;
            padding:12px 14px; margin:0 0 14px; line-height:1.5; }
  .legacy button { margin-left:6px; }
  select, input[type=text] { font-size:15px; padding:6px; background:var(--bg); color:var(--fg);
           border:1px solid var(--line); border-radius:5px; }
  select { margin-right:10px; }
  input[type=text] { width:min(320px,80%); }
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
  mark.judged sup { color:var(--bg); opacity:.85; }
  .caveat { display:block; font-family:-apple-system,BlinkMacSystemFont,sans-serif;
            font-size:11px; color:var(--muted); margin-top:4px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:6px; }
  .finding { border-left:3px solid var(--line); padding:8px 0 8px 12px; margin:12px 0; }
  .finding.done { border-left-color:var(--ok); }
  .human-finding { border-left-style:dashed; }
  .entity { font-size:14px; }
  .entity b { color:var(--mark); }
  .entity sup { font-weight:700; margin-right:3px; }
  .add-human { margin-top:8px; }
</style>
</head>
<body>
<header>
  <h1>ScribeCheck failure taxonomy</h1>
  <div class="bar">
    <span class="status">
      <strong id="progress">0</strong> of <strong id="total">0</strong> findings labeled,
      <strong id="found">0</strong> added by hand.
      <span id="saved"></span>
    </span>
    <button id="next">Next unlabeled</button>
    <button id="import">Import CSV</button>
    <button id="export" class="primary">Export CSV</button>
    <button id="clear">Clear</button>
    <input type="file" id="file" accept=".csv" hidden>
  </div>
  <div class="help">
    One card per recording. Play it, read it once, then judge each finding under it.
    Work saves to this browser automatically as you type, so you can close the tab
    and pick up here. Export writes the CSV you keep; Import restores from one, which
    is how you move to another browser or machine.
  </div>
</header>
<div id="rows"></div>
<p class="help">Codes &mdash; __CODE_HELP__</p>
<p class="help">Severity &mdash; __SEVERITY_HELP__</p>
<script>
const CARDS = __CARDS__;
const CODES = __CODES__;
const SEVERITIES = __SEVERITIES__;
const STORAGE_KEY = "scribecheck-labels-v2";

// A card is one recording through one provider, which is the thing being
// listened to. Findings hang off it.
const cardKey = (c) => c.clip_id + "|" + c.provider;

// Keyed on what the finding is rather than where it sits in the sheet. Row
// numbers shift every time the sheet is regenerated; the clip, the provider,
// the kind and the expected entity do not, so labels survive a rebuild.
let counter = 0;
const byUid = {};
for (const c of CARDS) {
  const seen = {};
  for (const f of c.findings) {
    const base = cardKey(c) + "|" + f.kind + "|" + f.expected;
    seen[base] = (seen[base] || 0) + 1;
    f.key = base + "|" + seen[base];
    f.uid = "u" + ++counter;
    byUid[f.uid] = f;
  }
}

let state = {};   // one entry per detector finding, by finding key
let human = {};   // errors the detector never reported, by card key

// Row identity changed when the sheet moved to one card per transcript, so
// labels written by the previous page are keyed on a `finding_id` that no
// longer means the same finding. Applying them automatically would attach a
// human judgment to whichever error now happens to hold that number, which is
// worse than losing them. They are surfaced for rescue instead, and remapped
// offline where the mapping can be checked against the old sheet in git.
const LEGACY_STORAGE_KEY = "scribecheck-labels-v1";

function rescueLegacyLabels() {
  let legacy;
  try {
    legacy = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || "null");
  } catch (e) {
    return;
  }
  const count = Object.keys((legacy && legacy.labels) || {}).length;
  if (!count) return;

  const bar = document.createElement("div");
  bar.className = "legacy";
  bar.innerHTML =
    "<strong>" + count + " label" + (count === 1 ? "" : "s") +
    " from the previous version of this sheet are still in this browser.</strong> " +
    "They are not shown above, because row numbers changed and applying them " +
    "blind would attach your judgment to the wrong error. Download them and " +
    "send the file to be remapped. ";
  const button = document.createElement("button");
  button.textContent = "Download the old labels";
  button.addEventListener("click", () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(legacy, null, 2)], { type: "application/json" })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "scribecheck-labels-v1-rescue.json";
    link.click();
    URL.revokeObjectURL(url);
  });
  bar.appendChild(button);
  document.body.insertBefore(bar, document.body.firstChild);
}

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    state = saved.labels || {};
    human = saved.human || {};
    return saved.at || null;
  } catch (e) {
    // A corrupt entry must not take the page down with it: an unusable
    // restore is recoverable, a blank screen is not.
    console.warn("could not restore saved labels", e);
    state = {};
    human = {};
    return null;
  }
}

function save() {
  const at = new Date().toISOString();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ at, labels: state, human }));
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

const isDone = (saved) => Boolean(saved && saved.failure_code && saved.severity);

function markup(text) {
  // [[3|word]] is an entity a finding below is asking about, numbered to match
  // it. [[word]] is the same thing unnumbered. *word* is an ordinary diff mark.
  return String(text)
    .replace(/\[\[([\d,]+)\|([^\]]+)\]\]/g,
             '<mark class="judged">$2<sup>$1</sup></mark>')
    .replace(/\[\[([^\]]+)\]\]/g, '<mark class="judged">$1</mark>')
    .replace(/\*([^*]+)\*/g, "<mark>$1</mark>");
}

// The inverse of markup(), for text going into the CSV rather than the page.
const unmark = (t) => String(t)
  .replace(/\[\[(?:[\d,]+\|)?/g, "")
  .replace(/\]\]/g, "")
  .replace(/\*/g, "");

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Whether a word is a real drug is a lookup, not a judgment, so the answer is
// shown rather than left to the labeller's pharmacology. It is what separates
// DRUG-SUB from DRUG-DEL: a drug replaced by another real drug reads as a
// valid sentence, a drug replaced by a non-word does not. Deliberately states
// the fact and suggests neither a code nor a severity.
function drugLine(f) {
  const expected = f.expected_drugs || [];
  const heard = f.heard_drugs || [];
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
  return `<div class="drugs"><span class="label">drugs&nbsp;</span>` +
         bits.join(" &middot; ") +
         `<span class="caveat">checked against the openFDA prescription directory, ` +
         `which is partial: a word missing from it is probably not a drug, not certainly</span></div>`;
}

const options = (values, chosen) => values.map((v) =>
  `<option value="${v}"${v === chosen ? " selected" : ""}>${v}</option>`).join("");

// The same four controls for a detector finding and a human one. `attrs`
// carries whichever identity the input handler needs to route the change to.
function controls(attrs, saved) {
  return `
      <div class="controls">
        <select ${attrs} data-field="failure_code">
          <option value="">code...</option>${options(CODES, saved.failure_code)}
        </select>
        <select ${attrs} data-field="severity">
          <option value="">severity...</option>${options(SEVERITIES, saved.severity)}
        </select>
        <input type="text" ${attrs} data-field="note" placeholder="note (optional)"
               value="${escapeHtml(saved.note || "")}">
        <label class="listen">
          <input type="checkbox" ${attrs} data-field="needs_listen"${
            saved.needs_listen ? " checked" : ""}> needs a listen
        </label>
      </div>`;
}

function findingHtml(f) {
  const saved = state[f.key] || {};
  return `
    <div class="finding${isDone(saved) ? " done" : ""}" id="finding-${f.uid}">
      <div class="entity"><sup>${f.position}</sup><b>${escapeHtml(f.kind)}</b>
        &middot; expected <b>${escapeHtml(f.expected)}</b>${
        f.heard_entity ? " &middot; heard <b>" + escapeHtml(f.heard_entity) + "</b>"
                       : " &middot; nothing recognisable in its place"}
        <span class="done-tag" id="done-${f.uid}">${isDone(saved) ? "labeled" : ""}</span>
        <span class="caveat">${f.kind === "ASR-COLLAPSE"
          ? "Nothing is highlighted because nothing survived. The question is whether"
            + " this recording produced anything usable, not which entity failed."
          : "Judge only the highlighted entity marked " + f.position
            + ". The other errors on this recording are their own findings here."
        }</span></div>
      ${drugLine(f)}
      ${controls('data-uid="' + f.uid + '"', saved)}
    </div>`;
}

// Not gated on the detector. The errors it missed are the reason this control
// exists, so every card carries it whatever the detector did or did not say.
function humanHtml(ck, rec) {
  const attrs = `data-ck="${escapeHtml(ck)}" data-hid="${escapeHtml(rec.id)}"`;
  return `
    <div class="finding human-finding${isDone(rec) ? " done" : ""}">
      <div class="entity"><b>found by hand</b>
        <span class="caveat">an error the detector never reported. These become its
          measured false-negative rate, so they export as their own rows.</span></div>
      <div class="controls">
        <input type="text" ${attrs} data-field="expected" placeholder="what was expected"
               value="${escapeHtml(rec.expected || "")}">
        <input type="text" ${attrs} data-field="heard" placeholder="what was heard"
               value="${escapeHtml(rec.heard || "")}">
        <button class="remove-human" ${attrs}>remove</button>
      </div>
      ${controls(attrs, rec)}
    </div>`;
}

function cardHtml(c, index) {
  const n = c.findings.length;
  return `
  <div class="card" id="card-${index}">
    <div class="tags">${escapeHtml(c.provider)} &middot; ${escapeHtml(c.accent)}
      &middot; tier ${escapeHtml(c.tier)} &middot; ${escapeHtml(c.domain)}
      &middot; ${escapeHtml(String(c.clip_id).slice(0, 12))}
      &middot; ${n} finding${n === 1 ? "" : "s"}</div>
    <audio controls preload="none" src="../data/audio/${encodeURIComponent(c.clip_id)}.wav"></audio>
    <div class="text"><span class="label">reference&nbsp;</span>${markup(escapeHtml(c.ref))}</div>
    <div class="text"><span class="label">heard&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>${markup(escapeHtml(c.hyp))}</div>
    ${c.findings.map((f) => findingHtml(f)).join("")}
    <div class="human-rows" id="human-${index}"></div>
    <button class="add-human" data-card="${index}">+ Add an error I found</button>
    <span class="caveat">Anything wrong on this recording that has no finding above.
      Free text, and it does not have to match anything the detector saw.</span>
  </div>`;
}

function renderHuman(index) {
  const host = document.getElementById("human-" + index);
  if (!host) return;
  const ck = cardKey(CARDS[index]);
  host.innerHTML = (human[ck] || []).map((rec) => humanHtml(ck, rec)).join("");
}

function render() {
  document.getElementById("rows").innerHTML =
    CARDS.map((c, i) => cardHtml(c, i)).join("");
  CARDS.forEach((c, i) => renderHuman(i));
  refresh();
}

function refresh() {
  let done = 0, total = 0, found = 0;
  CARDS.forEach((c, i) => {
    let cardDone = 0;
    for (const f of c.findings) {
      total++;
      const labeled = isDone(state[f.key]);
      if (labeled) { done++; cardDone++; }
      const tag = document.getElementById("done-" + f.uid);
      if (tag) tag.textContent = labeled ? "labeled" : "";
    }
    found += (human[cardKey(c)] || []).length;
    const card = document.getElementById("card-" + i);
    if (!card) return;
    if (c.findings.length && cardDone === c.findings.length) card.classList.add("done");
    else card.classList.remove("done");
  });
  document.getElementById("progress").textContent = done;
  document.getElementById("total").textContent = total;
  document.getElementById("found").textContent = found;
}

document.getElementById("rows").addEventListener("input", (e) => {
  const field = e.target.dataset.field;
  if (!field) return;
  const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
  if (e.target.dataset.uid) {
    const f = byUid[e.target.dataset.uid];
    state[f.key] = Object.assign({}, state[f.key], { [field]: value });
  } else if (e.target.dataset.ck) {
    const rec = (human[e.target.dataset.ck] || []).find(
      (r) => r.id === e.target.dataset.hid);
    if (!rec) return;
    rec[field] = value;
  } else {
    return;
  }
  save();
  refresh();
});

const newId = () =>
  "h" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

function addHuman(index) {
  const ck = cardKey(CARDS[index]);
  human[ck] = (human[ck] || []).concat({
    id: newId(), expected: "", heard: "", failure_code: "", severity: "",
    note: "", needs_listen: false,
  });
  save();
  renderHuman(index);
  refresh();
}

function removeHuman(ck, hid) {
  human[ck] = (human[ck] || []).filter((r) => r.id !== hid);
  save();
  const index = CARDS.findIndex((c) => cardKey(c) === ck);
  if (index >= 0) renderHuman(index);
  refresh();
}

document.getElementById("rows").addEventListener("click", (e) => {
  if (e.target.classList.contains("add-human")) {
    addHuman(Number(e.target.dataset.card));
  } else if (e.target.classList.contains("remove-human")) {
    removeHuman(e.target.dataset.ck, e.target.dataset.hid);
  }
});

document.getElementById("next").addEventListener("click", () => {
  const index = CARDS.findIndex((c) => c.findings.some((f) => !isDone(state[f.key])));
  if (index < 0) {
    alert("Every finding is labeled.");
    return;
  }
  document.getElementById("card-" + index)
    .scrollIntoView({ behavior: "smooth", block: "center" });
});

// One list, so a heading and its value cannot drift apart. They were two
// hand-maintained lists once, they drifted, and every exported column shifted.
const COLUMNS = [
  ["finding_id",   (c, f) => f.finding_id],
  ["source",       (c, f) => f.source],
  ["clip_id",      (c) => c.clip_id],
  ["provider",     (c) => c.provider],
  ["accent",       (c) => c.accent],
  ["tier",         (c) => c.tier],
  ["domain",       (c) => c.domain],
  ["kind",         (c, f) => f.kind],
  ["expected",     (c, f) => f.expected],
  ["heard",        (c, f) => f.heard_entity],
  ["weight",       (c, f) => f.weight],
  // A detector finding exports its own excerpt, which marks the entity it
  // asked about. A human one has no such entity, so it exports the whole
  // transcript with the marks stripped: the numbers refer to findings that are
  // not this row.
  ["ref_excerpt",  (c, f) => f.ref_excerpt === undefined ? unmark(c.ref) : f.ref_excerpt],
  ["hyp_excerpt",  (c, f) => f.hyp_excerpt === undefined ? unmark(c.hyp) : f.hyp_excerpt],
  ["auto_flag",    (c, f) => f.flag],
  ["needs_listen", (c, f, s) => s.needs_listen ? "yes" : ""],
  ["failure_code", (c, f, s) => s.failure_code || ""],
  ["severity",     (c, f, s) => s.severity || ""],
  ["note",         (c, f, s) => s.note || ""],
];
const HEADER = COLUMNS.map((col) => col[0]);

// A human-found error takes the shape of a detector finding so it exports
// through the same columns, and `source` is what tells them apart. It carries
// no inclusion weight because it came from no sampled stratum.
function humanFinding(rec) {
  return {
    finding_id: rec.id,
    source: "human",
    kind: "HUMAN",
    expected: rec.expected || "",
    heard_entity: rec.heard || "",
    weight: "",
    flag: "found by the labeller",
  };
}

const HUMAN_FIELDS = ["expected", "heard", "failure_code", "severity", "note"];
const touched = (rec) =>
  HUMAN_FIELDS.some((f) => String(rec[f] || "").trim()) || Boolean(rec.needs_listen);

function exportLines() {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [HEADER.join(",")];
  for (const c of CARDS) {
    for (const f of c.findings)
      lines.push(COLUMNS.map((col) => esc(col[1](c, f, state[f.key] || {}))).join(","));
    for (const rec of human[cardKey(c)] || [])
      if (touched(rec))
        lines.push(COLUMNS.map((col) => esc(col[1](c, humanFinding(rec), rec))).join(","));
  }
  return lines;
}

document.getElementById("export").addEventListener("click", () => {
  const lines = exportLines();
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  // Timestamped, because a fixed name means the browser either overwrites the
  // previous export or silently appends "(1)", and in both cases the labeller
  // cannot tell which file holds which session's work. One export was already
  // lost to this.
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
  link.download = "failure_taxonomy-" + stamp + ".csv";
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

// Rebuilds the same keys the page generates, so a file exported before the
// sheet was regenerated still reattaches to its findings.
function importRows(rows) {
  const head = rows[0];
  const col = (name) => head.indexOf(name);
  const iClip = col("clip_id"), iProv = col("provider"), iCode = col("failure_code");
  if (iClip < 0 || iProv < 0 || iCode < 0) return null;
  const iSrc = col("source"), iKind = col("kind"), iExp = col("expected"),
        iHeard = col("heard"), iSev = col("severity"), iNote = col("note"),
        iListen = col("needs_listen");
  const at = (r, i) => (i >= 0 ? r[i] || "" : "");
  const labels = {}, found = {}, seen = {};
  let restored = 0, skipped = 0, added = 0;
  for (const r of rows.slice(1)) {
    const clip = r[iClip], prov = r[iProv];
    if (!clip || !prov) { skipped++; continue; }
    const ck = clip + "|" + prov;
    const entry = {
      failure_code: r[iCode] || "",
      severity: at(r, iSev),
      note: at(r, iNote),
      needs_listen: at(r, iListen) === "yes",
    };
    if (at(r, iSrc) === "human") {
      found[ck] = (found[ck] || []).concat(Object.assign(
        { id: newId(), expected: at(r, iExp), heard: at(r, iHeard) }, entry));
      added++;
      continue;
    }
    const base = ck + "|" + at(r, iKind) + "|" + at(r, iExp);
    seen[base] = (seen[base] || 0) + 1;
    if (entry.failure_code || entry.severity || entry.note || entry.needs_listen) {
      labels[base + "|" + seen[base]] = entry;
      restored++;
    }
  }
  return { labels, found, restored, skipped, added };
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
    const result = importRows(rows);
    if (!result) {
      alert("That does not look like a ScribeCheck export: no clip_id, provider and failure_code columns.");
      return;
    }
    state = result.labels;
    human = result.found;
    save();
    render();
    alert("Restored " + result.restored + " labeled findings and " + result.added +
          " added by hand." +
          (result.skipped ? " Skipped " + result.skipped +
                            " rows with no clip_id or provider." : ""));
  };
  reader.readAsText(file);
  e.target.value = "";
});

document.getElementById("clear").addEventListener("click", () => {
  const n = Object.keys(state).length +
            Object.values(human).reduce((total, rows) => total + rows.length, 0);
  if (!confirm("Delete all " + n + " labels saved in this browser? Export first if you want them.")) return;
  state = {};
  human = {};
  localStorage.removeItem(STORAGE_KEY);
  render();
  document.getElementById("saved").textContent = "Cleared.";
});

const restoredAt = load();
render();
rescueLegacyLabels();
if (restoredAt) showSaved(restoredAt);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
    sys.exit(0)
