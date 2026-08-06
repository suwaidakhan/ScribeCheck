# Prompt 01 — Scaffold

Read CLAUDE.md and SPEC.md fully before doing anything.

Tasks:
1. Create the repo layout defined in CLAUDE.md. Initialize git.
2. Write `.gitignore` covering `.env`, `data/audio/`, `data/cache/`, `__pycache__`, `.DS_Store`.
3. Create `.env.example` with placeholders: OPENAI_API_KEY, DEEPGRAM_API_KEY, ASSEMBLYAI_API_KEY, GOOGLE_API_KEY. Copy it to `.env` and tell me, in one short list, exactly where to get each key and where to paste it.
4. Create `requirements.txt`: datasets, soundfile, librosa, pandas, jiwer, whisper-normalizer, requests, python-dotenv, tqdm. Set up a virtual environment and install. Pin versions after install.
5. Create empty `docs/BUILD_LOG.md` and `docs/DECISIONS.md`.
6. Smoke test: a script that (a) loads the AfriSpeech-200 transcript CSV for the test split directly by URL (see SPEC section 2 for split preference and the fallback order), prints row count and columns, and (b) confirms each API key in `.env` authenticates with a minimal call. Print a pass/fail line per check. Do not transcribe anything yet.
7. First commit.

Definition of done: repo committed, dependencies installed, transcript CSV loads with non-empty transcripts from the chosen split, four API auth checks pass. Print all of this explicitly, then stop and wait.
