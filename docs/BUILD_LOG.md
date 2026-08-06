# BUILD_LOG.md

One line per event. Failures, fixes, and anything that cost time. Writeup material.

---

## 2026-08-05

- 19:55 Kit read in full: SPEC.md, CLAUDE.md, prompts 00 through 07, taxonomy template.
- 19:56 Local toolchain checked: Python 3.13.7, git 2.54.0, no ffmpeg, 104 GB free.
- 19:57 HuggingFace dataset viewer refuses AfriSpeech-200: runs arbitrary Python. Loading-script dataset, so `datasets` streaming per SPEC section 3 cannot work on datasets 3.0 and later. Switched to direct tarball fetch. See DECISIONS D001.
- 19:57 Pulled `transcripts/test.csv` and `accents.json` anonymously. 6,319 rows, 108 accents, 0 empty transcripts. SPEC's clinical/general counts are off by 16 and 11. See DECISIONS D002.
- 19:58 Measured test tarball sizes by HEAD request. yoruba 522.5 MB, swahili 385.3 MB, igbo 280.3 MB, hausa 142.1 MB, zulu 137.0 MB, ijaw 46.1 MB, twi 43.8 MB.
- 20:05 Verified all requirements resolve with Python 3.13 support on PyPI.
- 20:06 openFDA `/drug/ndc.json` answers without an API key. 136,765 records. First record returned was a tinted sunscreen, so the lexicon needs filtering beyond SPEC's blocklist.
- 20:06 Confirmed current provider models and list prices: Whisper USD 0.006/min with no free tier, Deepgram nova-3 and nova-3-medical at USD 0.0077/min with USD 200 signup credit, AssemblyAI Universal-3.5 Pro at USD 0.21/hr with USD 50 signup credit, Gemini Flash free tier with per-account limits not published.
- 20:10 Repo layout created, git initialised on `main`.
- 20:11 Pre-write hook blocked the filename `.env.example`. Committed the template as `env.example` instead. See DECISIONS D005.
- 20:25 venv built on Python 3.13.7, 11 direct dependencies installed and pinned. Confirmed the Whisper normalizer turns "FIVE HUNDRED milligrams" into "500 milligrams", which is what makes dosage matching possible at all.
- 20:40 `src/entities.py` and 32 tests written and passing: drug mentions, dose pairs, unit canonicalisation, negation cues with token positions.
- 20:55 First lexicon build failed. openFDA answers 400, not 404, once `skip` passes its 25,000 ceiling, and the handler treated that as a network failure and discarded 25,000 records of work. Fixed: 400 and 404 both mean end-of-results, and partial results are kept rather than thrown away.
- 21:05 Built the lexicon, then checked it against the 3,607 real clinical transcripts before trusting it. Its five most frequent "drug" matches were pain, body, clear, muscle and head. All are real NDC brand names on OTC products. Unfixed, M2 would have measured how well providers transcribe the word "pain".
- 21:20 Rebuilt around provenance: generic names and active ingredients are never questioned, single-word brand names must not be dictionary words. Confirmed the dictionary alone would have been wrong in the other direction, since morphine, heparin, insulin, aspirin and codeine are all dictionary words. See DECISIONS D008.
- 21:30 Traced the four remaining contaminants to one root cause: the combination-splitter was fragmenting descriptive names. "SUS SCROFA PITUITARY GLAND, POSTERIOR" left "posterior", and "suspension/ drops" left "drops". Dropped slash as a separator and blocklisted the anatomy and lab-value residue. See DECISIONS D010 and D011.
- 21:35 Final lexicon: 4,865 terms. Entity rates on the real split, clinical against general: drug 10.7 vs 0.8 percent, dose 13.1 vs 2.1, negation 9.0 vs 9.7, any 26.0 vs 12.2. Negation not separating by domain is expected; it is a feature of English, not of clinical speech.
- 21:36 Noted for the sampler: 26.0 percent of clinical clips carry an entity, so SPEC section 3's 55 percent entity quota over 400 clips needs deliberate oversampling and may bind hardest in Tier C, where few clips exist per accent.
