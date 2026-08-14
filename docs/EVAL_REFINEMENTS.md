# Eval refinements

Running log of changes Suwaid made to the evaluation design after using it.

Separate from `DECISIONS.md` on purpose. That file records implementation
judgment calls made while building. This one records what changed once a human
sat down to run the eval and found the instrument wanting. Every entry follows
the same shape: what was observed, what it would have cost, what changed, and
the term for it.

This file feeds the final README and writeup. It is the evidence that the
evaluation harness was itself evaluated.

---

## R1. The taxonomy asked the annotator a question they could not answer

**Observed.** Row 3: `Quetiapine Fumarate 25 mg` transcribed as `glatropin
humira twenty five milligram`. The taxonomy asks the annotator to choose
between DRUG-SUB (one real drug became a different real drug) and DRUG-DEL
(drug dropped or corrupted into a non-word). Separating those requires knowing
whether "glatropin" and "humira" are real medicines. Suwaid is a product
manager, not a pharmacist, and asked how anyone without pharmacy training was
supposed to decide.

**Cost if unchanged.** DRUG-SUB against DRUG-DEL is not a cosmetic distinction.
A substitution is the more dangerous failure precisely because the output still
reads as a valid clinical sentence, so nothing downstream flags it. If that
split had been guessed across 100 rows, one of the two headline classifications
would have carried annotator noise rather than signal, and the finding it
supports is the one the whole project exists to make.

**Root cause.** Not a taxonomy flaw. A **task design** flaw. The label schema
mixed two different kinds of work in a single dropdown: a **factual lookup**
with a verifiable right answer ("is humira a drug?") and a **judgment** that
depends on clinical reasoning ("would this change what a clinician does?"). The
pipeline already held the answer to the first, in the 4,865-term openFDA
lexicon it uses to score M2, and never showed it. The code knew and did not say.

**Changed.** Each row now renders a drug-evidence line above the dropdowns:
which drugs the reference contained, which of them survived, and whether a
different real drug appeared in what was heard. Absence from the directory is
labelled as evidence rather than proof, because the lexicon is precision-leaning
and partial by construction (`D009`).

**Deliberately not changed.** The evidence line suggests no code and no
severity. Both dropdowns stay empty. The point was to remove an unanswerable
question from the annotator's plate, not to answer the questions that are
properly theirs.

**Terminology.** *Annotator qualification*: the gap between the expertise a
labelling task assumes and the expertise the labeller brings. The
standard fixes are to hire the expertise, train it, or remove the need for it.
This took the third. Also *automation boundary placement*: deciding which
sub-tasks a model does and which a human does, drawn along the line between
verifiable fact and contestable judgment rather than along the line of what is
technically automatable.

---

## R2. The annotation tool lost work on close

**Observed.** After being shown the labelling page, Suwaid asked what happens if
he labels ten rows, closes the tab, and comes back. Nothing happened: state
lived in a JavaScript object and reached disk only on Export.

**Cost if unchanged.** The task is 100 rows over 3 to 4 hours. Nobody completes
that in one sitting. The first accidental close discards the session, and the
realistic outcome is that the labelling never gets finished, which blocks the
severity-1 count the writeup leads with.

**Changed.** Autosave to `localStorage` on every keystroke, restore on open with
a visible count and timestamp, a jump to the next unlabelled row, and CSV import
to move between machines. Keyed on `clip_id|provider` rather than row number, so
labels survive the sheet being regenerated. A storage failure is announced in
the header instead of losing work quietly.

**Terminology.** *Annotation tooling as a first-class deliverable*. The quality
of a labelled dataset is bounded by the ergonomics of the tool that produced it,
and a tool that punishes interruption produces either no labels or rushed ones.

---

## R3. A tier claim the sample could not support

**Observed.** The tier breakdown showed Tier A, the best-represented accents,
scoring worst on drug accuracy for several providers, which inverts the equity
hypothesis. It was flagged as something to check before the writeup leaned on it.
Suwaid pushed back on being handed the check rather than the answer.

**Cost if unchanged.** An accent-equity claim resting on 44, 40 and 61 drug
mentions per tier. One error moves a tier by roughly two points. Publishing that
as a finding in a hiring artifact is the kind of error a reviewer catches.

**Changed.** Computed Wilson intervals. All three tier intervals overlap for
every provider, and two of five providers are non-monotonic across tiers. Domain
mix is identical at 80/20 per tier, so composition is not the confound. RESULTS
now carries a "what this sample cannot answer" section stating that the equity
question needs a drug-enriched sample, which is a different draw rather than a
different analysis of this one.

**Terminology.** *Scoping a claim to its statistical power*, and knowing which
questions a sampling design was and was not built to answer. The sample was
drawn for 400 clips against a clip-level entity quota, not for drug mentions per
tier, so the entity-by-tier cell sizes were never going to carry a claim.

---

## R4. The results page led with a disclaimer

**Observed.** RESULTS.md opened by saying the labelling was unfinished and that
nothing should be read as a final finding. Suwaid noted hiring managers read
this page.

**Cost if unchanged.** A complete, verified measurement was framed as
provisional. Honest, and wrongly weighted: the accuracy comparison is finished
and defensible, while the harm ranking is a further layer.

**Changed.** Opens with the finding, then separates what is settled from what is
next, in a section that says so plainly. Same facts, accurate emphasis.

**Terminology.** *Separating measurement completeness from interpretation
completeness.* Accuracy is measured; harm is not yet classified. Conflating the
two understated the work.

---

## Pending

- **Labelling guide.** The code, severity and note definitions, when to use
  each, and the worked examples from rows 1 to 4, written for the project page
  so a reader can see how the classifications were applied rather than only
  the counts. Drafted in conversation, not yet in the repo.

---

## R5. Four defects the test suite could not see

**Observed.** Suwaid labelled twelve rows and found four faults. All 228 tests
passed throughout, because every test checked the code that builds the sheet and
none checked the sheet.

**What each was.** A drug destroyed into a non-word was blamed on a different
drug nearby that had been transcribed perfectly, so 14 of 19 substitutions were
false and the headline read 7 against 2 when the truth was 1 against 0. The
excerpt centred on the first textual difference, usually capitalisation, so 15
of 100 rows hid the clinical entity being judged, one of them a dose doubling
from 200mg to 400mg. The sheet took one row per clip filled by priority band, so
the largest error class reached it at 5 percent while three classes reached 100,
and no rate computed from it would have described anything real. And there was
no way to record that nothing was wrong, which 12 rows needed.

**Changed.** Findings became the primitive: one record per error, naming what
was expected, what was heard, and where it sits. The sheet is one row per
finding, drawn by stratified sampling with inclusion weights so summed weights
recover the population. Each row centres on its own entity and marks it
distinctly from ordinary diffs.

**Caught while verifying in the browser rather than in a test.** Labelling a
DOSE-MISS row silently did nothing: a select rejects a value that is not one of
its options, and the taxonomy had no DOSE-MISS code although the detector emits
92 of them. The progress counter sat one behind and that was the only visible
symptom. There is now a test asserting every kind the detector emits is a
selectable code.

**Terminology.** *Instrument validation*: the measuring device gets tested
before the measurements it produces are trusted. The general lesson is narrower
and more useful than "write more tests": these tests all verified the producer,
not the artifact, and the artifact is what a human uses. Checking the emitted
page, the emitted sheet and the emitted numbers is a different activity from
unit-testing the functions that emit them.
