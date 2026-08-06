# Automated integrity check

Stands in for the blocking spot-listen in `prompts/02-sample.md`, which
needs a human and could not run unattended. The listen still happens, in
the morning, against `docs/spot_listen.html`. These checks catch the
mechanical class of failure: audio that disagrees with its metadata, a
clip with no signal, a speech rate no human produces, and a manifest
pairing one audio file with two rows. They cannot hear whether the
speaker said what the transcript claims. That part is still Suwaid's.

**Outcome: PASS**

- Clips checked: 20
- Passed: 20
- Flagged: 0 (halt threshold is more than 2)
- Suspicious pairings: 0 (any one halts the run)
- Expected repeated prompts: 1

## Flagged clips

None.

## Suspicious pairings

None.

## Expected repeated prompts

AfriSpeech has many speakers read the same prompt, so an identical
transcript on two different recordings is the corpus working as designed,
not an indexing bug. Listed for the record; none of these halt the run.

- 2 speakers read the same prompt: 0700cda752bd76a9e0094aa81371a166, 50dda38735c07990362d85bde0133f84 (TABLET, ORAL TADALAFIL, TADALAFIL, 5MG...)
