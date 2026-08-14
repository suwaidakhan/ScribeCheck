# ScribeCheck

A clinical ASR safety and equity benchmark.

Word error rate is the number speech-to-text vendors publish and the number
buyers compare. This measures something else: whether the words that can hurt a
patient survive transcription. Drug names, dosage values, negations. And whether
that holds across African English accents.

The claim under test is that headline WER is the wrong acceptance metric for
clinical dictation. The benchmark either supports that with numbers or it does
not, and both outcomes are reportable.

**Status: all 2,000 transcriptions complete and scored. The labelling sheet has
been rebuilt as 150 individual errors after four defects were found by using it
on real rows, and human labelling is outstanding.** See [RESULTS.md](RESULTS.md)
for the numbers and [docs/PRD_EVAL_V2.md](docs/PRD_EVAL_V2.md) for what the
rebuild fixed and why.

## What is measured

Five system configurations across four vendors: Whisper large-v3 hosted by Groq,
Deepgram nova-3, Deepgram nova-3-medical, AssemblyAI universal-3-5-pro, and
Gemini 3.5 Flash Lite. Deepgram appears twice because the general-against-medical
delta is a pricing and product finding in itself.

The result, in one line: Whisper large-v3 and Deepgram nova-3 differ by 0.0009
on WER and 11.4 points on drug-name recall, p = 0.0004 paired across the 109
clips that contain a drug. Full table in [RESULTS.md](RESULTS.md).

Whisper runs through Groq rather than OpenAI because every configuration here
sits on a free tier, which keeps the benchmark reproducible by anyone without a
card. Two consequences, both stated again wherever the numbers appear: the model
is large-v3 where OpenAI's `whisper-1` serves large-v2, and the cost and latency
columns for that row describe Groq's serving rather than OpenAI's. The quality
columns belong to the model, the speed and price columns belong to the host.
See `docs/DECISIONS.md` D016.

400 clips, 71.5 minutes, 86 accents, drawn from the AfriSpeech-200 test split
under seed 42 and stratified into three accent tiers by how well represented
each accent is in the corpus. 80 percent clinical domain. 82.2 percent of clips
carry a drug name, a dosage or a negation.

Five metrics, defined in [SPEC.md](SPEC.md) section 5:

| | |
|---|---|
| M1 | Word error rate, per provider, tier and domain |
| M2 | Drug-name accuracy, splitting substitutions from deletions |
| M3 | Dosage accuracy, splitting value errors from unit errors |
| M4 | Negation preservation |
| M5 | Cost per audio hour and median latency, beside every quality claim |

The headline is the gap between the WER column and the entity columns, and
whether that gap widens for lower-resource accents.

The number the writeup leads with is not any of these. It is the count of
severity-1 failures per provider: errors that could change a clinical action if
nobody caught them. That classification is human work, done by hand over 100
selected failures, and no part of this repository will guess it.

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp env.example .env          # then paste four free API keys
bash scripts/install-hooks.sh  # secret-blocking pre-commit hook
```

```bash
.venv/bin/python -m src.lexicon      # drug lexicon from openFDA, no key needed
.venv/bin/python -m src.sample       # 400-clip manifest, deterministic
.venv/bin/python -m src.fetch_audio  # 4.67 GB streamed, ~70 MB kept
.venv/bin/python -m src.integrity    # automated checks, writes the spot-listen page
.venv/bin/python -m src.transcribe   # needs keys
.venv/bin/python -m src.score        # needs transcripts
.venv/bin/python -m src.failures     # needs scores
```

Every stage is resumable and skips what it already has. The manifest is
committed, so a re-run that produces a different one is a bug and shows up in
the diff. Provider responses are cached per clip and never re-requested, so a
second run costs nothing.

```bash
.venv/bin/python -m pytest tests/ -q
```

220 tests. The one worth reading is
[tests/test_pipeline_end_to_end.py](tests/test_pipeline_end_to_end.py), which
plants known errors into otherwise perfect transcripts and asserts the headline
table reports exactly those.

## Layout

```
src/          lexicon, sample, fetch_audio, integrity, transcribe, score, failures
data/         manifest.csv and the drug lexicon are committed; audio and cache are not
results/      scores, headline table, charts
taxonomy/     the 100-row failure sheet and its labeling page
docs/         DECISIONS.md, BUILD_LOG.md, integrity_check.md, spot_listen.html
```

`docs/DECISIONS.md` carries every judgment call that moves a number, with the
alternative and the reason. It is the file to read if you want to know whether
to trust the results. Four entries there describe bugs that would have produced
confident wrong numbers rather than an error, including a drug lexicon whose
most frequent match was the word "pain".

## Data and license

AfriSpeech-200, `intronhealth/afrispeech-200` on HuggingFace. 200 hours of
clinical and general domain English, 120 African accents, 2,463 speakers.
Licensed CC-BY-NC-SA-4.0. This is non-commercial use, attribution is given, and
the manifest and results inherit the same license.

> Olatunji et al., *AfriSpeech-200: Pan-African Accented Speech Dataset for
> Clinical and General Domain ASR*, arXiv:2310.00274.

No bulk audio is committed. The manifest names every clip used, so anyone can
rebuild the exact sample from the source dataset.

One consequence for anyone cloning this: `taxonomy/labeling.html` plays clips
from `data/audio/`, which is gitignored, so the audio players are silent until
`python -m src.fetch_audio` has populated it. The reference-against-hypothesis
diffs in `taxonomy/failure_taxonomy.csv` are committed and readable on their own,
and most failure types are judgeable from the text alone. Only the
accent-phonology calls need the audio.

## Limitations

Stated in full in the writeup, and worth knowing before reading any number:

1. AfriSpeech-200 has been public since 2023, so current commercial models may
   have trained on it. Measured WER is therefore a favourable bound, which
   strengthens rather than weakens any harm finding.
2. Read speech, not spontaneous clinical conversation. Real dictation is harder.
3. Drug lexicon coverage is partial and leans towards precision. Drug metrics
   are computed only over reference mentions the lexicon catches.
4. One run per clip per provider. No variance estimate across repeated calls.
5. Automated entity matching was spot-checked by hand, not exhaustively audited.

## Author

Suwaid Khan, product manager. Owned prescription review and medicine ordering
flows in a live telehealth product, which is where the question came from.
