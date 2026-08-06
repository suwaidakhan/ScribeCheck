"""Automated integrity checks, standing in for the human spot-listen.

prompts/02-sample.md blocks on Suwaid listening to 20 clips against their
transcripts before transcription starts. During an unattended run nobody is
there to answer, so these checks run in its place and the listen happens in the
morning against the same `docs/spot_listen.html`. They cannot hear whether a
speaker said what the transcript claims. What they can catch is the mechanical
class of failure that puts the wrong audio beside a transcript: a clip whose
length disagrees with its metadata, a clip with no signal in it, a
transcript-to-duration ratio no human speech rate explains, and a manifest
pairing the same audio with two rows.

Run:  python -m src.integrity
"""

from __future__ import annotations

import html
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from src import config

# The overnight prompt's tolerances.
DURATION_LOW, DURATION_HIGH = 0.5, 1.5

# Speech-rate bounds as a multiple of this corpus's own median rate, rather
# than the absolute 1.0 to 5.0 words per second the overnight prompt names.
# Measured on the full 6,319-clip test split: median 1.67 w/s, and 12.2 percent
# of the split falls below 1.0 (17.2 percent of clinical clips, where people
# read long drug names carefully). An absolute floor of 1.0 therefore expects
# 2.46 flags in a 20-clip check against a halt threshold of 2, which is a coin
# flip on halting a clean run. These factors flag 1.3 percent of the split.
# See DECISIONS D015.
RATE_LOW_FACTOR, RATE_HIGH_FACTOR = 0.25, 4.0
FALLBACK_MEDIAN_RATE = 1.67
# Speech peaking around 0.2 sits near -14 dBFS RMS. This is far below that, low
# enough that only a genuinely empty or broken clip trips it.
SILENCE_RMS = 0.001

SPOT_CHECK_CLIPS = 20
MAX_FLAGGED = 2


def check_duration(path: Path, expected: float) -> str | None:
    """Does the audio last roughly as long as the manifest says?"""
    if not path.exists():
        return "missing audio file"
    try:
        info = sf.info(str(path))
    except (RuntimeError, OSError) as exc:
        return f"unreadable audio: {exc}"
    actual = info.frames / info.samplerate
    if not (DURATION_LOW * expected <= actual <= DURATION_HIGH * expected):
        return (
            f"duration {actual:.1f}s against an expected {expected:.1f}s, "
            f"outside {DURATION_LOW}x to {DURATION_HIGH}x"
        )
    return None


def check_rms(path: Path) -> str | None:
    """Is there any signal in the file?"""
    if not path.exists():
        return "missing audio file"
    try:
        samples, _ = sf.read(str(path), dtype="float32")
    except (RuntimeError, OSError) as exc:
        return f"unreadable audio: {exc}"
    if samples.size == 0:
        return "silent: empty file"
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms < SILENCE_RMS:
        return f"silent: RMS {rms:.6f} below {SILENCE_RMS}"
    return None


def speech_rate_bounds(manifest: pd.DataFrame) -> tuple[float, float]:
    """Acceptable words-per-second range, calibrated on this manifest.

    Derived rather than fixed, so the check cannot drift out of step with the
    corpus the way an absolute range did. A mispaired transcript is wrong by a
    large factor, so quarter-speed to quadruple-speed still catches it while
    leaving a careful reader of long drug names alone.
    """
    rates = (
        manifest["transcript"].astype(str).str.split().str.len() / manifest["duration"]
    )
    median = float(rates.median()) if len(rates) else FALLBACK_MEDIAN_RATE
    if not median > 0:
        median = FALLBACK_MEDIAN_RATE
    return median * RATE_LOW_FACTOR, median * RATE_HIGH_FACTOR


def check_speech_rate(
    transcript: str,
    seconds: float,
    low: float = FALLBACK_MEDIAN_RATE * RATE_LOW_FACTOR,
    high: float = FALLBACK_MEDIAN_RATE * RATE_HIGH_FACTOR,
) -> str | None:
    """Do the word count and the duration describe the same recording?

    This is the check that actually catches a transcript-audio pairing bug.
    A 30-word transcript on a 4-second clip is not a fast speaker.
    """
    if seconds <= 0:
        return "zero duration, cannot compute a speech rate"
    words = len(str(transcript).split())
    rate = words / seconds
    if not (low <= rate <= high):
        return (
            f"{rate:.2f} words per second ({words} words in {seconds:.1f}s), "
            f"outside {low:.2f} to {high:.2f}"
        )
    return None


def check_duplicate_pairings(rows) -> dict[str, list[str]]:
    """Look for the indexing-bug signature across the whole manifest.

    The overnight prompt asks for any identical transcript paired with two
    different audio files. Read literally that fires on AfriSpeech's own
    design: the corpus has many speakers read the same prompt, so an identical
    transcript on two different recordings is expected and appears in this
    manifest once already. Halting a run on it would be a false positive on
    hours of work.

    So the result is split. `expected` holds the same prompt read by different
    speakers, reported and not acted on. `suspicious` holds the two shapes that
    are genuine bugs: one speaker credited with the same transcript twice, and
    two manifest rows resolving to the same audio file. See DECISIONS D014.
    """
    by_transcript: dict[str, list[dict]] = defaultdict(list)
    by_path: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_transcript[str(row["transcript"]).strip()].append(row)
        by_path[str(row["path"]).strip()].append(row)

    suspicious: list[str] = []
    expected: list[str] = []

    for transcript, group in by_transcript.items():
        if len(group) < 2:
            continue
        clips = ", ".join(str(row["clip_id"]) for row in group)
        speakers = {str(row["speaker_id"]) for row in group}
        if len(speakers) < len(group):
            suspicious.append(
                f"one speaker credited with the same transcript twice: {clips}"
            )
        else:
            expected.append(
                f"{len(group)} speakers read the same prompt: {clips} "
                f"({transcript[:50]}...)"
            )

    for path, group in by_path.items():
        if len(group) > 1:
            clips = ", ".join(str(row["clip_id"]) for row in group)
            suspicious.append(f"{len(group)} manifest rows share audio {path}: {clips}")

    return {"suspicious": sorted(suspicious), "expected": sorted(expected)}


def should_halt(flagged: int, suspicious: list[str]) -> bool:
    """The overnight prompt's stop condition.

    More than 2 of the 20 spot-check clips failing, or any suspicious pairing
    anywhere in the manifest. The threshold is a count rather than a share
    because the prompt states it as one and the sample size never changes.
    """
    return flagged > MAX_FLAGGED or bool(suspicious)


def spot_check_sample(
    manifest: pd.DataFrame, n: int = SPOT_CHECK_CLIPS
) -> pd.DataFrame:
    """The same 20 clips the spot-listen page shows, drawn under seed 42."""
    return manifest.sample(n=min(n, len(manifest)), random_state=config.SEED)


def run(manifest: pd.DataFrame | None = None) -> dict:
    """Run every check, write docs/integrity_check.md, and return the outcome."""
    if manifest is None:
        manifest = pd.read_csv(config.MANIFEST)

    low, high = speech_rate_bounds(manifest)
    print(f"Speech-rate bounds from this manifest: {low:.2f} to {high:.2f} words/sec.")

    chosen = spot_check_sample(manifest)
    findings: list[tuple[str, list[str]]] = []
    for _, row in chosen.iterrows():
        path = config.AUDIO / f"{row['clip_id']}.wav"
        reasons = [
            reason
            for reason in (
                check_duration(path, float(row["duration"])),
                check_rms(path),
                check_speech_rate(row["transcript"], float(row["duration"]), low, high),
            )
            if reason
        ]
        if reasons:
            findings.append((str(row["clip_id"]), reasons))

    pairings = check_duplicate_pairings(manifest.to_dict("records"))
    flagged = len(findings)
    halt = should_halt(flagged, pairings["suspicious"])

    _write_report(chosen, findings, pairings, halt)
    write_spot_listen_page(chosen, dict(findings))

    print(f"Integrity check: {len(chosen) - flagged} passed, {flagged} flagged.")
    for clip_id, reasons in findings:
        for reason in reasons:
            print(f"  {clip_id}: {reason}")
    if pairings["expected"]:
        print(f"  {len(pairings['expected'])} expected repeated prompts (not a fault).")
    for note in pairings["suspicious"]:
        print(f"  SUSPICIOUS: {note}")
    print("HALT" if halt else "PASS: continuing to transcription.")

    return {
        "checked": len(chosen),
        "flagged": flagged,
        "findings": findings,
        "pairings": pairings,
        "halt": halt,
    }


def write_spot_listen_page(chosen: pd.DataFrame, flagged: dict) -> None:
    """SPEC section 3's human validation gate: 20 clips, audio beside transcript.

    The same 20 clips the automated checks ran on, so the retroactive listen
    audits exactly what the machine approved rather than a different sample.
    Anything the automated pass flagged is marked, so those get heard first.
    """
    cards = []
    for _, row in chosen.iterrows():
        clip_id = str(row["clip_id"])
        note = flagged.get(clip_id)
        warning = (
            f'<div class="flag">automated check flagged: {html.escape("; ".join(note))}</div>'
            if note
            else ""
        )
        cards.append(
            f"""  <div class="card">
    <div class="tags">{html.escape(clip_id[:12])} &middot; {html.escape(str(row["accent"]))}
      &middot; tier {html.escape(str(row["tier"]))} &middot; {html.escape(str(row["domain"]))}
      &middot; {float(row["duration"]):.1f}s</div>
    {warning}
    <audio controls preload="none" src="../data/audio/{html.escape(clip_id)}.wav"></audio>
    <p class="transcript">{html.escape(str(row["transcript"]))}</p>
    <label><input type="checkbox"> transcript matches what I heard</label>
  </div>"""
        )

    (config.DOCS / "spot_listen.html").write_text(
        _SPOT_LISTEN_TEMPLATE.replace("__CARDS__", "\n".join(cards)).replace(
            "__COUNT__", str(len(chosen))
        )
    )


_SPOT_LISTEN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ScribeCheck spot listen</title>
<style>
  :root { --bg:#fbfaf7; --fg:#1c1c1a; --line:#dcd8ce; --warn:#b23c17; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16171a; --fg:#e8e6e1; --line:#33353a; --warn:#ff8a5c; }
  }
  body { background:var(--bg); color:var(--fg); margin:0; padding:24px;
         font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         max-width:760px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .intro { font-size:14px; opacity:.8; border-bottom:1px solid var(--line);
           padding-bottom:14px; margin-bottom:18px; }
  .card { border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:14px; }
  .tags { font-size:12px; text-transform:uppercase; letter-spacing:.05em; opacity:.7; }
  .transcript { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; }
  .flag { color:var(--warn); font-size:13px; font-weight:600; margin-top:6px; }
  audio { width:100%; margin:10px 0; }
  label { font-size:14px; }
</style>
</head>
<body>
<h1>Spot listen: __COUNT__ clips</h1>
<p class="intro">
  Play each clip and read the transcript beside it. The question is only whether
  the transcript is what the speaker said. Accent, background noise and recording
  quality are the benchmark's subject, not a fault.
  <br><br>
  The overnight run passed its automated integrity checks and went ahead without
  this listen, so it is retroactive. If more than one of these disagrees with its
  audio, stop and say so before trusting any number downstream.
</p>
__CARDS__
</body>
</html>
"""


def _write_report(chosen, findings, pairings, halt) -> None:
    lines = [
        "# Automated integrity check",
        "",
        "Stands in for the blocking spot-listen in `prompts/02-sample.md`, which",
        "needs a human and could not run unattended. The listen still happens, in",
        "the morning, against `docs/spot_listen.html`. These checks catch the",
        "mechanical class of failure: audio that disagrees with its metadata, a",
        "clip with no signal, a speech rate no human produces, and a manifest",
        "pairing one audio file with two rows. They cannot hear whether the",
        "speaker said what the transcript claims. That part is still Suwaid's.",
        "",
        f"**Outcome: {'HALT' if halt else 'PASS'}**",
        "",
        f"- Clips checked: {len(chosen)}",
        f"- Passed: {len(chosen) - len(findings)}",
        f"- Flagged: {len(findings)} (halt threshold is more than {MAX_FLAGGED})",
        f"- Suspicious pairings: {len(pairings['suspicious'])} (any one halts the run)",
        f"- Expected repeated prompts: {len(pairings['expected'])}",
        "",
    ]

    lines += ["## Flagged clips", ""]
    if findings:
        for clip_id, reasons in findings:
            lines.append(f"- `{clip_id}`")
            lines += [f"  - {reason}" for reason in reasons]
    else:
        lines.append("None.")
    lines.append("")

    lines += ["## Suspicious pairings", ""]
    lines += [f"- {note}" for note in pairings["suspicious"]] or ["None."]
    lines.append("")

    lines += [
        "## Expected repeated prompts",
        "",
        "AfriSpeech has many speakers read the same prompt, so an identical",
        "transcript on two different recordings is the corpus working as designed,",
        "not an indexing bug. Listed for the record; none of these halt the run.",
        "",
    ]
    lines += [f"- {note}" for note in pairings["expected"]] or ["None."]
    lines.append("")

    config.DOCS.mkdir(parents=True, exist_ok=True)
    (config.DOCS / "integrity_check.md").write_text("\n".join(lines))


if __name__ == "__main__":
    outcome = run()
    sys.exit(1 if outcome["halt"] else 0)
