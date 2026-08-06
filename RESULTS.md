# Results

2,000 transcriptions: 400 clips through five ASR configurations, zero failures,
USD 1.35 spent entirely against provider signup credit. Generated 2026-08-06
from `data/manifest.csv` under seed 42. Every number below is reproducible from
`results/headline.csv`.

**The failure labelling is not finished.** The taxonomy sheet is built and the
100 rows are selected, but `failure_code`, `severity` and `note` are empty until
a human fills them. The severity-1 count, which is the number this project is
actually for, does not exist yet. Nothing here should be read as a final
finding.

## Headline

| Configuration | WER | Drug accuracy | Drug subs | Dose value | Negation | Cost/hr | Median latency |
|---|---|---|---|---|---|---|---|
| AssemblyAI universal-3-5-pro | **0.100** | **91.0%** | 1 | 92.5% | 98.3% | $0.21 | 518 ms |
| Deepgram nova-3-medical | 0.324 | 83.4% | 3 | 82.3% | 96.5% | $0.46 | 876 ms |
| Gemini 3.5 Flash Lite | 0.333 | 72.4% | 6 | 82.3% | 94.8% | $0.00 | 4112 ms |
| Deepgram nova-3 | 0.337 | 74.5% | 2 | 85.0% | 95.9% | $0.46 | 752 ms |
| Whisper large-v3 (Groq) | 0.338 | 62.8% | **7** | 80.3% | 92.4% | $0.00 | 952 ms |

Drug accuracy is measured over 145 reference drug mentions, dosage over 147
pairs, negation over 172 cues.

## What the numbers say

**Whisper large-v3 and Deepgram nova-3 differ by 0.0009 on WER and 11.7 points
on drug-name accuracy.** On the metric vendors publish, those two systems are
indistinguishable. On the words that can change a prescription, one of them gets
it wrong half again as often, with 7 drug substitutions against 2. A substituted
drug is the dangerous class, because the output reads as a complete, plausible
sentence and nothing downstream looks wrong.

Gemini and Deepgram nova-3 also swap places between the two columns: Gemini
ranks 3rd on WER and 4th on drugs.

WER is not useless. AssemblyAI leads on both, by a wide margin on each. The
claim is narrower and survives the counterexample: WER alone does not tell you
which systems are safe to put in front of a prescription, and two systems with
the same WER can differ sharply on the words that matter.

**The medical model earns its price on the axis it should.** nova-3-medical
against nova-3 is +9.0 points of drug accuracy for a 0.013 WER improvement. The
gain is concentrated exactly where a clinical buyer would want it.

## What this sample cannot answer

The accent-equity question. Drug accuracy per tier rests on 44, 40 and 61
mentions, so one error moves a tier by roughly two points, every provider's
three Wilson intervals overlap, and two of five providers are non-monotonic
across tiers. Domain mix is identical at 80/20 in every tier, so composition is
not the confound; the sample was drawn for 400 clips, not for drug mentions per
tier. WER by tier has n=400 and is trustworthy, and shows no meaningful tier
effect either.

Answering the equity question properly needs a drug-enriched sample, which is a
different draw, not a different analysis of this one.

## Configurations

| | Model | Host | Notes |
|---|---|---|---|
| whisper | `whisper-large-v3` | Groq | OpenAI's model, Groq's serving. Cost and latency are Groq's. OpenAI's `whisper-1` is large-v2, so this is not comparable to a published OpenAI WER. |
| dg-general | `nova-3` | Deepgram | `smart_format=false`, so numbers and units are not rewritten before scoring |
| dg-medical | `nova-3-medical` | Deepgram | reported as `medical-nova-3` version `2026-05-18.18466` |
| aai | `universal-3-5-pro` | AssemblyAI | sync route, so latency is the provider's own `request_time_ms` |
| gemini | `gemini-3.5-flash-lite` | Google | Flash Lite, not Flash. Full-size Gemini free tier is capped at 20 requests per day, per model, which will not run 400 clips. |

Two of those are load-bearing caveats rather than footnotes, and both are in
`docs/DECISIONS.md`: the Whisper row is Groq's serving of a newer model than
OpenAI's API sells (`D016`), and the Gemini row is Google's small tier because
the free tier permits nothing else at this volume (`D019`).

## Reproducing

```bash
.venv/bin/python -m src.score
```

Reads the cached provider responses and rewrites every file in `results/`. The
manifest is committed and deterministic under seed 42, so a rerun that produces
different numbers is a bug and shows up in the diff.

The response cache is not committed, so reproducing from scratch means
re-running `src.transcribe` with your own four keys. That costs nothing on the
free tiers; `env.example` has the signup links.

## Files

| | |
|---|---|
| `results/headline.csv` | the table above |
| `results/by_tier.csv`, `by_domain.csv`, `by_accent.csv` | breakdowns |
| `results/per_clip_scores.csv` | every clip, every provider, every metric |
| `results/transcription_run_summary.csv` | clips, cost and latency per configuration |
| `taxonomy/failure_taxonomy.csv` | the 100 selected failures, unlabelled |
| `taxonomy/labeling.html` | the labelling interface |
