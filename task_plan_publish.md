# ExecPlan: publish ScribeCheck publicly and update the GitHub profile

Started 2026-08-06. Owner: Claude Code. Human: Suwaid Khan.

## 1. Purpose and Big Picture

Put ScribeCheck on GitHub as a public repository, and update
`suwaidakhan/suwaidakhan` so the profile reflects two AI projects rather than
one. A public push is hard to undo: a leaked key stays in history, and a stale
document is read by everyone who arrives. So the audit runs before the push,
not after.

## 2. Context and Orientation

- Repo at `/Users/suwaid/ScribeCheck`, 8 commits on `main`, no remote.
- `gh` authenticated as `essendigitalgroup-cyber`, which is the same account
  now named `suwaidakhan`.
- 57 tracked files, 1.0 MB tracked, 1.0 MB of history. Audio and cache are
  gitignored and stay local.
- Profile README lives at `suwaidakhan/suwaidakhan`. Public repos today:
  mindyourmacro, Edmonton, vezir-on-hermes, openclaw-memory. vezir stays
  private.

## 3. Plan of Work

- **Phase 2** Pre-publication audit. Secrets, PII, licence, stale docs, size.
- **Phase 3** Fix what the audit found, before any push.
- **Phase 4** Create the public repo and push.
- **Phase 5** Verify the published result as a stranger would see it.
- **Phase 6** Research the profile, then rewrite it to carry both projects.

## 4. Concrete Steps

See §5.

## 5. Progress

- [x] Phase 2 audit run
- [ ] Phase 3 fixes
- [ ] Phase 4 push
- [ ] Phase 5 verify
- [ ] Phase 6 profile

## 6. Surprises and Discoveries

**S1. Secrets are clean.** Every one of the four live keys was searched for
across every blob in every commit, not just the working tree. Zero hits. The
pre-commit hook and `.gitignore` did their job.

**S2. Personal email would go public.** `suwaidakhan@gmail.com` appears in
`MORNING_BRIEF.md` twice and in `env.example` once, as an instruction to
myself about which account to sign up with. That is an artifact of how the work
happened, not something a reader needs, and publishing an address invites
scraping. It also appears in 11 commit trailers, which is ordinary for git and
is left alone; rewriting history over it is disproportionate.

**S3. No LICENSE file.** The dataset is CC-BY-NC-SA-4.0 and the README says so,
but the repository's own code carries no licence, which means default
all-rights-reserved and nobody can reuse it. The results and manifest inherit
the dataset's share-alike non-commercial terms, so the licence has to say both
things.

**S4. MORNING_BRIEF.md is now false.** It still reads "The run stopped at phase
03", "205 tests", "Spend so far USD 0.00" and "Ran no provider. Spent nothing."
All of that was true at 04:20 and none of it is true now. It is a handover note
to a specific person on a specific morning, and it is the second file a visitor
opens. It gets replaced by an accurate status document.

## 7. Decision Log

| Decision | Reasoning | Time |
|---|---|---|
| Strip the email from published files, leave commit trailers | The files are read by strangers; the trailers are standard git attribution and rewriting 8 commits to remove one address is disproportionate | 16:05 |
| Replace MORNING_BRIEF.md with RESULTS.md | A public repo whose top document contradicts its own results destroys trust in the numbers, which is the only thing this project sells | 16:05 |
| MIT for the code, note the dataset terms separately | Code should be reusable; the manifest and results inherit CC-BY-NC-SA-4.0 from AfriSpeech-200 and cannot be relicensed | 16:05 |

## 8. Validation and Acceptance

- No key fragment in any blob in any commit, checked across full history.
- `gh repo view` shows public, README renders, CI green.
- Every top-level document's claims match `results/headline.csv`.
- Profile README names both projects and reads as one person's focus.

## 9. Idempotence and Recovery

The push is the irreversible step. Everything before it is local. If the repo
must be withdrawn, `gh repo delete` works, but anything cloned or indexed in
the interim is gone from our control, which is why the audit precedes it.

## 10. Interfaces and Dependencies

- github.com via `gh`, authenticated.
- `suwaidakhan/suwaidakhan` for the profile README.

## 11. Artifacts and Notes

Headline result for the profile copy, from `results/headline.csv`:
whisper and dg-general differ by 0.0009 WER and 11.7 points of drug-name
accuracy; 2,000 transcriptions, five configurations, USD 1.35.

## 12. Outcomes and Retrospective

To be filled at the end.
