# OVERNIGHT_RUN — unattended sequential run, phases 01 through 04, plus taxonomy sheet generation

Use this only after `.env` holds all four working API keys. This prompt runs prompts 01 through 04 back to back with no pause for confirmation, then generates, but does not fill, the failure taxonomy sheet from prompt 05, then stops.

One deliberate deviation from the individual prompt files, logged so it is auditable: prompts/02-sample.md specifies a blocking human spot-listen before transcription starts. No human is present during an overnight run, so replace that block with the automated integrity check defined below. This does not remove the human spot check, it defers it. `docs/spot_listen.html` is still generated exactly as specced, for review after waking up.

## Automated integrity check (replaces the blocking gate for this run only)

For every clip selected for `docs/spot_listen.html` (still 20, still random, still seed 42):

1. Confirm audio duration is within 0.5x to 1.5x the clip's expected duration from the manifest.
2. Compute RMS energy. Flag any clip below a silence threshold as having no meaningful audio.
3. Compute transcript word count divided by audio duration in seconds. Flag anything outside 1.0 to 5.0 words per second as an implausible speech rate. This range usually catches a transcript-audio pairing bug, not an unusually slow or fast speaker.
4. Scan the full 400-clip manifest for any identical transcript paired with two different audio files. This is a common indexing-bug signature.

Write `docs/integrity_check.md`: pass count, fail count, and every flagged clip with its reason.

**Stop the entire run and do not proceed to phase 03** only if more than 2 of the 20 spot-check clips fail, or if check 4 finds a duplicate-pairing bug anywhere in the manifest. Otherwise continue. Log the outcome in `docs/BUILD_LOG.md` either way.

## Sequence

Execute in order. No pause between steps unless a stop condition below fires.

1. Confirm `.env` holds four non-placeholder keys. If any is missing, stop now and write `MORNING_BRIEF.md` stating which key is missing and that nothing else ran.
2. Run prompts/01-scaffold.md in full.
3. Run prompts/02-sample.md in full, except: skip the closing instruction to stop and wait for spot-listen confirmation. Run the automated integrity check above instead, apply its stop condition, and continue if it passes.
4. Run prompts/03-transcribe.md in full. Cost rule for this unattended run: if a single provider's projected cost alone exceeds USD 20, skip that provider, log it clearly, and continue with the rest rather than halting everything. If total actual spend across all providers passes USD 20, stop starting new provider runs, finish whichever provider is mid-run, and log the stop.
5. Run prompts/04-score.md in full.
6. Run prompts/05-failures.md only through generating `taxonomy/failure_taxonomy.csv` (every column pre-filled except failure_code, severity, note) and `taxonomy/labeling.html`. Do not attempt to fill failure_code, severity, or note. Those are Suwaid's judgment calls. A guess from you would contaminate the one part of this project that has to be his.
7. Stop. Do not touch prompts/06 or prompts/07.

## On completion, or on any stop condition, write `MORNING_BRIEF.md` at the repo root

In this order:

- One line: did the run complete through step 6, or stop early, and why.
- The headline results table from `results/headline.csv`, rendered as a markdown table.
- Total actual spend, and spend per provider.
- Automated integrity check summary: pass and fail counts, any flagged clips.
- Every new entry added to `docs/DECISIONS.md` and `docs/BUILD_LOG.md` during this run.
- A numbered next-steps list with a time estimate per item. If the run completed cleanly this list has exactly two items:
  1. Open `docs/spot_listen.html` and confirm the 20 clips sound right against their transcripts. About 15 minutes. This is a retroactive check, since the run already proceeded past this gate on the automated check's approval.
  2. Open `taxonomy/labeling.html` and complete the 100-row failure taxonomy. 3 to 4 hours. This is the core judgment work of the project and the reason the benchmark is worth publishing under your name.

Do not summarize anything not asked for above. Do not editorialize on the findings. That happens in prompt 07, with Suwaid, after he has seen the numbers himself.
