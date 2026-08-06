"""Paths, constants and provider configuration.

One place for anything two modules would otherwise both hardcode.
"""

from __future__ import annotations

from pathlib import Path

# Repo layout. Everything else builds paths from these.
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AUDIO = DATA / "audio"
CACHE = DATA / "cache"
TARBALLS = DATA / "tarballs"
RESULTS = ROOT / "results"
CHARTS = RESULTS / "charts"
DOCS = ROOT / "docs"
TAXONOMY = ROOT / "taxonomy"

MANIFEST = DATA / "manifest.csv"
LEXICON = DATA / "drug_lexicon.txt"
LEXICON_FALLBACK = DATA / "drug_lexicon_fallback.txt"

# SPEC section 3. Every random draw in this project uses this and nothing else.
SEED = 42

# SPEC section 3 sample design.
SAMPLE_SIZE = 400
TIER_ALLOCATION = {"A": 135, "B": 135, "C": 130}
CLINICAL_SHARE = 0.80
MIN_ACCENTS_PER_TIER = 4
MAX_CLIPS_PER_ACCENT = 40
MIN_ENTITY_SHARE = 0.55
MIN_DURATION_S = 3.0
MAX_DURATION_S = 30.0
MIN_TIER_C_CLIPS_IN_SPLIT = 15

# CLAUDE.md guardrails.
MAX_DOWNLOAD_BYTES = 8 * 1024**3
SPEND_CAP_USD = 20.00

# Audio written for the providers. 16 kHz mono is what every ASR API
# downsamples to anyway, and it keeps the upload small.
TARGET_SAMPLE_RATE = 16_000

# AfriSpeech-200 on HuggingFace. Public, ungated, CC-BY-NC-SA-4.0.
HF_REPO = "intronhealth/afrispeech-200"
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"
# SPEC section 2: try test first, then dev, then train, and use the first split
# whose transcript CSV loads with non-empty transcripts.
SPLIT_PREFERENCE = ("test", "dev", "train")

DATASET_CITATION = (
    "AfriSpeech-200 (intronhealth/afrispeech-200), CC-BY-NC-SA-4.0. "
    "Olatunji et al., AfriSpeech-200: Pan-African Accented Speech Dataset for "
    "Clinical and General Domain ASR, arXiv:2310.00274."
)

# SPEC section 4. Five configurations across four vendors; Deepgram appears
# twice because the general-versus-medical delta is a finding in itself.
#
# usd_per_min is list price, checked 2026-08-05, used for the projection printed
# before any run starts. Actual cost is read back from the API response wherever
# the provider reports it. See docs/DECISIONS.md D006.
PROVIDERS: dict[str, dict[str, object]] = {
    # Whisper served by Groq rather than OpenAI. Same model family, no card,
    # no spend. Two things this changes about the results, both in D016:
    # the model is large-v3 where OpenAI's `whisper-1` is large-v2, and the
    # latency and cost-per-hour in M5 belong to Groq's serving, not OpenAI's.
    "whisper": {
        "vendor": "groq",
        "model": "whisper-large-v3",
        "env_key": "GROQ_API_KEY",
        "usd_per_min": 0.0,
        "free_tier": True,
    },
    "dg-general": {
        "vendor": "deepgram",
        "model": "nova-3",
        "env_key": "DEEPGRAM_API_KEY",
        "usd_per_min": 0.0077,
        "free_tier": True,
    },
    "dg-medical": {
        "vendor": "deepgram",
        "model": "nova-3-medical",
        "env_key": "DEEPGRAM_API_KEY",
        "usd_per_min": 0.0077,
        "free_tier": True,
    },
    "aai": {
        "vendor": "assemblyai",
        "model": "universal",
        "env_key": "ASSEMBLYAI_API_KEY",
        "usd_per_min": 0.0035,
        "free_tier": True,
    },
    "gemini": {
        "vendor": "google",
        "model": "gemini-flash-latest",
        "env_key": "GOOGLE_API_KEY",
        "usd_per_min": 0.0,
        "free_tier": True,
    },
}

# SPEC section 4: nothing else in the prompt, so nothing else steers the output.
GEMINI_PROMPT = "Transcribe this audio verbatim."
