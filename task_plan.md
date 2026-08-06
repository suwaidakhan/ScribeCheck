# ExecPlan: ScribeCheck overnight build (phases 01-05, API keys blocked)

Started 2026-08-05 20:00 local. Owner: Claude Code. Human: Suwaid Khan.

## 1. Purpose and Big Picture

Build a clinical ASR safety and equity benchmark. Measure whether commercial
speech-to-text transcribes the words that can hurt a patient (drug names, dosage
values, negations), and whether that accuracy holds across African English accents,
using AfriSpeech-200.

Five system configurations across four vendors: OpenAI Whisper, Deepgram nova-3
general, Deepgram nova-3-medical, AssemblyAI, Gemini Flash. Deepgram contributes two
configurations because the general-versus-medical delta is a finding in itself. Four
API keys, five runs, 400 clips, 2,000 transcriptions.

The product claim under test: headline WER is the wrong acceptance metric for
clinical dictation. The benchmark either supports that with numbers or fails to.
Both outcomes are publishable.

This is a public GitHub repo, a LinkedIn artifact, and an interview exhibit.
Quality bar is accordingly higher than "it runs."

Tonight's constraint from Suwaid: create free API keys where possible, spend no
money, stop where blocked, leave a brief. I cannot create accounts (safety rule),
and three of the four providers have no keyless free tier, so every transcription
call is blocked until morning. Everything upstream and downstream of the calls
themselves can be built and proven tonight.

## 2. Context and Orientation

Working directory `/Users/suwaid/ScribeCheck`, empty, not a git repo at start.
Kit unpacked at scratchpad `kit/scribecheck-kit/` (CLAUDE.md, SPEC.md, 7 prompts,
taxonomy template).

Local toolchain, verified:
- Python 3.13.7 at `/usr/local/bin/python3`. git 2.54.0. No ffmpeg. No uv.
- Disk free 104 GB. Well clear of the 8 GB dataset abort rule.

All required PyPI packages exist and declare Python 3.13 support (versions in §11).

## 3. Plan of Work

- **Phase 0** Internal research and alignment. DONE.
- **Phase 1** External research: dataset reachability, provider models and prices,
  package currency. DONE.
- **Phase 2** Scaffold (prompt 01). Repo, venv, deps, `.env.example`, git init,
  smoke test that reports honestly on the four missing keys.
- **Phase 3** Lexicon and sample (prompt 02a). openFDA drug lexicon; annotate the
  6,319-row test split; draw the 400-clip stratified sample; write `manifest.csv`.
- **Phase 4** Audio fetch (prompt 02b). Per-accent tarball download with byte
  projection, selective extraction, resample to 16 kHz mono WAV.
- **Phase 5** Integrity check and spot-listen page (prompt 02c + overnight
  substitution). Four automated checks, `docs/integrity_check.md`,
  `docs/spot_listen.html`.
- **Phase 6** Transcribe module (prompt 03), written and unit-tested, NOT run.
  Cost projector runs for real against manifest durations.
- **Phase 7** Score module (prompt 04), written and unit-tested, proven end to end
  against a synthetic fixture cache. No real numbers possible.
- **Phase 8** Failures module (prompt 05), written and unit-tested, `labeling.html`
  built and rendered. No real rows possible.
- **Phase 9** MORNING_BRIEF.md, README, CI, final commits.
- **Phase 10 (optional, drop first if short)** Local faster-whisper validation run
  on 20 clips, cached in a namespace excluded from results, purely to prove
  `score.py` behaves on real audio rather than fixtures.

## 4. Concrete Steps

See §5. Steps are tracked as checkboxes with timestamps.

## 5. Progress

- [x] (19:55) Phase 0 internal research: kit read in full, all 7 prompts + SPEC + CLAUDE.md.
- [x] (20:05) Phase 1 external research: dataset structure, provider models/prices, PyPI.
- [ ] Phase 2 Scaffold
- [ ] Phase 3 Lexicon and sample
- [ ] Phase 4 Audio fetch
- [ ] Phase 5 Integrity check
- [ ] Phase 6 Transcribe module
- [ ] Phase 7 Score module
- [ ] Phase 8 Failures module
- [ ] Phase 9 Morning brief and polish
- [ ] Phase 10 Local validation run (optional)

## 6. Surprises and Discoveries

**S1. The SPEC's dataset access method no longer works.** AfriSpeech-200 is a
loading-script dataset (`afrispeech-200.py`). The `datasets` library dropped
script execution in v3.0; current release is 5.0.1. So
`load_dataset("intronhealth/afrispeech-200", "yoruba", streaming=True)`, which
SPEC section 3 assumes, cannot run. The HF dataset viewer confirms this
independently: `"The dataset viewer doesn't support this dataset because it runs
arbitrary Python code."`

The repo is public and ungated, and lays out cleanly as static files:
`transcripts/{accent}/{split}.csv`, a combined `transcripts/test.csv`,
`accents.json`, and `audio/{accent}/{split}/{split}_{accent}_{n}.tar.gz`.
Direct HTTPS download of the tarballs we need, with selective extraction, replaces
streaming. It is deterministic, resumable, and lets us project exact bytes before
downloading anything.

**S2. SPEC clip counts are slightly off.** SPEC section 2 says the test split holds
3,623 clinical and 2,723 general clips. The actual `transcripts/test.csv` has 6,319
rows: 3,607 clinical, 2,712 general, 108 accents, zero empty transcripts. Small
difference, but the manifest must be built from the real file, and the writeup must
quote the real numbers.

**S3. Column names differ from SPEC.** SPEC names `speaker_id` and `path`. The CSV
has `user_ids` and `audio_paths` (plus `audio_ids`, `idx`, `nchars`, `origin`).
Mapping is recorded in DECISIONS.md.

**S4. No free path to three of the four providers.** OpenAI has no free tier for
audio and needs a paid balance (USD 5 minimum top-up). Deepgram and AssemblyAI both
give free credit, but only after account signup, which I am not permitted to do.
Gemini has a free tier but needs a Google sign-in. So phase 03 is fully blocked and
phases 04 and 05 cannot produce real numbers. This is the whole reason tonight ends
with a tested pipeline rather than results.

**S5. openFDA needs no key** and exposes 136,765 NDC records. It also contains
cosmetics and supplements (first record returned was a tinted sunscreen), so the
lexicon build needs harder filtering than SPEC's blocklist alone.

## 7. Decision Log

| Decision | Alternative | Reasoning | Time |
|---|---|---|---|
| Fetch audio by direct tarball download + selective extract | `datasets` streaming per SPEC 3 | Streaming is impossible: script datasets removed in datasets 3.0. Direct download also gives exact byte projection before committing to a download, which serves the 8 GB abort rule better than streaming did. | 20:05 |
| Use `transcripts/test.csv` as the split source | Per-accent CSVs concatenated | One file, one fetch, identical content, and the split field is present for verification. | 20:05 |
| Resample with soundfile + soxr | librosa per SPEC requirements | No ffmpeg on this machine; librosa pulls numba for a job that is one resample call. soxr is the same algorithm family, a small wheel, and has a 3.13 build. librosa stays in requirements for anyone reproducing. | 20:06 |
| Deepgram `nova-3` and `nova-3-medical` | nova-2 variants named in older docs | Current per Deepgram model docs, verified tonight. SPEC section 4 explicitly says check the console for current names and record substitutions. | 20:06 |
| Write and test 03/04/05 tonight against fixtures, do not call providers | Wait for keys and build in the morning | The failure mode this project can least afford is discovering a scoring bug after burning API credit on 2,000 calls. Building and testing the harness first is free; running it is not. | 20:07 |

## 8. Validation and Acceptance

- Phase 2: `pytest` runs, venv installs, smoke test prints one pass/fail line per
  check and does not claim a key works when it does not.
- Phase 3: manifest has 400 rows and every SPEC section 3 quota is printed and
  passes: tier split, domain split, accents per tier, per-accent cap, entity
  coverage, duration bounds.
- Phase 4: 400 WAVs on disk, each 16 kHz mono, each duration within tolerance of
  the manifest value.
- Phase 5: `docs/integrity_check.md` written; stop condition evaluated and obeyed.
- Phases 6-8: unit tests pass with real assertions on arguments and outputs, not
  smoke tests. Score module reproduces identical numbers on a rerun of the same
  fixture cache.
- Phase 9: MORNING_BRIEF.md states plainly what ran, what did not, and what it
  costs him to unblock it.

## 9. Idempotence and Recovery

Every stage is resumable. Tarballs cache to `data/tarballs/` (gitignored) and are
skipped if present. Extracted WAVs are skipped if present. Provider responses cache
to `data/cache/{provider}/{clip_id}.json` and are never re-requested. `manifest.csv`
is deterministic under seed 42 and is committed, so a rerun that produces a
different manifest is a bug and will be visible in the diff.

## 10. Interfaces and Dependencies

- huggingface.co (anonymous HTTPS, public dataset, no token)
- api.fda.gov `/drug/ndc.json` (no key)
- Blocked until morning: OPENAI_API_KEY, DEEPGRAM_API_KEY, ASSEMBLYAI_API_KEY,
  GOOGLE_API_KEY. All four live in `.env`, gitignored from the first commit.

## 11. Artifacts and Notes

Dataset, verified 2026-08-05 [VERIFIED: https://huggingface.co/api/datasets/intronhealth/afrispeech-200]
- public, ungated, CC-BY-NC-SA-4.0, 478 files, 120 accents, 108 with a test split.
- `transcripts/test.csv`: 6,319 rows, 3,607 clinical / 2,712 general, 0 empty.
- `accents.json`: 121 keys (120 accents + `all`). `all.test` = 6,319 clips, 67,263 s.
- Test tarball sizes measured: yoruba 522.5 MB, swahili 385.3 MB, igbo 280.3 MB,
  hausa 142.1 MB, zulu 137.0 MB, ijaw 46.1 MB, twi 43.8 MB.

Provider models and list prices, verified 2026-08-05
- OpenAI Whisper USD 0.006/min, no free tier [VERIFIED: https://developers.openai.com/api/docs/pricing]
- Deepgram `nova-3` / `nova-3-medical`, USD 0.0077/min pre-recorded, USD 200 signup credit [VERIFIED: https://developers.deepgram.com/docs/models-languages-overview and https://deepgram.com/pricing]
- AssemblyAI Universal-3.5 Pro, USD 0.21/hr = USD 0.0035/min, USD 50 signup credit [VERIFIED: https://www.assemblyai.com/pricing]
- Gemini Flash audio: free tier exists, per-account limits shown only in AI Studio, not published statically [UNVERIFIED numbers; handle 429 with backoff]

PyPI, all with Python 3.13 support: datasets 5.0.1, soundfile 0.14.0, librosa 0.11.0,
pandas 3.0.5, jiwer 4.0.0, whisper-normalizer 0.1.15, requests 2.34.2,
python-dotenv 1.2.2, tqdm 4.70.0, soxr 1.1.0, numpy 2.5.1, pytest 9.1.1.

## 12. Outcomes and Retrospective

To be filled at the end of the run.
