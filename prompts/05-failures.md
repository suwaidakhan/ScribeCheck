# Prompt 05 — Failure sheet

Implements SPEC section 6.

Tasks:
1. `src/failures.py`: select 100 failure instances per the SPEC priority order, spread across providers and tiers.
2. Populate `taxonomy/failure_taxonomy.csv` using the template header. Fill every column except failure_code, severity, note. ref_excerpt and hyp_excerpt: about 15 words centred on the error, with the differing tokens marked like *this*.
3. Build `taxonomy/labeling.html`: one row per case, audio player, reference and hypothesis side by side with the diff highlighted, dropdowns for code and severity per the SPEC definitions, and an export button that downloads the completed CSV.
4. Print labeling instructions for me in 8 lines or fewer, including the code and severity definitions verbatim from SPEC section 6.
5. Commit.

Definition of done: 100 pre-filled rows, labeling.html works locally, instructions printed. Then stop. Prompts 06 and 07 wait until my completed `taxonomy/failure_taxonomy.csv` is saved.
