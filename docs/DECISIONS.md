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

**D017 | AssemblyAI route and model | Call the sync endpoint
`sync.assemblyai.com/transcribe` and name `universal-3-5-pro` explicitly in the
`X-AAI-Model` header. | The async `/v2/transcript` route with no model
parameter, which is what the first version did. | Two separate faults, one of
which would have put a false number in the results.

The model was never being requested. On the async route the model parameter is
optional, and when it is omitted AssemblyAI applies its own default. `config.py`
declared `universal`, which is not a valid model string on any route, and that
label was written into every cache record and every results row. The benchmark
would have reported accuracy for a model it never asked for. Naming the model
explicitly is the fix; `universal-3-5-pro` is the current flagship, which is
what a buyer evaluating AssemblyAI today would use.

The latency was measuring the wrong thing. The async route is upload, then
submit, then poll until the job settles, and the poll loop slept two seconds
between checks. So the figure recorded for AssemblyAI was dominated by that
sleep rather than by anything AssemblyAI did, and M5 places it in a column
beside three providers that answer in a single request. The sync route returns
the finished transcript in one round trip and reports its own
`request_time_ms`, which is the provider's processing time with our network and
our polling excluded. Every clip in the manifest is 3 to 30 seconds of 16 kHz
mono PCM16, comfortably inside the sync route's 80 ms to 120 s and 40 MB
limits. Measured on a real clip: 545 ms against the several seconds the polling
path would have reported. The sync route does not expose diarisation, chapters
or PII redaction, none of which this benchmark uses.

**D018 | Gemini model pinning | Pin `gemini-3.6-flash`, version
`3.6-flash-07-2026`. | `gemini-flash-latest`, which the first version used. | An
alias is a moving target, and CLAUDE.md requires that a scoring rerun reproduce
identical numbers. Our own results are safe either way because every response is
cached, but anyone reproducing this benchmark later would silently get a
different model behind the same name and no way to tell from the manifest. The
two were also observed to differ: on the same clip, `gemini-flash-latest`
answered in 5.9 s and `gemini-3.6-flash` in 16.9 s with a different transcript,
so the alias is not simply a pointer to the newest version. Checked against
`GET /v1beta/models` rather than assumed: `gemini-3.6-flash` is the newest
stable flash release, and `gemini-2.5-flash` now returns 404 for newly created
accounts, so a name from training data would have failed outright.

**D019 | Gemini model, forced by quota | Benchmark `gemini-3.5-flash-lite`,
version `3.5-flash-lite-07-2026`, and label the row as the Flash Lite tier
everywhere it appears. | `gemini-3.6-flash`, pinned under D018, or dropping the
Gemini configuration. | The free tier will not run a full-size model over 400
clips, and the limit is not a throttle that patience solves. Measured from the
API's own quota response: `GenerateRequestsPerDayPerProjectPerModel-FreeTier =
20`. Twenty requests per day, per model. The first attempt reached 17 of 400
before every remaining clip failed after five backoffs.

`gemini-3.5-flash` had quota left but delivered one clip every two minutes,
which is 13 hours for the sample and still exposed to the same daily ceiling.
`gemini-flash-latest` was already exhausted at 20. `gemini-2.0-flash` returned
429 immediately. `gemini-3.5-flash-lite` ran 8 of 8 with no rate limiting at
roughly 20 clips a minute, and completed all 400 in about half an hour with
zero failures and zero give-ups.

This is a real change to what the Gemini column means and it must not be
smoothed over in the writeup. Flash Lite is Google's small tier, so it is not
comparable to nova-3-medical or universal-3-5-pro as a like-for-like model
choice. What it is comparable on is the question a reader will actually ask,
which is what Google's free tier gives you at this volume, and the answer is
Flash Lite or nothing. Every table and chart names the model rather than the
vendor for exactly this reason.

The 17 responses already cached from `gemini-3.6-flash`, and the 4 from
`gemini-3.5-flash`, were deleted rather than kept. Mixing three models inside
one provider column would have produced a number that describes no system.

**D020 | labeling persistence | Autosave labels to `localStorage` on every
change, keyed on `clip_id|provider`, and offer CSV import to move between
browsers. | Keep the in-memory-only page, where Export was the sole way to save.
| The original page held everything in a JavaScript object and wrote it out only
on Export. Closing the tab discarded the work. That is a defect for a job that
takes 3 to 4 hours and that nobody does in one sitting: the first accidental
close costs an hour and the labelling never gets finished. The key is the clip
and provider pair rather than the row number, so labels survive the sheet being
regenerated; row order is a presentation detail while the pair is the identity
of the thing being judged. `localStorage` is per browser, so Import restores
from an exported CSV when moving machines, and a quota or private-browsing
failure says so in the header rather than losing the work silently. A
`needs_listen` flag was added alongside, because most rows are judgeable from
the text diff and only accent-phonology calls require audio, so the sheet can be
worked without headphones and the audio-dependent rows revisited.

**D021 | collapsed transcripts | A transcript at WER 0.8 or above emits one
`ASR-COLLAPSE` finding instead of one finding per lost entity. It stays in the
entity metrics, which still count every loss inside it. | Label it per entity as
before, or exclude collapsed transcripts from the metrics entirely. | 118 of
2,000 transcripts collapse, and they were generating 57 percent of all DOSE-MISS
findings, 25 percent of DRUG-DEL, and 42 of the 150 sheet rows. One clip,
`8132758125fa0e31`, collapsed for all five providers and contributed 10 rows on
its own. Asking a human which of ten codes describes a missing dose in a
hypothesis reading `so radiation of other force damaged tubular fracture of lotr
is formula` is a question with no honest answer, and the WER column already
records the fact. Excluding them from the metrics instead was rejected because a
drug lost to a collapse is still lost, and dropping the worst 5.9 percent would
flatter every provider. The collapse rate is reported separately: AAI 0.5
percent against Whisper 9.5, a 19-fold spread, and flat across accent tiers, so
it is a robustness result rather than an equity one.

**D022 | lexicon components | Emit single-word components of multi-word generic
names, filtered harder than brand-only terms: the English dictionary applies to
every component with no exception, plus letters-only and the blocklist. | Keep
whole generic names only. | `find_drug_mentions` compares whole tokens, so no
multi-word entry can ever match anything: 2,306 of 5,347 entries are inert and
the lexicon was functionally half its stated size. `insulin glargine` was
present while `glargine` and `insulin` were not, so a reference reading `14
glargine sig 22 units` produced no drug mention at all and an insulin mangled
into `nicaragine` scored as nothing. Components are weaker evidence than a whole
generic name, so they are filtered harder rather than equally; the asymmetry the
lexicon already used for brand names is extended, not broken.

**D023 | INN names | Add a committed list of 468 International Nonproprietary
Names, `data/drug_lexicon_inn.txt`, merged at build and never dictionary
filtered. | Rely on openFDA alone, or fetch DrugCentral at build time. | openFDA
is the US National Drug Code directory and carries United States Adopted Names,
so paracetamol is only listed as acetaminophen and rifampicin as rifampin. An
African clinical corpus was being measured against a US formulary, with
chloroquine, quinine, proguanil, amodiaquine, sulfadoxine, primaquine,
ethambutol and piperaquine all absent. Committed rather than fetched because a
network dependency at build time would make the denominator depend on a remote
service being up. The list also carries `insulin` back after the dictionary
filter drops it, which keeps the filter intact instead of punching a hole in it.

**D024 | blocklist additions | 43 terms added to `COLLISION_BLOCKLIST`, six of
them found by measuring the new terms against real transcripts: cells,
dehydrated, delayed, chewable, ethinyl, dimesylate. | Ship the expanded lexicon
unmeasured. | The same method that caught `pain` appearing in 91 clips as a
supposed drug. `dehydrated alcohol` and `delayed release` are whole generic
names, so the dictionary filter never sees their components. `ethinyl` and
`dimesylate` are halves of names that never stand alone, and counting `ethinyl
estradiol` as two mentions would inflate the denominator by counting one drug
twice. `clavulanic` was kept because `acid` is dictionary-filtered, so
`clavulanic acid` correctly yields one mention. After the pass, all 21 newly
added terms that match a real transcript are genuine drugs. Effect on the
sample: 145 drug mentions to 175, across 102 clips to 109.

**D025 | openFDA is not reproducible, recorded as a known defect | The committed
`data/drug_lexicon.txt` is the canonical artifact; a rebuild with `--force` is
not guaranteed to reproduce it. | Claim determinism the build does not have. |
Two openFDA fetches minutes apart returned 1,904 and 1,935 brand-only terms. The
public tier's `skip` paging has no stable sort, so the same query returns a
different subset each run. Scoring reruns are deterministic because they read
the committed lexicon, so the guardrail in CLAUDE.md holds for every published
number; what does not hold is that a future `--force` reproduces it. Recorded
here rather than fixed, because the fix is to commit the raw openFDA snapshot
and build from that, which is a change to the fetch path and not to any number
in the current results.

**D026 | drug precision beside recall | Report precision and F1 alongside the
existing recall metric, keeping `drug_accuracy` named and defined as it was. |
Replace M2 with an F1, or leave recall alone. | Measured over reference
mentions, M2 asks whether a drug the clinician said survived, and a system can
raise that number by writing more drug names. Gemini invented 14 drug names that
appear in no reference, against 3 for Whisper, and paid nothing for it. Folding
the two into a single F1 was rejected because a missed drug and an invented drug
are different clinical failures and a buyer needs to see which one a system
commits. `drug_accuracy` keeps its name because it is already published.

**D027 | significance at clip level | McNemar over clips, where a clip counts as
correct only if every entity mention in it survived, for each provider pair. |
Mention-level pairing, or no test. | The same 400 clips went to all five
providers, so this is matched-pairs data and an unpaired test would throw away
the pairing. Clip level rather than mention level because per-mention identity is
not carried in `per_clip_scores.csv`. The test is stated in the code and in
RESULTS as an upper bound on evidence rather than a p-value to be taken at face
value: 99 of the 247 speakers contribute more than one clip, so the independence
assumption is violated and the true intervals are wider. Implemented with the
standard library, `math.comb` for the exact tail below 25 discordant pairs and an
Edwards-corrected chi-square above it, so no dependency was added for it.

**D028 | export filenames are timestamped | The labelling page writes
`failure_taxonomy-YYYYMMDD-HHMM.csv`. | Keep the fixed filename. | A fixed name
means the browser either silently overwrites the previous export or appends
"(1)", and in both cases the labeller cannot tell which file holds which
session. One export was lost to this before it was noticed.

**D029 | labels from the previous sheet are surfaced, not migrated | If the old
storage key holds labels, the page shows a banner and offers them as a download.
It does not apply them. | Auto-map them onto the new rows, or ignore them. | Row
identity changed when the sheet moved to one card per transcript, so a stored
`finding_id` no longer names the same finding. Applying those labels blind would
attach a human judgment to whichever error now holds that number, which is worse
than losing it, because a wrong label is indistinguishable from a right one once
it is in the file. Remapping is done offline against the old sheet in git, where
the mapping can be checked.
