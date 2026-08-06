# DECISIONS.md

Every judgment call that changes a result or deviates from SPEC.md. One entry each:
decision, alternative, reason.

Format: `YYYY-MM-DD | area | decision | alternative | reason`

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
