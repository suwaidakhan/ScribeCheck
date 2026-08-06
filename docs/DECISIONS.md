# DECISIONS.md

Every judgment call that changes a result or deviates from SPEC.md. One entry each:
decision, alternative, reason.

Format: `**Dnnn | area | decision | alternative | reason**`, grouped under a
dated section heading.

---

## 2026-08-05, phase 01 scaffold

**D001 | dataset access | Fetch audio by direct per-accent tarball download over
HTTPS and extract only the manifest clips. | `datasets` streaming with per-accent
configs, as SPEC section 3 specifies. | Streaming that dataset is no longer
possible. AfriSpeech-200 ships a loading script (`afrispeech-200.py`), and the
`datasets` library removed loading-script execution in version 3.0; the current
release is 5.0.1. HuggingFace's own dataset viewer reports the same thing: it
cannot preview the dataset because it runs arbitrary Python. The repo is public
and ungated, and its files are laid out predictably as
`audio/{accent}/{split}/{split}_{accent}_{n}.tar.gz`, so a direct fetch reads the
same bytes the streaming path would have. It is also better for the 8 GB abort
rule in CLAUDE.md: a HEAD request gives the exact size of every tarball before a
single byte of payload is downloaded, so the projection is measured rather than
estimated.

**D002 | split source | Use the combined `transcripts/test.csv`. | Concatenate the
108 per-accent `transcripts/{accent}/test.csv` files. | Same content in one fetch,
and it carries a `split` column that lets the loader verify it got what it asked
for. Verified 2026-08-05: 6,319 rows, 3,607 clinical, 2,712 general, 108 accents,
zero empty transcripts. SPEC section 2 quotes 3,623 clinical and 2,723 general;
the real file wins, and the writeup quotes the real numbers.

**D003 | column mapping | Map SPEC's field names onto the real CSV header:
`speaker_id` to `user_ids`, `path` to `audio_paths`, `audio` to the WAV extracted
from the tarball. | Rename columns in the manifest to match SPEC. | The manifest
keeps SPEC's names so downstream code reads as specified, and the mapping is
recorded here so the difference is auditable rather than silent. The CSV also
carries `idx`, `audio_ids`, `nchars` and `origin`, which SPEC does not mention.

**D004 | resampling | Resample 44.1 kHz source audio to 16 kHz mono with
`soundfile` plus `soxr`. | `librosa`, which SPEC's requirements list names. | No
ffmpeg on the build machine, and librosa pulls numba as a transitive dependency
for what is a single resample call. soxr is the same high-quality resampler family,
ships a small wheel with Python 3.13 support, and is deterministic. librosa is left
out of `requirements.txt` entirely rather than carried unused; the comment there
records why. Same for `datasets`, which D001 made unusable.

**D005 | env template filename | Commit the key template as `env.example` rather
than `.env.example`. | The conventional `.env.example`. | A local pre-write hook on
this machine blocks any filename matching `.env*` to prevent secrets being written
by accident. The file holds no secrets, only labelled empty slots, so the one
character change is the cheapest way through. `README.md` and the scaffold script
both point at it.

**D006 | Deepgram model names | Use `nova-3` for the general configuration and
`nova-3-medical` for the medical one. | The `nova-2` variants named in older
documentation. | Current per Deepgram's model documentation, checked 2026-08-05.
SPEC section 4 explicitly instructs checking the console for current model names
at run time and recording any substitution here.

**D007 | build order | Write and unit-test the transcription, scoring and failure
modules before any provider key exists, proving them against fixture data. | Wait
for keys and build each module the morning they arrive. | A scoring bug found
after 2,000 paid API calls costs the calls plus the rerun. Found against fixtures
it costs nothing. The provider runners are the only code that needs a live key,
and their caching and retry behaviour can be tested against a stub transport.

**D008 | drug lexicon provenance | Take generic names and active ingredients
from openFDA unconditionally, but keep a single-word brand name only if it is
not in the system English wordlist. | Take generic and brand names together, as
SPEC section 5 M2 reads. | The unfiltered version was measured against the 3,607
real clinical transcripts in the test split before being accepted, and its most
frequent "drug" matches were pain (91 clips), body (51), clear (37), muscle (36)
and head (26). Those are genuine NDC brand names on OTC products, and left in
they would have turned M2 into a measurement of how well each provider
transcribes the word "pain". Filtering everything through the dictionary was the
obvious alternative and is wrong in the other direction: morphine, heparin,
insulin, aspirin and codeine are all dictionary words and all drugs. Provenance
is what separates the two cases. After the change, 11.4 percent of clinical
clips carry a drug mention against 0.9 percent of general clips, which is the
domain separation the sample design assumes.

**D009 | lexicon source scope | Query openFDA with
`search=product_type:"HUMAN PRESCRIPTION DRUG"`. | Read the directory
unfiltered. | The public tier stops answering past 25,000 records, so the
question is what those 25,000 are spent on. Unfiltered, most of them are OTC
cosmetics. Filtered, the same budget returns 2,911 generic terms that are
prescription actives. SPEC section 9 limitation 3 already states coverage is
partial; this makes the partial coverage the useful part.

**D010 | combination splitting | Split NDC name strings on comma, semicolon,
"and" and plus, but not on slash. | Split on slash as well, which the first
version did. | In this directory slash joins a product to its dosage form rather
than separating two actives. "neomycin sulfate, polymyxin b sulfate and
dexamethasone suspension/ drops" is one product, and splitting on the slash put
the word "drops" into the lexicon, where it matched 5 clinical clips as a drug.
Changes M2's denominator, so it is recorded here.

**D011 | anatomy and lab-value blocklist | Drop cholesterol, thyroid, posterior,
pituitary, creatinine, hemoglobin and similar organ and lab terms even though
each is a real NDC generic name. | Keep them, since openFDA calls them drugs. |
They arrive through homeopathic and organ-derived preparations: Cholesterinum is
sold as generic name "CHOLESTEROL", and "SUS SCROFA PITUITARY GLAND, POSTERIOR"
leaves "posterior" behind after splitting. In clinical dictation these words
name a body part or a lab result far more often than a prescription. The
lexicon leans to precision for the reason stated in the module docstring: a
missed drug costs one observation, a false term costs every clip that says the
word.

**D012 | clip identity | Use the `audio_ids` column as `clip_id`. | Use the
basename of `audio_paths`, which the first version did. | The basename is not
unique. 46 filenames in the test split appear in two different session
directories: the same prompt read by two different speakers, stored under the
same name, with different durations and an identical transcript. Keyed on the
basename, the manifest carried duplicate clip_ids, extraction would have written
one clip over the other, and the surviving row would have paired one speaker's
audio with a transcript verified against another's. `audio_paths` and
`audio_ids` are both unique across all 6,319 rows, so either works as identity;
`audio_ids` is used because it is already a single token and needs no parsing.
`path` is kept alongside it, because locating the file inside the tarball needs
the full path. Caught by the manifest's own duplicate-clip_id check, which is
the same failure signature the overnight run's integrity check 4 looks for.

**D013 | entity alignment window | Look for a reference entity in the
hypothesis within 5 tokens of its proportionally aligned position, and treat a
drug found anywhere in the clip as correct while requiring a substitution
candidate to fall inside the window. | Search the whole hypothesis for
everything, or use absolute token positions. | SPEC M4 names a 5-token window
for negation and M2 says a substitution is a different lexicon term "in its
aligned vicinity" without defining it, so one definition is set here and used
for both. Proportional rather than absolute alignment matters because a
hypothesis that dropped three words early on would otherwise push every later
entity out of its window and turn ordinary deletions into false substitutions.
The asymmetry is deliberate: a drug transcribed correctly but in the wrong place
is still transcribed correctly, while a different drug appearing far away in a
long clip is not evidence that this mention was swapped. Applied identically to
all five configurations.

**D016 | Whisper host | Run Whisper through Groq's OpenAI-compatible endpoint on
`whisper-large-v3`, and drop the OpenAI configuration entirely. | Call OpenAI's
`/v1/audio/transcriptions` on `whisper-1`, as SPEC section 4 names it. | Suwaid
asked for a free replacement for the one paid slot. OpenAI has no free tier for
audio and needs a USD 5 minimum top-up; Groq serves the same model family with
no card, 2,000 requests a day and 7,200 audio seconds an hour, which covers this
run's 400 requests and 4,290 audio seconds inside a single hour. Two things this
changes about the results, and both belong in the writeup rather than being
quietly absorbed.

First, the model is not the same version. OpenAI's `whisper-1` serves Whisper
large-v2. Groq serves large-v3, which is newer and generally more accurate. So
the quality numbers describe large-v3, and any comparison against a published
OpenAI Whisper WER is not like for like.

Second, and more likely to mislead, M5 measures cost per audio hour and median
latency. Those now describe Groq's serving of Whisper, not OpenAI's. Groq is
built for fast inference and is priced well below OpenAI, so this configuration
will probably look both faster and cheaper than the same model at OpenAI. The
writeup must attribute that column to Groq and must not report it as an OpenAI
result. The quality columns are the model's; the speed and price columns are the
host's.

**D015 | speech-rate bounds | Flag a clip whose words-per-second falls outside
0.25 to 4 times this corpus's median rate, computed from the manifest at run
time. | The absolute 1.0 to 5.0 words per second named in
`prompts/00-overnight-run.md`. | Measured on the full 6,319-clip test split, the
median rate is 1.67 words per second and 12.2 percent of the split falls below
1.0, rising to 17.2 percent among clinical clips, where speakers read long drug
names carefully. An absolute floor of 1.0 therefore expects 2.46 flags in a
20-clip check whose halt threshold is 2, which makes halting a clean run close
to a coin flip. It did halt on the first run, on three clips at 0.62, 0.73 and
0.89 words per second, none of which had anything wrong with them. The
overnight prompt states the intent plainly, that the range should catch a
transcript-audio pairing bug rather than an unusually slow speaker, and the
absolute numbers do not serve that intent on this corpus. The replacement flags
1.3 percent of the split, keeps the ceiling meaningful, and is derived from the
data rather than chosen, so it cannot drift out of step again if the sample
changes. A genuinely mispaired transcript is wrong by a much larger factor than
this window allows.

**D014 | duplicate-pairing check | Split the overnight run's integrity check 4
into "expected" and "suspicious", and halt only on the second. | Halt on any
identical transcript paired with two different audio files, as
`prompts/00-overnight-run.md` states it. | Read literally, that check fires on
AfriSpeech's own design. The corpus has many speakers read the same prompt, and
this manifest already contains one such pair: "TABLET, ORAL TADALAFIL,
TADALAFIL, 5MG" read by two different speakers, in etsako and ikulu, at 4.4 and
4.0 seconds. Halting on it would have ended an unattended run on a false
positive, with hours of downloading behind it and nothing wrong. The two shapes
that are the indexing bug this check exists to find still halt: one
speaker credited with the same transcript twice, and two manifest rows resolving
to the same audio file. Both are reported in `docs/integrity_check.md` either
way, so the deviation is visible rather than assumed.
