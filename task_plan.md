# ExecPlan: ScribeCheck

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

**Shipped.** Phases 2 through 5 complete and verified against real data. Phases
6 through 8 written and tested against fixtures, blocked on API keys. Phase 9
complete. Phase 10 dropped on purpose, see below. Four commits, 197 tests, USD
0.00 spent.

- 400-clip manifest, deterministic under seed 42, every SPEC section 3 quota
  passing, committed.
- 400 of 400 WAVs on disk at 16 kHz mono, 132 MB kept from 4.67 GB streamed.
- 4,865-term drug lexicon, checked against 3,607 real clinical transcripts
  before being trusted.
- Integrity check passing 20 of 20, spot-listen page rendered and verified in a
  browser, audio paths confirmed to resolve.
- Scoring, failure selection and the labeling page proven end to end against
  transcripts carrying known planted errors.

**What the night actually bought.** Not results. Four bugs found and fixed that
would each have produced confident wrong numbers rather than a visible error:
the lexicon measuring the word "pain", clip IDs colliding on a non-unique
filename, the spend cap overshooting by one clip, and an integrity threshold
miscalibrated badly enough to halt clean runs at close to even odds. Every one
of those was caught by looking at the artifact rather than the mechanism. The
lexicon looked fine as code and as a 14,481-line file; it only looked wrong when
counted against real transcripts.

**What went wrong in my own process.** The audio download died on the first
attempt and wrote nothing, because I handled network errors inside the download
loop and not inside the size-projection loop that ran before it. That is the
optimistic-path failure, in code written the same hour I wrote a decision entry
about resumability. Cost about twenty minutes and a restart.

**Phase 10 dropped deliberately.** A local faster-whisper run would have given
real transcripts for one system overnight, and would also have been a different
system from the one SPEC names. It was named and parked rather than started
quietly, which is the rule it would have broken.

**For the morning.** The blocker is four API keys and about twenty minutes of
Suwaid's hands. Real projected spend is USD 1.78, of which USD 0.43 is genuinely
out of pocket, inflated to USD 5.00 only by OpenAI's minimum top-up. See
`MORNING_BRIEF.md`.

---

## 13. Publication, 2026-08-06

Published at https://github.com/suwaidakhan/ScribeCheck, public.

The audit ran before the push rather than after, because a leaked key stays in
history and a stale document is read by everyone who arrives. It found four
things. No secrets, confirmed by searching every blob in every commit for all
four live keys rather than checking the working tree. A personal email address
in two files that a stranger would read. No LICENSE, which left the code
all-rights-reserved and unusable by anyone. And `MORNING_BRIEF.md`, which still
said "Ran no provider. Spent nothing." That was true at 04:20 and would have
been the second file a visitor opened.

Every published number was recomputed from `results/headline.csv` rather than
retyped, which caught the nova-3-medical delta: 8.97 points, so 9.0 rather than
the 8.9 first written.

Verified as a stranger sees it, by cloning the public URL fresh: no `.env`, no
audio, no cache, 220 tests passing with no keys present.


---

# ExecPlan addendum: evaluation harness v2

Opened 2026-08-14. Trigger: Suwaid labelled twelve rows and found four defects
the 228-test suite did not catch. Full analysis in `docs/PRD_EVAL_V2.md`, 15
weaknesses with measured blast radius.

## Purpose

Make the labelling instrument trustworthy before any labels are recorded
against it. Today three defects would put wrong numbers in the writeup and two
ask the labeller questions the screen does not contain the answer to.

## Phases

- **A. Blocking.** W1 false substitutions, W2 the excerpt, W3 sampling
  disclosure, W6 a code for no error. Nothing may be labelled until these land.
  Scoring and display only, no API calls, no cost.
- **B. Before any number is published.** W9 spoken punctuation, W11 recall-only
  drug accuracy, W13 paired significance test.
- **C. Before the taxonomy is called sound.** W4 the lexicon, W5 multiple
  errors per row, W7 intra-rater reliability, W8 a calibration pass.
- **D. Writeup framing.** W14 prior art, W15 potential against realised harm,
  W12 speaker-clustered intervals, W10 an uncertainty flag.

## Method, per `~/.claude/rules/common/coding-style.md`

- TDD without exception. Failing test first, RED confirmed in the transcript,
  then the implementation, then refactor. Every weakness above has a
  reproduction already measured against real data, so each starts as a test
  that encodes that reproduction.
- Surgical diffs. W1 is a candidate-filter change inside one function. W2 is a
  centring change inside one function. Neither is licence to restructure
  scoring.
- No new abstraction without a second caller. The temptation here is a general
  "entity span" object; it gets built only if W3 option 3 is chosen and two
  callers exist.
- Minimum code for the problem in front of us. W6 is a list entry, not a
  taxonomy redesign.
- Catch the four repeat failures. The Kitchen Sink is the live risk: 15
  weaknesses is an invitation to rewrite the pipeline. Phase A is four fixes
  and stops there.

## Definition of done, phase A

- `score_drugs` returns deletion, not substitution, when a drug is mangled into
  a non-word beside a correctly transcribed different drug. Reproduction test
  green.
- Every one of the 100 rows displays every clinical entity present in its
  transcripts. Measured, not asserted: the count of rows hiding a drug, dose or
  negation is 0, down from 15.
- RESULTS states the sampling scheme and forbids computing a rate from the
  sheet.
- `NO-ERROR` exists and is distinct from `BENIGN`.
- Full suite green, and the browser check repeated on the regenerated page.

## Progress

- [x] A1 W1 false substitutions: 19 to 5, matches the manual audit
- [x] A2 W2 excerpt centring: rows hiding their entity, 15 to 0
- [x] A3 W3 stratified sampling with weights, not just a disclosure
- [x] A4 W6 NO-ERROR added, and DOSE-MISS which was missing entirely
- [x] A5 regenerated, browser-verified, both counts re-measured

---

## Phase A2, opened 2026-08-14 by Suwaid labelling rows 1 to 4

Phase A was declared done and he opened the sheet. Rows 1, 3 and 4 each exposed
a defect that 267 green tests did not, which is the third time this session that
the artifact was broken while the code that builds it was correct.

Ordering changed on his challenge: he asked why W4 was not being done first.
He was right. W11 counts drug mentions with the same lexicon, and the M2
denominator rests on it, so running Phase B first computes drug precision and
drug accuracy against a lexicon that is about to change. His ordering computes
each number once. Phase C therefore splits: W4 is pre-labelling, W7 and W8 stay
post-labelling because they need his labels to exist.

### What rows 1 to 4 exposed

- **W16, new. Collapsed transcripts are labelled per entity.** Row 1: the whole
  hypothesis was `so radiation of other force damaged tubular fracture of lotr
  is formula`. 118 of 2,000 transcripts score WER at or above 0.8; they produce
  57 percent of DOSE-MISS and 25 percent of DRUG-DEL, and 42 of the 150 sheet
  rows. Clip `8132758125fa0e31` collapsed for all five providers and contributed
  10 rows on its own, 6.7 percent of the labelling budget.
- **W5 was resolved wrongly.** It was closed as "MQM assigns one category per
  span, leave it". That answered a question he had not asked. He asked how to
  record several errors in one clip, and the sheet caps what he can record at
  what the detector proposed. Row 3: `glargine` became `nicaragine`, an insulin
  mangled into a non-word, and it produced no row at all, while the only row
  offered was a false DOSE-MISS on `22 units` that the hypothesis contains
  twice. On that clip the eval scored one error that is not real and missed the
  one that is.
- **W4 is larger than the 3 percent measured.** 2,363 of 4,865 lexicon entries
  are multi-word. `insulin glargine` is present; `glargine` and `insulin` are
  not. 131 clips contain a component word whose only entry is a longer phrase.
- **New, unnamed in the PRD: non-English hallucination.** Row 4 is Gemini
  emitting `Me le gusta oír sin titubear. Juan, ¿me hablas?` against a
  levothyroxine script. Gemini has 9 non-ASCII outputs, Whisper 2, the other
  three zero.

### Decision taken, collapsed transcripts

Keep them in the eval, take them out of the labelling. Collapse rate is a
provider finding in its own right: AAI 0.5 percent, dg-medical 5.5, Gemini 6.8,
dg-general 7.2, Whisper 9.5, a 19-fold spread. It is flat across accent tiers
(6.4 / 5.2 / 6.2), so it is a robustness result and not an equity one. Entity
metrics report with and without. What he does not do is click a dropdown 42
times to record something the WER column already holds.

### Tracks, run in parallel on his instruction

1. **findings.py, me.** `COLLAPSE_WER`, `collapse_finding`, `FINDING_KINDS`,
   and `findings_for` short-circuiting a collapsed transcript to one finding.
2. **lexicon.py, agent.** Single-token generic components under the existing
   dictionary and blocklist filters, plus a committed INN supplement. Must
   re-measure the top newly-matched terms against real transcripts, the D008
   method that caught `pain` in 91 clips.
3. **failures.py, agent.** Group the sheet by clip and provider, add an
   "add an error I found" control that is not gated on the detector, add the
   `ASR-COLLAPSE` code, carry a `source` column of `detector` or `human`.

### Definition of done, phase A2

- A collapsed transcript produces exactly one sheet row. Measured: rows drawn
  from transcripts at WER >= 0.8 falls from 42 of 150 to at most one per
  transcript.
- `glargine`, `insulin`, `paracetamol`, `chloroquine` and `rifampicin` are all
  in the lexicon, and the top 30 newly-matched terms against real transcripts
  contain no ordinary English word.
- He can add an error the detector never proposed, it survives a reload, and it
  exports with `source=human`.
- Every kind in `FINDING_KINDS` has a selectable code.
- Full suite green AND the page driven in a browser: label a detector row, add
  a human row, reload, export, read the CSV.

### Progress

- [x] A2-1 W16 measured: 118 collapsed transcripts, 42 of 150 rows, clip
      `8132758125fa0e31` alone contributing 10
- [x] A2-2 collapse rate by provider and tier computed, 19-fold spread, flat
      across tiers
- [x] A2-3 non-English hallucination counted per provider
- [x] A2-4 W16 written into the PRD with options and a recommendation
- [x] A2-5 `findings.py`: collapse short-circuit, RED confirmed then green
- [x] A2-6 lexicon rebuilt and re-measured: 4,865 to 5,347 terms, 145 to
      175 mentions, all five probes present, six false terms blocklisted
- [x] A2-6b W9 promoted out of phase B: 38 of 118 collapses were false,
      caused by transcribed punctuation. `strip_spoken_punctuation` added.
- [ ] A2-7 labelling page grouped, add-an-error control, ASR-COLLAPSE
- [ ] A2-8 regenerate, re-measure, browser-verify, commit
