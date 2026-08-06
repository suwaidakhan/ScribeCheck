# Prompt 03 — Transcribe

Precondition: I have confirmed the spot-listen passed. If I have not said so, stop and ask.

Implements SPEC section 4.

Tasks:
1. `src/transcribe.py` with one runner per system ID in SPEC section 4. Before coding each runner, check the provider's current docs for the current general and medical model names; record any substitutions in DECISIONS.md.
2. Cache every response to `data/cache/{provider}/{clip_id}.json` with: text, latency_ms, audio_seconds, billed or list cost. Skip cached clips on rerun. Handle rate limits with backoff. Never crash the whole run on one clip; log failures and continue.
3. Print projected cost per provider before each run (list price times total audio minutes) and honour the USD 20 cap from CLAUDE.md.
4. Run all five configurations over all 400 clips. After each provider: print completion count, failure count, actual cost, median latency.
5. Retry failed clips once. Write `results/transcription_run_summary.csv` (provider, clips_ok, clips_failed, cost_usd, median_latency_ms).
6. Commit code and the run summary. Cache stays gitignored.

Definition of done: at least 395 of 400 clips have cached transcripts for every provider, run summary written, total actual spend printed. Print these, then stop.
