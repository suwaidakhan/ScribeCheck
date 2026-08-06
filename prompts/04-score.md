# Prompt 04 — Score

Implements SPEC section 5 exactly. Where the spec defines a metric, do not improvise; where a judgment call is unavoidable, make it, apply it identically to all providers, and log it in DECISIONS.md.

Tasks:
1. `src/score.py`: apply the single normalizer, then compute M1 through M5 per SPEC.
2. Write:
   - `results/per_clip_scores.csv` (clip_id, provider, wer, drug outcomes, dose outcomes, negation outcome)
   - `results/headline.csv` (the SPEC headline table)
   - `results/by_tier.csv`, `results/by_domain.csv`, `results/by_accent.csv`
3. Charts to `results/charts/` (matplotlib, no seaborn, one chart per figure): WER by provider and tier; drug accuracy by provider and tier; the WER-versus-dosage-value-accuracy gap per provider; cost per audio hour versus WER scatter.
4. Sanity checks, printed: per-provider WER within 0 to 1; entity denominators match manifest annotations; a rerun of score.py reproduces identical numbers.
5. Print a 10-line plain-language reading of the headline table, including whether the WER-versus-entity gap widened for Tier C, per the SPEC section 1 claim.
6. Commit results and charts.

Definition of done: all CSVs and charts written, sanity checks pass, the 10-line reading printed. Then stop.
