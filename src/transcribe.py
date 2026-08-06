"""Run the manifest through all five ASR configurations, SPEC section 4.

Nothing here is called during the overnight build, because no provider key
exists yet. It is written and tested first on purpose: a caching or accounting
bug found against a stub costs nothing, and the same bug found after 2,000 paid
calls costs the calls plus the rerun. See DECISIONS D007.

The orchestrator takes its transcriber as an argument so tests can hand it a
stub. The real transcribers are at the bottom of this file, one per vendor.

Run:  python -m src.transcribe [provider_id ...]
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import statistics
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src import config


class TranscriptionFailed(Exception):
    """The provider refused this clip. Log it, skip it, keep going."""


class RateLimited(Exception):
    """The provider asked us to slow down. Back off and try the clip again."""


def cached_path(provider_id: str, clip_id: str, cache_root: Path | None = None) -> Path:
    return (cache_root or config.CACHE) / provider_id / f"{clip_id}.json"


def project_cost(manifest: pd.DataFrame, provider_id: str) -> float:
    """List price times audio minutes, printed before a run starts."""
    minutes = manifest["duration"].sum() / 60
    return minutes * float(config.PROVIDERS[provider_id]["usd_per_min"])


def run_provider(
    provider_id: str,
    manifest: pd.DataFrame,
    transcriber,
    audio_root: Path | None = None,
    cache_root: Path | None = None,
    spend_cap: float = config.SPEND_CAP_USD,
    max_rate_limit_retries: int = 5,
) -> dict:
    """Transcribe every uncached clip and return this provider's run summary.

    Three rules hold the run together. A cached clip is never re-requested, so
    a rerun costs nothing and resumes where it stopped. A failure is never
    cached, so the retry pass can see it rather than skipping it forever. And
    the spend cap is checked before each call rather than after, so it stops an
    overspend instead of reporting one.
    """
    audio_root = audio_root or config.AUDIO
    cache_root = cache_root or config.CACHE
    (cache_root / provider_id).mkdir(parents=True, exist_ok=True)

    costs: list[float] = []
    latencies: list[float] = []
    ok = failed = 0
    stopped_on_cap = False

    for _, row in manifest.iterrows():
        clip_id = str(row["clip_id"])
        destination = cached_path(provider_id, clip_id, cache_root)
        if destination.exists():
            ok += 1
            continue

        audio_path = audio_root / f"{clip_id}.wav"
        if not audio_path.exists():
            print(f"  {clip_id}: no audio on disk, skipped.")
            failed += 1
            continue

        # Stop before the call that would breach the cap, not after. Once any
        # clip has completed, its observed cost is a better estimate of the
        # next one than list price is, which is what catches a provider
        # billing above its published rate.
        next_estimate = (
            statistics.mean(costs)
            if costs
            else _list_cost(provider_id, float(row["duration"]))
        )
        if sum(costs) + next_estimate > spend_cap:
            stopped_on_cap = True
            print(
                f"  Spend cap: USD {sum(costs):.4f} spent, next clip is about "
                f"USD {next_estimate:.4f}, cap is USD {spend_cap:.4f}. "
                f"Stopping {provider_id} with {ok} clips done."
            )
            break

        result = _transcribe_with_backoff(
            transcriber, audio_path, provider_id, max_rate_limit_retries
        )
        if result is None:
            failed += 1
            continue

        record = {
            "clip_id": clip_id,
            "provider": provider_id,
            "model": config.PROVIDERS[provider_id]["model"],
            "text": result["text"],
            "latency_ms": result.get("latency_ms"),
            "audio_seconds": float(row["duration"]),
            "cost_usd": result.get("cost_usd", 0.0),
        }
        destination.write_text(json.dumps(record, indent=2))
        costs.append(record["cost_usd"])
        if record["latency_ms"] is not None:
            latencies.append(record["latency_ms"])
        ok += 1

    return {
        "provider": provider_id,
        "model": config.PROVIDERS[provider_id]["model"],
        "clips_ok": ok,
        "clips_failed": failed,
        "cost_usd": round(sum(costs), 4),
        "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "stopped_on_cap": stopped_on_cap,
    }


def _transcribe_with_backoff(
    transcriber, audio_path: Path, provider_id: str, max_retries: int
) -> dict | None:
    """Call the transcriber, backing off on rate limits. None means give up."""
    for attempt in range(max_retries):
        try:
            return transcriber(audio_path, provider_id)
        except RateLimited:
            if attempt == max_retries - 1:
                print(
                    f"  {audio_path.stem}: still rate limited after {max_retries} tries."
                )
                return None
            time.sleep(2**attempt)
        except TranscriptionFailed as exc:
            print(f"  {audio_path.stem}: {exc}")
            return None
    return None


# ---------------------------------------------------------------------------
# Real transcribers. One per vendor, all sharing the (audio_path, provider_id)
# signature the orchestrator calls with.
# ---------------------------------------------------------------------------


def _api_key(provider_id: str) -> str:
    key = os.getenv(str(config.PROVIDERS[provider_id]["env_key"]))
    if not key:
        raise TranscriptionFailed(
            f"{config.PROVIDERS[provider_id]['env_key']} is not set in .env"
        )
    return key


def _check(response: requests.Response) -> None:
    """Turn an HTTP status into the two exceptions the orchestrator understands."""
    if response.status_code == 429:
        raise RateLimited(response.text[:200])
    if response.status_code >= 500:
        raise RateLimited(f"HTTP {response.status_code}")  # Transient, worth a retry.
    if not response.ok:
        raise TranscriptionFailed(f"HTTP {response.status_code}: {response.text[:200]}")


def _list_cost(provider_id: str, audio_seconds: float) -> float:
    return audio_seconds / 60 * float(config.PROVIDERS[provider_id]["usd_per_min"])


def _json(response: requests.Response) -> dict:
    """Parse a provider response, or fail in the one way the run understands.

    A 200 carrying an HTML error page from a proxy is rare and real. Left
    unguarded it raises JSONDecodeError, which is neither of the two exceptions
    `_transcribe_with_backoff` catches, so it would escape and end a 400-clip
    unattended run on one bad response.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise TranscriptionFailed(
            f"response was not JSON: {response.text[:200]}"
        ) from exc
    if not isinstance(payload, dict):
        raise TranscriptionFailed(
            f"expected a JSON object, got {type(payload).__name__}"
        )
    return payload


def _reported_number(payload: dict, key: str) -> float | None:
    """A number a provider reported, or None if it is missing or unusable.

    Providers hand us durations and timings we then do arithmetic on. A value
    that will not convert would raise TypeError or ValueError, neither of
    which `_transcribe_with_backoff` catches, so one odd response would end a
    400-clip unattended run. None lets each caller fall back to its own
    measurement instead.
    """
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _reported_latency_ms(payload: dict, key: str, started: float) -> int:
    """The provider's own processing time when it gives one, ours otherwise.

    A latency figure is not worth losing a transcript over, so this falls back
    rather than raising.
    """
    reported = _reported_number(payload, key)
    if reported is not None:
        return round(reported)
    return round((time.monotonic() - started) * 1000)


def transcribe_groq(audio_path: Path, provider_id: str) -> dict:
    """Whisper, hosted by Groq. See DECISIONS D016.

    Groq exposes an OpenAI-compatible route, so the request shape is the one
    OpenAI documents. The host is the whole point of the change though: pointed
    at api.openai.com this would authenticate against the wrong service and bill
    an account that has no free tier, which is what the tests pin down.

    The free tier is capped per hour rather than per month, so a 429 here is
    ordinary traffic. `_check` turns it into RateLimited and the orchestrator
    backs off, which is why a 400-clip run needs no pacing of its own.
    """
    started = time.monotonic()
    key = _api_key(provider_id)  # Before opening the file, so a missing key is cheap.
    with audio_path.open("rb") as handle:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (audio_path.name, handle, "audio/wav")},
            data={
                "model": config.PROVIDERS[provider_id]["model"],
                "response_format": "json",
            },
            timeout=300,
        )
    _check(response)
    return {
        "text": _json(response).get("text", ""),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "cost_usd": 0.0,  # Free tier.
    }


def transcribe_deepgram(audio_path: Path, provider_id: str) -> dict:
    started = time.monotonic()
    response = requests.post(
        "https://api.deepgram.com/v1/listen",
        headers={
            "Authorization": f"Token {_api_key(provider_id)}",
            "Content-Type": "audio/wav",
        },
        params={
            "model": config.PROVIDERS[provider_id]["model"],
            "smart_format": "false",
        },
        data=audio_path.read_bytes(),
        timeout=300,
    )
    _check(response)
    payload = _json(response)
    try:
        text = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError) as exc:
        raise TranscriptionFailed(f"unexpected Deepgram payload: {exc}") from exc
    metadata = payload.get("metadata")
    reported = (
        _reported_number(metadata, "duration") if isinstance(metadata, dict) else None
    )
    seconds = reported if reported is not None else _wav_seconds(audio_path)
    return {
        "text": text,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "cost_usd": _list_cost(provider_id, seconds),
    }


def transcribe_assemblyai(audio_path: Path, provider_id: str) -> dict:
    """AssemblyAI's sync route: one request in, finished transcript out.

    The async route this replaced uploaded, submitted, then polled every two
    seconds until the job settled. It worked, but the latency it recorded was
    mostly that sleep timer rather than anything AssemblyAI did, and M5 puts
    that number in a column beside three providers that answer in one request.
    Every clip here is 3 to 30 seconds of 16 kHz mono PCM16, comfortably inside
    the sync route's 80 ms to 120 s and 40 MB limits. See DECISIONS D017.

    Two shapes here are AssemblyAI-specific and easy to get wrong. The key goes
    in the Authorization header raw, with no Bearer prefix, and the model is
    named in an X-AAI-Model header rather than in the body.
    """
    started = time.monotonic()
    key = _api_key(provider_id)
    with audio_path.open("rb") as handle:
        response = requests.post(
            "https://sync.assemblyai.com/transcribe",
            headers={
                "Authorization": key,  # Raw. A Bearer prefix 401s here.
                "X-AAI-Model": str(config.PROVIDERS[provider_id]["model"]),
            },
            files={"audio": (audio_path.name, handle, "audio/wav")},
            timeout=300,
        )
    _check(response)
    payload = _json(response)
    # Bill against the duration AssemblyAI itself measured, the same way the
    # Deepgram path uses metadata.duration. It is what the invoice will be
    # based on, and it saves re-reading the file we just uploaded.
    reported_ms = _reported_number(payload, "audio_duration_ms")
    seconds = (
        reported_ms / 1000 if reported_ms is not None else _wav_seconds(audio_path)
    )
    return {
        "text": payload.get("text") or "",
        "latency_ms": _reported_latency_ms(payload, "request_time_ms", started),
        "cost_usd": _list_cost(provider_id, seconds),
    }


def transcribe_gemini(audio_path: Path, provider_id: str) -> dict:
    started = time.monotonic()
    model = config.PROVIDERS[provider_id]["model"]
    mime = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={
            "x-goog-api-key": _api_key(provider_id),
            "Content-Type": "application/json",
        },
        json={
            "contents": [
                {
                    "parts": [
                        {"text": config.GEMINI_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(
                                    audio_path.read_bytes()
                                ).decode(),
                            }
                        },
                    ]
                }
            ]
        },
        timeout=300,
    )
    _check(response)
    payload = _json(response)
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        # A safety block returns a well-formed response with no candidate.
        raise TranscriptionFailed(f"no Gemini candidate: {str(payload)[:200]}") from exc
    return {
        "text": text.strip(),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "cost_usd": 0.0,  # Free tier.
    }


TRANSCRIBERS = {
    "groq": transcribe_groq,
    "deepgram": transcribe_deepgram,
    "assemblyai": transcribe_assemblyai,
    "google": transcribe_gemini,
}


def _wav_seconds(audio_path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(audio_path))
    return info.frames / info.samplerate


def real_transcriber(audio_path: Path, provider_id: str) -> dict:
    """Dispatch to the vendor that owns this configuration."""
    vendor = str(config.PROVIDERS[provider_id]["vendor"])
    return TRANSCRIBERS[vendor](audio_path, provider_id)


def main(provider_ids: list[str] | None = None) -> int:
    """Run every configuration, print the projection first, honour the cap."""
    load_dotenv(config.ROOT / ".env")
    manifest = pd.read_csv(config.MANIFEST)
    provider_ids = provider_ids or list(config.PROVIDERS)

    print(
        f"{len(manifest)} clips, {manifest['duration'].sum() / 60:.1f} audio minutes.\n"
    )
    print("Projected cost (list price):")
    for provider_id in provider_ids:
        print(f"  {provider_id:11s} USD {project_cost(manifest, provider_id):5.2f}")
    print(
        f"  {'TOTAL':11s} USD {sum(project_cost(manifest, p) for p in provider_ids):5.2f}"
    )
    print(f"  Cap: USD {config.SPEND_CAP_USD:.2f}\n")

    summaries = []
    spent = 0.0
    for provider_id in provider_ids:
        projected = project_cost(manifest, provider_id)
        if projected > config.SPEND_CAP_USD:
            print(
                f"{provider_id}: projected USD {projected:.2f} alone exceeds the cap. Skipped."
            )
            continue
        if spent >= config.SPEND_CAP_USD:
            print(f"{provider_id}: cap already reached at USD {spent:.2f}. Skipped.")
            continue

        print(f"--- {provider_id} ({config.PROVIDERS[provider_id]['model']}) ---")
        summary = run_provider(
            provider_id,
            manifest,
            real_transcriber,
            spend_cap=config.SPEND_CAP_USD - spent,
        )
        # SPEC prompt 03 task 5: one retry pass over whatever failed.
        if summary["clips_failed"]:
            print(f"  Retrying {summary['clips_failed']} failed clips once.")
            summary = run_provider(
                provider_id,
                manifest,
                real_transcriber,
                spend_cap=config.SPEND_CAP_USD - spent,
            )

        spent += summary["cost_usd"]
        summaries.append(summary)
        print(
            f"  ok {summary['clips_ok']}, failed {summary['clips_failed']}, "
            f"USD {summary['cost_usd']:.4f}, median {summary['median_latency_ms']} ms\n"
        )

    config.RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(
        config.RESULTS / "transcription_run_summary.csv", index=False
    )
    print(f"Total actual spend: USD {spent:.4f}")
    print(f"Wrote {config.RESULTS / 'transcription_run_summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
