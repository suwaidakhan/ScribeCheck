# Results

**Two speech-to-text systems can post the same word error rate and differ by 10.6
points on whether they get the drug name right.**

Whisper large-v3 and Deepgram nova-3 landed 0.0009 apart on WER, the metric
vendors publish and buyers compare. On drug-name accuracy they landed 61.5
percent against 72.1 percent. Paired across the 110 clips that contain a drug,
Deepgram gets 18 right that Whisper misses and Whisper gets 3 that Deepgram
misses, p = 0.0015 by McNemar. A procurement decision made on published WER
would treat those two systems as interchangeable.

One honest qualification travels with that. 112 of the 400 clips have a speaker
voicing punctuation aloud, and the providers write "comma" and "open bracket"
as words. Charged for those, Whisper and Deepgram are 0.0009 apart. Not charged
for them, they are 0.0305 apart, because Deepgram writes far more of them. The
drug gap is 10.6 points either way. Both WERs are reported below rather than
one, since which of them a buyer sees decides whether these two systems look
identical.

Measured over 2,000 transcriptions: 400 clips through five commercial
configurations, zero failures, USD 1.35 spent entirely against provider signup
credit. Generated 2026-08-13 from `data/manifest.csv` under seed 42, and
reproducible from `results/headline.csv`.

## What is settled and what comes next

The measurement is complete. All five metrics are computed over every clip and
every configuration, and the comparison above is the finding.

One layer is outstanding. Ranking systems by *how badly* they fail needs a human
to classify each error, and 150 individual errors have been selected and prepared
for that, one per row, stratified by error class with sampling weights so a
population rate can be recovered from the labelled sheet. `failure_code` and `severity` are empty until a person fills them, and the
code refuses to guess: a model rating the danger of its own domain's mistakes is
the one number nobody should accept. So this page reports accuracy, not harm.
The per-provider count of errors that could change a clinical action is the next
deliverable and does not exist yet.

## Headline

| Configuration | WER | WER, punctuation words removed | Drug recall | Drug precision | Dose value | Negation | Cost/hr | Median latency |
|---|---|---|---|---|---|---|---|---|
| AssemblyAI universal-3-5-pro | **0.100** | **0.100** | **92.2%** | 97.0% | 92.5% | 98.3% | $0.21 | 518 ms |
| Deepgram nova-3-medical | 0.324 | 0.228 | 81.0% | 95.9% | 82.3% | 96.5% | $0.46 | 876 ms |
| Gemini 3.5 Flash Lite | 0.333 | 0.262 | 71.5% | **90.6%** | 82.3% | 94.8% | $0.00 | 4112 ms |
| Deepgram nova-3 | 0.337 | 0.247 | 72.1% | 97.6% | 85.0% | 95.9% | $0.46 | 752 ms |
| Whisper large-v3 (Groq) | 0.338 | 0.278 | **61.5%** | 97.8% | 80.3% | 92.4% | $0.00 | 952 ms |

Drug metrics are measured over 179 reference drug mentions, dosage over 147
pairs, negation over 172 cues.

**Recall and precision answer different questions and both are reported.**
Recall asks whether a drug the clinician said survived. Precision asks whether a
drug the system wrote was ever said. A system can raise recall by guessing more
drug names, so recall alone points a vendor in the wrong direction. Gemini
wrote 12 drug names with nothing like them in the reference, against 2 for
Whisper and 3 for Deepgram nova-3, which is why it sits last on precision while sitting fourth
on recall.

Drug substitution, one real drug written as a different real drug, no longer
separates these systems: 5, 4, 3, 3, 3 across the five. An earlier version of
this page led with a 7-against-2 split on that column. It was wrong. The scorer
credited a surviving reference drug as the replacement for a mangled one, and 14
of the 19 recorded substitutions were false. The fix and its measurement are in
`docs/PRD_EVAL_V2.md` under W1.

## What the numbers say

Drug recall spans 30.7 points across the five systems, from 61.5 to 92.2. WER
spans 0.238. The two orderings do not match: Gemini ranks 3rd on WER and 4th on
drugs, and the three systems clustered within 0.005 of each other on WER sit
10.6 points apart on drugs.

WER is not useless. AssemblyAI leads on both, by a wide margin on each. The
claim is narrower and survives that: WER alone does not tell you which systems
are safe to put in front of a prescription, and systems with the same WER can
differ sharply on the words that matter.

**The medical model earns its price on the axis it should.** nova-3-medical
against nova-3 is +8.9 points of drug recall for a 0.013 WER improvement, and
the pairing holds up: 13 clips where the medical model gets the drug and the
general one does not, against 1 the other way, p = 0.002. The gain is
concentrated exactly where a clinical buyer would want it, and it costs the same.

**Two of the gaps do not survive a test, and saying so is part of the result.**
Every pair was compared with McNemar over the clips that contain the entity,
which is matched-pairs data because all five systems saw the same 400 clips.
Deepgram nova-3 and Gemini are indistinguishable on drugs, p = 1.00, despite
looking 0.6 points apart in the table. On dosage only AssemblyAI separates from
anything, and the other four are mutually indistinguishable, p = 0.21 to 1.00.
On negation only two of the ten pairs separate. Full table in
`results/significance.csv`.

That test assumes clips are independent. They are not: the 400 clips come from
247 speakers and 99 speakers contribute more than one, so every p-value above is
optimistic and should be read as an upper bound on the evidence.

## What this sample cannot answer

The accent-equity question. Drug recall per tier rests on 52, 50 and 73
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
| `results/significance.csv` | McNemar paired tests, every provider pair, every entity |
| `taxonomy/failure_taxonomy.csv` | the 150 selected findings, unlabelled |
| `taxonomy/labeling.html` | the labelling interface |
