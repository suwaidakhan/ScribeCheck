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
    "row_id",
    "clip_id",
    "provider",
    "accent",
    "tier",
    "domain",
    "ref_excerpt",
    "hyp_excerpt",
    "entity_expected",
    "entity_transcribed",
    "auto_flag",
    "failure_code",
    "severity",
    "note",
]

CODE_DEFINITIONS = [
    ("DRUG-SUB", "one real drug transcribed as a different real drug"),
    ("DRUG-DEL", "drug name dropped or corrupted into a non-word"),
    ("DOSE-VAL", "numeric value changed"),
    ("DOSE-UNIT", "unit changed, value intact"),
    ("NEG-FLIP", "negation lost or inverted"),
    ("TERM-CORRUPT", "clinical term corrupted into a plausible-reading wrong term"),
    ("PHON-ACCENT", "error traceable to accent phonology (verify by listening)"),
    ("BENIGN", "error with no clinical meaning change"),
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
    """Write taxonomy/failure_taxonomy.csv and taxonomy/labeling.html."""
    scores_path = config.RESULTS / "per_clip_scores.csv"
    if not scores_path.exists():
        raise SystemExit(
            f"{scores_path} does not exist. Run `python -m src.score` first, "
            "which needs cached transcripts, which need the four API keys."
        )

    scores = pd.read_csv(scores_path)
    manifest = pd.read_csv(config.MANIFEST).set_index("clip_id")
    transcripts = _cached_text()

    selected = select_failures(scores)
    rows = []
    for row_id, (_, row) in enumerate(selected.iterrows(), start=1):
        clip_id = row["clip_id"]
        reference = str(manifest.loc[clip_id, "transcript"])
        hypothesis = transcripts.get((row["provider"], clip_id), "")
        marked_ref, marked_hyp = mark_diff(reference, hypothesis)
        rows.append(
            {
                "row_id": row_id,
                "clip_id": clip_id,
                "provider": row["provider"],
                "accent": row["accent"],
                "tier": row["tier"],
                "domain": row["domain"],
                "ref_excerpt": excerpt(marked_ref),
                "hyp_excerpt": excerpt(marked_hyp),
                "entity_expected": manifest.loc[clip_id, "drug_terms"]
                or manifest.loc[clip_id, "dose_strings"]
                or "",
                "entity_transcribed": "",
                "auto_flag": row["auto_flag"],
                "needs_listen": "",  # Set in the page when a row needs audio.
                "failure_code": "",  # Suwaid's.
                "severity": "",  # Suwaid's.
                "note": "",  # Suwaid's.
            }
        )

    sheet = pd.DataFrame(rows, columns=SHEET_COLUMNS)
    config.TAXONOMY.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(config.TAXONOMY / "failure_taxonomy.csv", index=False)
    _write_labeling_page(sheet, manifest)

    print(f"Wrote {len(sheet)} rows to {config.TAXONOMY / 'failure_taxonomy.csv'}")
    print(f"Wrote {config.TAXONOMY / 'labeling.html'}")
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
    payload = []
    for _, row in sheet.iterrows():
        payload.append(
            {
                "row_id": int(row["row_id"]),
                "clip_id": row["clip_id"],
                "provider": row["provider"],
                "accent": row["accent"],
                "tier": row["tier"],
                "domain": row["domain"],
                "ref": row["ref_excerpt"],
                "hyp": row["hyp_excerpt"],
                "entity": row["entity_expected"],
                "flag": row["auto_flag"],
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
const keyOf = (r) => r.clip_id + "|" + r.provider;

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
    const card = document.getElementById("card-" + r.row_id);
    const tag = document.getElementById("done-" + r.row_id);
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
  return String(text).replace(/\*([^*]+)\*/g, "<mark>$1</mark>");
}

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

document.getElementById("rows").innerHTML = ROWS.map((r) => `
  <div class="card" id="card-${r.row_id}">
    <div class="tags">#${r.row_id} &middot; ${escapeHtml(r.provider)} &middot; ${escapeHtml(r.accent)}
      &middot; tier ${escapeHtml(r.tier)} &middot; ${escapeHtml(r.domain)} &middot; ${escapeHtml(r.flag)}</div>
    <audio controls preload="none" src="../data/audio/${encodeURIComponent(r.clip_id)}.wav"></audio>
    <div class="text"><span class="label">reference&nbsp;</span>${markup(escapeHtml(r.ref))}</div>
    <div class="text"><span class="label">heard&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>${markup(escapeHtml(r.hyp))}</div>
    <div class="controls">
      <select data-row="${r.row_id}" data-field="failure_code">
        <option value="">code...</option>
        ${CODES.map((c) => `<option value="${c}">${c}</option>`).join("")}
      </select>
      <select data-row="${r.row_id}" data-field="severity">
        <option value="">severity...</option>
        ${SEVERITIES.map((s) => `<option value="${s}">${s}</option>`).join("")}
      </select>
      <input type="text" data-row="${r.row_id}" data-field="note" placeholder="note (optional)">
      <label class="listen">
        <input type="checkbox" data-row="${r.row_id}" data-field="needs_listen"> needs a listen
      </label>
      <span class="done-tag" id="done-${r.row_id}"></span>
    </div>
  </div>`).join("");

const byRowId = {};
for (const r of ROWS) byRowId[r.row_id] = r;

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
  document.getElementById("card-" + target.row_id)
    .scrollIntoView({ behavior: "smooth", block: "center" });
});

const HEADER = ["row_id","clip_id","provider","accent","tier","domain",
                "ref_excerpt","hyp_excerpt","entity_expected","entity_transcribed",
                "auto_flag","failure_code","severity","needs_listen","note"];

document.getElementById("export").addEventListener("click", () => {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [HEADER.join(",")];
  for (const r of ROWS) {
    const s = state[keyOf(r)] || {};
    lines.push([r.row_id, r.clip_id, r.provider, r.accent, r.tier, r.domain,
                r.ref, r.hyp, r.entity, "", r.flag,
                s.failure_code || "", s.severity || "",
                s.needs_listen ? "yes" : "", s.note || ""].map(esc).join(","));
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
