# Prompt 02 — Sample and lexicon

Implements SPEC sections 2, 3, and the lexicon in section 5 (M2).

Tasks:
1. `src/lexicon.py`: build the drug lexicon from the openFDA NDC endpoint per SPEC M2, cache to `data/drug_lexicon.txt`. If openFDA is unreachable, generate the 300-name fallback list, commit it, and log the fallback in DECISIONS.md.
2. `src/sample.py`:
   a. Load transcript CSVs for the chosen split (SPEC split preference). Load `accents.json` and compute the accent tiers per SPEC section 3.
   b. Annotate every row: has_drug, drug_terms, has_dose, dose_strings, has_negation, using the lexicon and the SPEC unit and negation lists.
   c. Draw the 400-clip stratified sample per SPEC section 3, seed 42. Write `data/manifest.csv`.
   d. Print the sample sheet: clips per tier, per domain, per accent, entity coverage percentage, total audio minutes.
3. Fetch audio for manifest clips only, via per-accent streaming configs, to 16 kHz mono WAV in `data/audio/`. Show projected shard download size before starting and respect the 8 GB abort rule. Stop each accent stream as soon as its manifest clips are captured.
4. Build `docs/spot_listen.html`: 20 random manifest clips, audio player beside reference transcript, one checkbox per clip.
5. Commit manifest, lexicon, code. Log runtime issues in BUILD_LOG.md.

Definition of done: manifest.csv has 400 rows meeting every SPEC quota (print the checks), all 400 WAVs exist on disk, spot_listen.html opens locally. Then tell me to do the spot-listen and stop. Do not proceed to transcription until I confirm the spot-listen passed.
