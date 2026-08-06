# MORNING_BRIEF

**The run stopped at phase 03. Every API key is missing, and I cannot create the
accounts that issue them.** Everything that does not need a key is built, tested
and verified. Everything that does is written, tested against stubs, and waiting.

Total cost to unblock it: **USD 5.00**, and USD 4.57 of that is change you will
not spend.

---

## What is on disk

| | |
|---|---|
| Sample | 400 clips, 71.5 minutes, 86 accents, drawn under seed 42 |
| Audio | 400 of 400 WAVs, 16 kHz mono, 132 MB, every clip found |
| Manifest | `data/manifest.csv`, committed, every SPEC section 3 quota passing |
| Drug lexicon | 4,865 terms from openFDA prescription products |
| Integrity check | 20 of 20 clips passed, 0 flagged, no suspicious pairings |
| Tests | 197 passing, including an end-to-end proof of the scoring path |
| Spend so far | USD 0.00 |

## What is blocked, and why

Three of the four providers have no keyless free tier, and I am not permitted to
create accounts or sign in as you. So phase 03 could not run, and phases 04 and
05 cannot produce real numbers without it. No amount of work on my side changes
that; it needs your hands for about twenty minutes.

| Provider | Key | Cost for this run | Free credit |
|---|---|---|---|
| OpenAI Whisper | `OPENAI_API_KEY` | USD 0.43 | none, needs a USD 5 minimum top-up |
| Deepgram nova-3 | `DEEPGRAM_API_KEY` | USD 0.55 | USD 200 on signup |
| Deepgram nova-3-medical | same key | USD 0.55 | covered by the same credit |
| AssemblyAI | `ASSEMBLYAI_API_KEY` | USD 0.25 | USD 50 on signup |
| Gemini Flash | `GOOGLE_API_KEY` | USD 0.00 | free tier |
| **Total** | | **USD 1.78** | cap is USD 20.00 |

Those are list price times 71.5 real audio minutes from your manifest, not an
estimate. OpenAI is the only genuine spend, and only because their minimum
top-up is USD 5 rather than because the run costs it.

## What to do

**1. Create four keys and paste them into `.env`. About 20 minutes.**

```bash
cp env.example .env
```

Then fill the four blanks. `env.example` names where each key comes from.
`.env` is gitignored and was never written by me.

**2. Run the rest. About 1 to 2 hours, unattended.**

```bash
.venv/bin/python -m src.transcribe && .venv/bin/python -m src.score && .venv/bin/python -m src.failures
```

It prints the projected cost before each provider, skips any clip it has
already cached, and stops before the call that would breach the USD 20 cap. If
it dies partway, run it again; nothing is re-requested.

**3. Spot-listen 20 clips. About 15 minutes.**

```bash
open docs/spot_listen.html
```

Retroactive, because the automated checks passed and the run went ahead. You are
checking one thing: is the transcript what the speaker said. Accent and recording
quality are the benchmark's subject, not a fault. If more than one of the twenty
disagrees with its audio, stop and say so before trusting any number downstream.

**4. Label 100 failures. 3 to 4 hours.**

```bash
open taxonomy/labeling.html
```

One code and one severity per row, then Export. This is the project. I have not
filled `failure_code`, `severity` or `note` and the code will refuse to; a guess
from me would contaminate the only part of this that has to be your judgment.

---

## What I found while building it

Four things worth knowing, because three of them would have produced confident
wrong numbers rather than an error.

**The kit's dataset access method no longer works.** SPEC section 3 assumes
`datasets` streaming. AfriSpeech-200 is a loading-script dataset and the library
dropped script execution in v3.0. HuggingFace's own viewer says the same. Audio
now comes from direct per-accent tarball downloads: 4.67 GB measured by HEAD
request before a byte moved, against the 8 GB abort rule, streamed so the 4.6 GB
we do not want is discarded rather than stored. `D001`

**The drug lexicon was measuring the word "pain".** Built straight from openFDA
as SPEC describes, its five most frequent matches against your 3,607 real
clinical transcripts were pain (91 clips), body (51), clear (37), muscle (36) and
head (26). All are genuine NDC brand names on OTC products. Drug accuracy would
have measured how well each provider transcribes ordinary English. Rebuilt around
provenance: generic names and active ingredients are trusted, single-word brand
names must not be dictionary words. Running everything through a dictionary was
the obvious alternative and is wrong the other way, since morphine, heparin,
insulin, aspirin and codeine are all dictionary words and all drugs. `D008` to
`D011`

**Clip IDs collided.** I keyed clips on the audio filename. 46 filenames in the
test split appear under two session directories: the same prompt read by two
speakers, same name, different durations. Extraction would have written one clip
over the other and left a row pairing one speaker's audio with another's
transcript. Now keyed on `audio_ids`. Caught by the manifest's own duplicate
check. `D012`

**The integrity check halted the run on a false positive.** Its speech-rate
window of 1.0 to 5.0 words per second flagged 3 of 20 clips, one over the halt
threshold. None had anything wrong. This corpus runs at a median 1.67 words per
second and 12.2 percent of the whole test split sits below 1.0, rising to 17.2
percent among clinical clips where people read long drug names carefully. The
absolute floor expected 2.46 flags in a 20-clip check whose threshold is 2, so
halting a clean run was close to a coin flip. Bounds are now derived from the
corpus median. 20 of 20 pass. `D015`

Also worth one line: your manifest contains one repeated transcript, "TABLET,
ORAL TADALAFIL, TADALAFIL, 5MG", read by two different speakers in etsako and
ikulu. Read literally, the overnight prompt's check 4 treats that as an indexing
bug and halts. It is AfriSpeech working as designed. The check now separates the
expected case from the two shapes that are genuine bugs. `D014`

Every decision is in `docs/DECISIONS.md` with its alternative and its reason.
Every event is in `docs/BUILD_LOG.md`.

## What I did not do

- Ran no provider. Spent nothing. Created no account.
- Filled no `failure_code`, `severity` or `note`.
- Touched neither prompt 06 nor prompt 07.
- Left the local-Whisper validation idea unbuilt. It would have given a real
  transcript for one system tonight, and it would also have been a different
  system from the one the benchmark names. Parked rather than smuggled in.

The scoring path is proven the honest way instead:
`tests/test_pipeline_end_to_end.py` plants one drug substitution, one dose value
error, one unit error and one dropped negation into otherwise perfect
transcripts, then asserts the headline table reports those and nothing else. If
that passes and the real numbers still come out wrong, the fault is in the
provider responses or the manifest, not in the metrics.
