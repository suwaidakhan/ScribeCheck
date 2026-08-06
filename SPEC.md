# SPEC.md — ScribeCheck Benchmark Specification

Version 1.0. This document defines the benchmark. Code follows this spec; the spec does not bend to the code.

## 1. Question

When commercial speech-to-text is used in a clinical dictation or intake flow, how often does it corrupt the content that can harm a patient, and does that risk change with the speaker's accent?

Three sub-questions:

1. What is overall word error rate per provider on clinical-domain speech?
2. What is accuracy on safety-relevant entities: drug names, dosage values, dosage units, negations?
3. How do both vary across accent tiers, and does the gap between headline WER and entity accuracy widen for lower-resource accents?

The product claim under test: headline WER is the wrong acceptance metric for clinical dictation. The benchmark either supports that with numbers or fails to, and both outcomes are reportable.

## 2. Dataset

AfriSpeech-200 (`intronhealth/afrispeech-200`, Hugging Face). Verified fields per clip: `speaker_id`, `path`, `audio` (44.1 kHz), `transcript`, `age_group`, `gender`, `accent`, `domain` (clinical or general), `country`, `duration`. 120 accent configs plus `all`. Splits: train, dev, test, split by speaker with no speaker crossing partitions. Test split holds 3,623 clinical and 2,723 general clips.

Split preference for sampling: test, then dev, then train, using the first split whose transcript CSV loads with non-empty transcripts. Record the split used in the manifest. Rationale: test transcripts were withheld during the 2023 challenge and released after; verify at runtime rather than assume.

License: CC-BY-NC-SA-4.0. Non-commercial use, attribution, share-alike on derived artifacts. The manifest and results inherit this license.

## 3. Sample design

**N = 400 clips**, seed 42, drawn as follows.

**Accent tiers**, computed from `accents.json` clip counts at runtime (top of the distribution for reference: yoruba 15,378; igbo 8,654; swahili 6,314; hausa 5,749; ijaw 2,485):

- Tier A (high representation): the top 5 accents by total clip count.
- Tier B (mid): accents ranked 6 through 25.
- Tier C (low): accents ranked 26 and below that have at least 15 clips in the chosen split.

**Allocation:** approximately 135 clips per tier (135 / 135 / 130). Within each tier: 80% clinical domain, 20% general domain. Spread across at least 4 accents per tier and cap any single accent at 40 clips so no accent dominates its tier.

**Entity oversampling:** at least 55% of the final 400 must contain at least one safety-relevant entity in the reference transcript (a drug lexicon hit, or a number adjacent to a dosage unit, or a negation cue). Stratify first, then within each stratum prefer entity-bearing clips until the quota is met, filling the remainder randomly.

**Duration filter:** clips between 3 and 30 seconds.

**Manifest** (`data/manifest.csv`, committed): clip_id (path), split, accent, tier, domain, duration, transcript, has_drug, drug_terms, has_dose, dose_strings, has_negation, gender, age_group, country.

**Audio fetch:** only for manifest clips, via per-accent streaming configs, saved as 16 kHz mono WAV in `data/audio/`.

**Human validation gate:** export 20 random manifest clips to `docs/spot_listen.html` (audio player beside reference transcript). Suwaid listens and confirms transcripts match audio before prompt 03 runs. If more than 1 of 20 is a mismatch, stop and reassess.

## 4. Systems under test

| ID | System | Note |
|---|---|---|
| whisper | OpenAI Whisper API (`whisper-1`) | Comparability with published AfriSpeech baselines |
| dg-general | Deepgram, current general Nova model | Check the console for the current model name at run time |
| dg-medical | Deepgram, current medical Nova model | The general-vs-medical delta is a pricing and product finding in itself |
| aai | AssemblyAI, current default speech model | |
| gemini | Gemini Flash (current version) audio transcription | Prompt: "Transcribe this audio verbatim." Nothing else |

If a listed variant no longer exists, substitute the provider's closest current equivalent and record the substitution in `docs/DECISIONS.md`. Five configurations, 400 clips, 2,000 transcriptions, all cached.

Log per call: latency (wall clock), audio seconds, billed cost where the API reports it, otherwise list price times duration.

## 5. Metrics

**Normalization (applies to reference and hypothesis identically):** the Whisper English text normalizer (`whisper-normalizer` package): lowercase, punctuation removal, number-word to digit conversion, standard English contractions. One normalizer for everything; note in DECISIONS.md that digit conversion is what allows dosage matching between "five hundred milligrams" and "500 mg".

**M1. WER.** `jiwer` on normalized text. Report per provider overall, per provider by tier, per provider by domain.

**M2. Drug-name accuracy.** Lexicon built in prompt 02 from the openFDA NDC endpoint (generic and brand names, deduplicated, lowercase, length 4 or more, minus an English-word collision blocklist such as "sodium" alone). Fallback if openFDA is unreachable: a 300-name common-drug list generated and committed as `data/drug_lexicon_fallback.txt`. For each reference drug mention:
- Correct: same term present in the hypothesis (allow edit distance 1 for pluralization or minor spelling).
- Substitution: a different lexicon term appears in its aligned vicinity. The most dangerous class.
- Deletion: no lexicon term appears.
Report accuracy per provider and per tier, and the substitution count separately.

**M3. Dosage accuracy.** Extract number-plus-unit pairs from normalized reference (units: mg, mcg, g, kg, ml, l, cc, iu, units, mmol, meq, percent, tablets, capsules, drops, puffs, mg/dl, ml/hr, hours, days, times daily; treat mcg and µg as equal, cc and ml as equal). A pair is correct only if value and unit both survive in the hypothesis. Report separately: value errors (the dangerous class) versus unit errors.

**M4. Negation preservation.** For references containing a negation cue (no, not, denies, denied, without, negative for, never), check the cue survives within a 5-token window of its aligned context. Report flip-or-drop rate per provider.

**M5. Cost and latency.** Cost per audio hour and median latency per provider, presented beside quality so every quality claim has a price attached.

**Headline table:** provider rows; columns overall WER, Tier A WER, Tier C WER, drug accuracy, dosage-value accuracy, negation preservation, cost per audio hour. The gap between the WER column and the entity columns is the story.

## 6. Failure taxonomy (the human layer)

Prompt 05 selects 100 failure instances, prioritized: all drug substitutions, then all dosage value errors, then all negation flips, then worst-WER clips to fill, spread across providers and tiers. Suwaid labels each with one code and one severity in `taxonomy/failure_taxonomy.csv`.

Codes:
- DRUG-SUB: one real drug transcribed as a different real drug
- DRUG-DEL: drug name dropped or corrupted into a non-word
- DOSE-VAL: numeric value changed
- DOSE-UNIT: unit changed, value intact
- NEG-FLIP: negation lost or inverted
- TERM-CORRUPT: clinical term corrupted into a plausible-reading wrong term
- PHON-ACCENT: error traceable to accent phonology (verify by listening)
- BENIGN: error with no clinical meaning change

Severity:
- S1: could change a clinical action if unreviewed (wrong drug, wrong value, flipped negation)
- S2: misleading, likely caught by a reader
- S3: cosmetic

The writeup reports S1 counts per provider and per tier. That number, not WER, is the benchmark's headline.

## 7. Product spec output

One page in the writeup, derived from the S1 pattern, covering: which fields never autofill from ASR (drug, dose, negation-bearing findings), where confidence gating and re-prompt sits, where the human review step goes, whether accent-aware routing or a medical-model upgrade is justified by the measured delta against its cost, and the acceptance metric a team should use instead of WER.

## 8. Deliverables

1. Public GitHub repo: code, manifest, results, taxonomy, decisions log. No bulk audio.
2. Dashboard: static single-page site (designed in Google Stitch, built by Claude Code, deployed on Vercel). Headline table, tier chart, S1 severity chart, 5 annotated failure examples.
3. Writeup, about 6 pages, in `docs/writeup.md`: 1 Why (one line on Dawaai prescription-review ownership) 2 Method 3 Headline numbers 4 Where WER hides the harm 5 Taxonomy findings with examples 6 Product spec. Plus Limitations and License sections.
4. 3-minute video. Skeleton: 0:00 the question and why it matters, 0:30 what was measured and on what data, 1:00 the headline table, 1:30 two failure examples read aloud, 2:20 the product spec conclusions, 2:50 what would be measured next. Walk the findings, never the UI.

## 9. Limitations (stated in the writeup, in this order)

1. AfriSpeech-200 has been public since 2023, so current commercial models may have trained on it; measured WER is therefore a favourable bound, which strengthens rather than weakens any harm findings.
2. Read speech, not spontaneous clinical conversation; real dictation is harder.
3. Drug lexicon coverage is partial; drug metrics are computed only over reference mentions the lexicon catches.
4. One run per clip per provider; no variance estimate across repeated calls.
5. Automated entity matching was spot-checked by hand, not exhaustively audited.
