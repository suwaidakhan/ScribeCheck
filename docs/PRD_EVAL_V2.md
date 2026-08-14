# PRD: evaluation harness v2

Status: proposed, nothing implemented. No code has been changed.

Written after Suwaid sat down to label 100 failures and found four defects in
the first twelve rows. Every weakness below is evidenced against the real data
in this repo, with the blast radius measured rather than estimated, and options
ranked by cost.

**The one-line summary.** The measurement pipeline is sound and the transcripts
are real. The layer between the measurement and the human, meaning what gets
selected, what gets displayed and what the human is asked to record, is not
sound, and three of its defects would have put wrong numbers in the writeup.

---

## How these were found

Not by reading code and not by running tests. 228 tests pass and every defect
below survived them. They were found by a person using the tool on real rows
and asking why the screen disagreed with the data. That is the argument for the
human labelling phase existing at all, and it belongs in the writeup.

---

## W1. Drug substitutions are mostly false

**Severity: critical. This is the headline number.**

**Observed.** Row 10: `trimethoprim` was transcribed `trimethropium`, a
non-word. The scorer recorded a substitution. It reached that verdict by
finding `pyrimethamine` nearby, which is a real drug that was transcribed
perfectly, and crediting it as the replacement.

**Minimal reproduction.**

```
lexicon = {aspirin, warfarin}
reference:  patient takes aspirin and warfarin
hypothesis: patient takes aspirin and wxyzzy
returns:    1 correct, 1 substitution, 0 deletion
correct:    1 correct, 0 substitution, 1 deletion
```

`score_drugs` looks for a substitute in the aligned window and accepts any
lexicon term other than the mention itself. A different reference drug that
survived correctly satisfies that test.

**Blast radius.** 14 of 19 recorded substitutions are false, 74 percent.

| Provider | Reported | Genuine | False |
|---|---|---|---|
| whisper | 7 | 1 | 6 |
| gemini | 6 | 2 | 4 |
| dg-medical | 3 | 1 | 2 |
| dg-general | 2 | 0 | 2 |
| aai | 1 | 1 | 0 |

RESULTS.md currently leads with "Whisper substituted one real drug for a
different real drug 7 times against Deepgram's 2". The true counts are 1 and 0.
The claim does not survive.

**Options.**

1. Exclude any token that is itself a matched reference mention from the
   substitute candidates. Small change, restores the metric, requires a rerun
   of scoring only, no API calls. **Recommended.**
2. Additionally require the candidate to sit where the missing drug was rather
   than anywhere in the window, using the diff alignment instead of a
   proportional estimate. More faithful, more work.
3. Drop the substitution and deletion split, and report drug accuracy only.
   Cheapest, and throws away the distinction the project argues matters most.

---

## W2. The labeller is shown a window that often does not contain the error

**Severity: critical. It invalidates labels made against it.**

**Observed.** Row 12 looked clinically perfect: capitalisation, punctuation and
`1` against `one`. The actual error, `multivitamin` transcribed
`emotivitamin`, is at the end of the clip and off screen. `excerpt()` centres
on the first marked token, and the first difference was `The` against `the`.

**Blast radius.** 42 of 100 rows hide at least one changed word from the
labeller.

**Options.**

1. Centre the excerpt on the highest-priority entity error rather than the
   first diff, and mark that word distinctly from ordinary diffs.
   **Recommended, and cheap.**
2. Show the full transcript with the entity error scrolled into view. Removes
   truncation entirely at the cost of a denser screen.
3. Show one row per error span rather than one per clip, each centred on its
   own span. Correct in the MQM sense, and folds into W3.

---

## W3. The 100 rows are not a sample of the failures

**Severity: critical. It silently biases every count computed from the sheet.**

**Observed.** `select_failures` fills three priority bands first, then pads with
worst-WER clips. One row per clip and provider, carrying one `auto_flag`.

**Blast radius.** Coverage of the 328 error instances the scorer found:

| Error class | Instances found | On the sheet | Coverage |
|---|---|---|---|
| DRUG-DEL | 149 | 7 | **5%** |
| DOSE-MISS | 92 | 14 | 15% |
| NEG-FLIP | 38 | 38 | 100% |
| DOSE-VAL | 22 | 22 | 100% |
| DRUG-SUB | 19 | 19 | 100% |
| DOSE-UNIT | 8 | 1 | 12% |

The largest error class in the entire benchmark, drug names destroyed outright,
is represented by 7 of its 149 instances. A statement of the form "N percent of
failures are severity 1", computed from the labelled sheet, would describe a
population that does not exist.

A further 23 error instances sit on selected rows but are not named by that
row's flag, so the labeller has no prompt to look for them.

**Options.**

1. Keep the priority ordering for what a human should see first, and **state the
   sampling scheme in RESULTS so no rate is ever computed from the sheet as
   though it were a random sample**. Zero code, restores honesty, keeps the
   current sheet usable. **Recommended as the minimum.**
2. Stratified sample within each error class, so every class contributes in
   proportion, with weights recorded for later reweighting. Correct if any rate
   is to be published.
3. One row per error span rather than per clip, with spans sampled by class.
   The MQM-shaped answer, and the largest change here.

---

## W4. The drug lexicon is United States only

**Severity: high, and it is an equity failure inside an equity benchmark.**

**Observed.** openFDA is the US National Drug Code directory. It carries United
States Adopted Names, not International Nonproprietary Names. Confirmed missing:
`paracetamol`, `chloroquine`, `quinine`, `rifampicin`, `cotrimoxazole`,
`proguanil`, `chlorproguanil`, `amodiaquine`, `sulfadoxine`, `primaquine`,
`ethambutol`, `dihydroartemisinin`, `piperaquine`.

Paracetamol is listed as acetaminophen, rifampicin as rifampin. The benchmark
measures African clinical speech against a US formulary.

**Blast radius on this sample.** 5 uncounted mentions against a denominator of
145, roughly 3 percent. Smaller than it sounds, and the design flaw is larger
than its effect here: the same lexicon on a malaria or tuberculosis corpus
would miss most of the drugs in it.

**Research findings.** DrugCentral ships INN names explicitly, is CC BY-SA 4.0,
free, and needs no registration. The WHO Model List of Essential Medicines is
CC BY 3.0 IGO and about 500 terms, PDF only. National essential medicines lists
for Nigeria, Kenya, Ghana and South Africa are free and INN-named, and South
Africa publishes as a spreadsheet. RxNorm has no first-class INN source, so it
reproduces the same failure. No authoritative INN-to-USAN crosswalk file was
found; ChEMBL and DrugCentral both carry INN and USAN as separate fields, so one
can be derived and committed rather than fetched.

**Options.**

1. Add DrugCentral as the backbone and keep openFDA for US brand coverage.
   One download, INN-native, biggest coverage gain per unit of work.
   **Recommended.**
2. Add the WHO EML on top, about 500 terms, hand-extracted once and committed.
   Cheap, authoritative, and directly on point for the corpus.
3. Add the four national lists. Most faithful to what AfriSpeech speakers were
   actually reading, and the most extraction work.

A precision caveat travels with all of these. Broad drug databases fire on
common words: iron, blood, glucose, calcium, water are all real ingredient
names. The existing provenance filter and blocklist must be re-tuned against
any new source, and the tuning re-measured against the real transcripts the way
D008 was.

---

## W5. One code per row cannot describe a row with several errors

**Severity: medium.**

**Observed.** 8 rows carry more than one error instance and 5 carry more than
one error type. One row carries 7.

**Research findings.** MQM, the reference framework for human evaluation in
machine translation and the basis of the WMT metrics task, annotates zero to
five error spans per segment, each with its own category and its own severity.
Label Studio, Prodigy and Argilla all implement span-level multi-label natively.
The pattern is off the shelf, not bespoke.

**Options.**

1. Allow a second code per row, unranked. Smallest change that stops forcing a
   false choice.
2. One row per error span, each with its own code and severity. The MQM answer,
   and it composes with W2 and W3 rather than conflicting.
   **Recommended if W3 option 3 is taken, otherwise option 1.**

---

## W6. There is no way to record that nothing is wrong

**Severity: medium, and it corrupts the denominator.**

**Observed.** 12 of 100 rows have no drug, dose or negation error at all. They
are worst-WER padding. `BENIGN` means "error with no clinical meaning change",
which is not the same as "there is no error here", and the difference matters
when counting.

**Options.**

1. Add `NO-ERROR` to the code list, distinct from `BENIGN`. Trivial.
   **Recommended.**
2. Stop padding with worst-WER rows and select only rows carrying an entity
   error. Cleaner, and reduces the sheet below 100 unless W3 changes too.

---

## W7. No reliability measure, and none is currently possible

**Severity: medium. A reviewer will ask.**

**Observed.** One annotator. Cohen's kappa, Fleiss' kappa and Krippendorff's
alpha all require two or more independent coders by definition, so no
inter-annotator figure can be computed, and none should be invented.

**Research findings.** The accepted substitute for a single-annotator study is
**intra-rater reliability**: the same person re-labels a blind subsample days
later, and exact-match agreement with the first pass is reported. It measures
consistency rather than correctness, and it is the only reliability number a
solo annotator can honestly produce.

**Options.**

1. Re-label a blind random 15 rows after the main pass and report agreement.
   Roughly 15 minutes, turns "no reliability data" into a measured figure.
   **Recommended.**
2. Seed 5 unambiguous pre-agreed cases into the sheet as a self-consistency
   check during the pass.
3. State the limitation and compute nothing. Acceptable, weaker.

---

## W8. No calibration pass before the real one

**Severity: medium.**

**Observed.** Nothing in SPEC or the prompts asks the labeller to calibrate
before labelling 100 rows. Standard practice is a small pilot batch, a review of
the disagreements, and a guideline refinement before the main pass.

**Options.**

1. Label 10 rows, stop, re-read those 10, adjust the written definitions, then
   continue and re-label the first 10 at the end. **Recommended, costs 20
   minutes.**
2. Write worked examples into the labelling guide first, drawn from rows
   already discussed, so the anchors exist before the first judgment.

---

## W9. Spoken punctuation is contaminating WER

**Severity: high. Already measured, not yet acted on.**

**Observed.** AfriSpeech speakers read prompts aloud and many voiced the
punctuation. Three independent vendors transcribe the word "comma" on the same
clip, which only happens if it was said.

**Blast radius.**

| Provider | WER | WER without spoken punctuation | Share |
|---|---|---|---|
| dg-medical | 0.3242 | 0.2935 | 9.5% |
| dg-general | 0.3368 | 0.3059 | 9.2% |
| gemini | 0.3330 | 0.3097 | 7.0% |
| whisper | 0.3377 | 0.3282 | 2.8% |
| aai | 0.1001 | 0.1005 | 0% |

AssemblyAI converts a spoken "comma" into a comma character, which the
normalizer then strips. Deepgram writes the literal word and takes an insertion
error. Same audio, same recognition, different output convention.

The whisper against dg-general WER gap moves from 0.0009 to 0.0222, so the
"near-identical WER" framing in RESULTS does not hold. Setting
`smart_format=false` on Deepgram, done deliberately to protect dosage scoring,
is the direct cause of its share.

Entity metrics are unaffected: no punctuation word is in the drug lexicon, a
unit, a number or a negation cue.

**Options.**

1. Report both WERs and make the gap between them a finding about the metric's
   fragility. **Recommended**, and it strengthens the thesis rather than
   weakening it.
2. Strip spoken punctuation words by default and report one number. Cleaner,
   and hides a real vendor difference.
3. Run Deepgram again with `smart_format=true` as a sixth configuration to
   measure the tradeoff directly instead of inferring it. Free and cached,
   about ten minutes.

---

## W10. Uncertainty has nowhere structured to go

**Severity: low, but it costs information.**

**Observed.** A labeller who is unsure has only the free-text note. There is no
structured low-confidence flag, so uncertain rows cannot be counted, filtered or
revisited, and with one annotator there is nobody to escalate to.

**Option.** Add a confidence or "unsure" flag beside `needs a listen`. Trivial,
and it makes the honest caveats in the writeup countable.

---

## W11. Drug accuracy is recall only, which rewards inventing drugs

**Severity: high, and it points the wrong way for a safety benchmark.**

**Observed.** M2 is computed over reference mentions. A provider that outputs a
drug name never spoken is not penalised anywhere. Entity-level F1, standard in
named-entity evaluation, scores both directions.

**Blast radius.** Drug names appearing in output that are absent from the
reference: gemini 7, dg-medical 4, aai 4, whisper 1, dg-general 1.

A system that hallucinates plausible drug names scores the same as one that
stays silent, and a silent system is safer. The metric is backwards on exactly
the axis the project cares about.

**Options.**

1. Report precision beside recall, and an F1. The counts above already exist.
   **Recommended.**
2. Report hallucinated drug mentions as their own headline number. Arguably the
   more alarming figure for a clinical reader.

---

## W12. Confidence intervals treat clips as independent when they are not

**Severity: medium, and it makes the intervals too narrow.**

**Observed.** 400 clips come from 247 speakers. 99 speakers contribute more than
one clip, one contributes 7, and 252 of 400 clips sit in a multi-clip speaker
group. The Wilson intervals in RESULTS treat every clip as an independent draw.

**Research findings.** Naive per-utterance bootstrap understates variance when
utterances share a speaker; the documented fix is blockwise bootstrap resampling
by speaker rather than by clip.

**Effect on the current conclusion.** The tier intervals are wider than
reported, which strengthens rather than weakens the existing "this sample cannot
answer the equity question" statement. The conclusion holds; the reasoning
behind it should be stated correctly.

**Option.** Bootstrap by speaker block and report the wider intervals.

---

## W13. No significance test on the headline gap

**Severity: medium. First thing a technical reviewer asks.**

**Observed.** The 62.8 against 74.5 drug-accuracy gap is reported as a raw
difference. The five providers are scored on the same 145 mentions, which is a
matched-pairs design, and no paired test is reported.

**Option.** McNemar's test on the paired correct and incorrect vectors already
sitting in `per_clip_scores.csv`. The gap is large and plausibly survives, but
it has not been shown.

---

## W14. Prior art exists and is close

**Severity: high for the writeup, not for the code.**

**Observed.** Afonja, Olatunji and Ogun, "Performant ASR Models for Medical
Entities in Accented Speech", Interspeech 2024, arXiv 2406.12387, evaluates
medical entity accuracy on the AfriSpeech-200 clinical subset and reports
medical WER improving 25 to 34 percent where overall WER barely moved. That is
the same corpus and close to the same finding.

Adedeji, Joshi and Doohan, "The Sound of Healthcare", arXiv 2402.07658, defines
Medical Concept WER and shows commercial systems separating far more on it than
on overall WER.

**Why it matters.** The writeup currently reads as though the WER-against-entity
gap is a novel observation. It is a replication on new providers, which is
honest and still worth publishing, but claiming novelty without citing these
would be the fastest way to lose a technically literate reader.

**Option.** Cite both, and position ScribeCheck as what it is: an independent
replication across five current commercial systems, with a harm-classification
layer and a cost and latency comparison that neither paper has.

---

## W15. The severity scale rates potential, not realised, harm

**Severity: low, and it is a framing fix rather than a defect.**

**Observed.** NCC MERP's nine categories turn on whether an error reached the
patient and what happened next. S1 to S3 are scored from a transcript with no
downstream encounter to observe, so they rate the capacity to cause harm.

**Option.** Say so in the writeup. Describing S1 as a harm rating invites a
reader who knows NCC MERP to call it a category error.

---

## What the research says the project already gets right

Recorded so the PRD is not only a list of faults.

- **Severity anchored on consequence, not on linguistic distance.** S1, S2 and
  S3 are structurally what MQM and its lighter ESA variant use, and anchoring on
  "could this change a clinical action" rather than on edit distance is the
  choice that makes the scale usable by a non-linguist.
- **Model-assisted labelling with an authoritative dictionary.** The drug
  evidence line added after R1 is the pattern Labelbox and Prodigy call
  pre-annotation, and the caveat that absence is evidence rather than proof is
  the correct epistemic framing.
- **Refusing to let a model fill `failure_code` and `severity`.** A validity
  control, and the right one.
- **Save and resume.** Table stakes on every serious platform, and present.
- **NCC MERP is correctly not used.** Its nine harm categories are anchored on
  what happened to a patient in reality. There is no chart here to check, so only
  its ordinal logic transfers, which S1 to S3 already carries.

---

## Recommended scope

**Before any more labelling.** W1, W2, W3 option 1, W6. These are the defects
that make the current sheet produce wrong numbers or ask unanswerable questions.
The first three are scoring and display fixes with no API cost.

**Before publishing any number.** W9 option 1, and rewriting the RESULTS
headline around drug accuracy, which is unaffected by W1 and W9 alike.

**Before calling the taxonomy sound.** W4 option 1, W5, W7 option 1, W8.

**Before the writeup.** W11, W13, W14, W15. W11 is the one that changes a
number; the rest change what the numbers are allowed to claim.

**Explicitly out of scope.** Rebuilding this as a Label Studio or Argilla
deployment. The single self-contained HTML page is the right shape for 100 rows
and one annotator, and adopting a platform would add operational weight for
patterns already implemented.

---

## Open questions for Suwaid

1. W3 is the fork in the road. One row per clip with the sampling scheme
   disclosed, or one row per error span with proportional sampling? The second
   is more work and is the only version that supports publishing a rate.
2. W9: report both WERs, or normalise to one? This is a product judgment about
   what a buyer should be shown, not a technical call.
3. Re-label from scratch after the fixes, or keep any labels already recorded?
   Given W2 affects 42 rows, anything labelled before the fix should probably be
   redone.
