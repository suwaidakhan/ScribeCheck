# CLAUDE.md, ScribeCheck

You are building a clinical ASR safety and equity benchmark with Suwaid Khan, a product manager. The split is deliberate: he sets the product direction, makes the judgment calls that move a result, labels the failures by hand, and owns the public writeup. You do the implementation, and you run and debug it.

That division is the point rather than a constraint. The classifications a reader is asked to trust, `failure_code` and `severity`, are the ones a model must never fill in, and the code refuses to. Everything else is his to direct and yours to build.

Read SPEC.md before any task. It defines the sampling design, metrics, taxonomy, and deliverables. SPEC.md wins over anything else, including this file, if they conflict.

## Project one-liner

Measure whether commercial speech-to-text systems transcribe the words that can hurt a patient (drug names, dosages, negations), and whether accuracy holds across 120 African English accents, using AfriSpeech-200.

## Hard guardrails

- Never download the full dataset. Transcript CSVs first, stratify on metadata, then fetch audio only for selected clips via per-accent streaming. Abort and report if projected download exceeds 8 GB.
- Spend cap: stop and report before any action projected to exceed USD 20 in API cost. Log estimated cost before each provider run and actual cost after.
- Secrets live in `.env` only. `.env` is in `.gitignore` from the first commit. Never print keys, never commit them, never place them in code.
- Cache every API response to disk keyed by clip_id and provider. Never re-call a provider for a clip that has a cached result. Every run must be resumable.
- Determinism: random seed 42 everywhere. The sample manifest is committed; scoring reruns must reproduce identical numbers.
- Never fabricate a number. If a metric cannot be computed, say so and show what blocked it.
- Do not upload dataset audio anywhere except to the ASR provider APIs for transcription. Do not commit audio files to git (gitignore `data/audio/`). The public repo carries the manifest, code, results, and up to 10 short illustrative clips only if license attribution is included.

## When the project finishes, the documents have to catch up

This is a public repository and a hiring artifact, so a document that describes
an earlier state of the work is worse than no document. It has already happened
once: `MORNING_BRIEF.md` still said "Ran no provider. Spent nothing" after all
2,000 transcriptions had run, and it was the second file a visitor opened.

So when the 100 failures are labelled and the writeup exists, the following are
stale by definition and every one of them gets revisited in the same pass:

- `README.md`, whose status line and headline claim both name the current phase
- `RESULTS.md`, which says the severity classification does not exist yet
- `CLAUDE.md`, this file, whose phase-by-phase framing stops applying
- `SPEC.md`, wherever the built thing diverged from the plan
- `docs/DECISIONS.md` and `docs/BUILD_LOG.md`, which are append-only and stay
- `task_plan.md`, section 12
- The GitHub profile README at `suwaidakhan/suwaidakhan`, which quotes the
  headline result and calls the labelling in progress

The check before publishing anything: does every number in a public document
still match `results/headline.csv`, and does every status claim still describe
what is on disk? Recompute rather than retype. That check has already caught a
wrong figure once.

## Working style

- One prompt file, one phase. Finish the phase, print the definition of done from the prompt, and confirm each item explicitly before stopping.
- When something fails, fix it and note the fix in `docs/BUILD_LOG.md` (one line per event). The build log becomes writeup material.
- Prefer boring, readable Python. pandas, jiwer, requests, datasets. No frameworks the project does not need.
- Any judgment call that changes the results (normalization choice, matching threshold, tier boundary) gets one line in `docs/DECISIONS.md`: decision, alternative, reason.

## Writing rules for anything public-facing (README, writeup, dashboard copy)

- No em-dashes or en-dashes. Restructure with a comma or period.
- Banned words: delve, tapestry, underscore, testament, pivotal, elevate, enhance, foster, garner, bolster, showcase, empower, leverage, unleash, drive (as a verb), implement, essential, impressive, robust, valuable, vital, crucial, significant, intricate, meticulous, furthermore, moreover, consequently, additionally, align (as a verb), utilize, game-changing, cutting-edge.
- No intensifiers: really, very, quite, pretty, fairly, just, simply.
- No mock-corrective adverbs: actually, in fact, in reality, the truth is, turns out.
- No "this isn't X, this is Y" contrast framing.
- Plain language first, technical detail second. Real numbers over vague claims.

## Repo layout (created in prompt 01)

```
scribecheck/
├── CLAUDE.md
├── SPEC.md
├── .env                  # keys, gitignored
├── .gitignore
├── requirements.txt
├── src/
│   ├── sample.py         # prompt 02
│   ├── lexicon.py        # prompt 02
│   ├── transcribe.py     # prompt 03
│   ├── score.py          # prompt 04
│   └── failures.py       # prompt 05
├── data/
│   ├── manifest.csv      # the committed 400-clip sample definition
│   ├── audio/            # gitignored
│   └── cache/            # provider responses, gitignored
├── results/              # committed CSVs and charts
├── taxonomy/             # failure sheet, template provided
├── dashboard/            # prompt 06
├── docs/                 # BUILD_LOG.md, DECISIONS.md, writeup draft
└── prompts/              # the phase prompts
```
