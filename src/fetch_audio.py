"""Fetch the manifest's audio, SPEC section 3.

AfriSpeech-200 stores audio as one gzipped tar per accent and split. SPEC
section 3 asks for per-accent streaming configs, which the `datasets` library
can no longer do for this dataset (D001), so each needed tarball is streamed
over HTTPS and only the manifest's members are written out. Nothing is kept on
disk except the 400 WAVs.

Streaming rather than downloading whole tarballs first matters here: the 86
tarballs this manifest needs total 4.67 GB, and only about 70 MB of that is
wanted. Reading them as a stream means the unwanted bytes are decompressed and
discarded rather than stored.

Run:  python -m src.fetch_audio
"""

from __future__ import annotations

import io
import sys
import tarfile
import time

import numpy as np
import pandas as pd
import requests
import soundfile as sf
import soxr

from src import config


def member_key(path: str) -> str:
    """The session directory and filename, which is what both sides agree on.

    A manifest path looks like `/AfriSpeech-100/test/<session>/<name>.wav` and
    the matching tar member looks like `data/data/intron/<session>/<name>.wav`.
    Only the last two components are shared. The session directory has to be
    part of the key: 46 basenames in the test split appear under two different
    sessions, and keying on the basename alone pairs the wrong audio with a
    transcript. See DECISIONS D012.
    """
    cleaned = path.strip().lstrip("/")
    if not cleaned.endswith(".wav"):
        cleaned += ".wav"
    parts = cleaned.split("/")
    return "/".join(parts[-2:])


def needed_tarballs(rows) -> list[tuple[str, str]]:
    """Distinct (accent, split) pairs the manifest needs, in a stable order."""
    pairs = {(row["accent"], row["split"]) for row in rows}
    return sorted(pairs)


def tarball_url(accent: str, split: str, shard: int = 0) -> str:
    return f"{config.HF_BASE}/audio/{accent}/{split}/{split}_{accent}_{shard}.tar.gz"


def _request_with_retry(
    method: str, url: str, attempts: int = 4, **kwargs
) -> requests.Response | None:
    """One HTTP request with exponential backoff. Returns None once it gives up.

    HuggingFace redirects to a CDN that intermittently stalls, and this machine
    sleeps. Neither is a reason to end a run that has hours of work behind it,
    so transient failures back off and retry and a persistent one returns None
    for the caller to report.
    """
    for attempt in range(attempts):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code < 500:
                return response
            last = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last = str(exc)
        if attempt < attempts - 1:
            time.sleep(2**attempt)
    print(f"  giving up on {method} {url.rsplit('/', 1)[-1]}: {last}", flush=True)
    return None


def project_download_bytes(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """Exact size of every tarball, by HEAD request, before anything downloads.

    CLAUDE.md says to abort if the projected download passes 8 GB. Measuring it
    rather than estimating it is the only way that rule means anything. A
    tarball whose size cannot be read records 0 and is reported; it must not
    end the run, which is what an uncaught timeout here did on the first
    attempt at this download.
    """
    sizes: dict[tuple[str, str], int] = {}
    for index, (accent, split) in enumerate(pairs, start=1):
        response = _request_with_retry(
            "HEAD", tarball_url(accent, split), allow_redirects=True, timeout=30
        )
        sizes[(accent, split)] = (
            int(response.headers.get("content-length", 0))
            if response is not None and response.ok
            else 0
        )
        if index % 20 == 0:
            print(f"  sized {index}/{len(pairs)} tarballs", flush=True)
    return sizes


def to_mono_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Downmix to mono and resample to 16 kHz, as float32.

    16 kHz mono is what every ASR API resamples to internally, so doing it once
    here keeps the uploads small and guarantees all five providers hear exactly
    the same bytes.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != config.TARGET_SAMPLE_RATE:
        audio = soxr.resample(audio, sample_rate, config.TARGET_SAMPLE_RATE)
    return audio.astype(np.float32)


def _extract_from_stream(
    accent: str,
    split: str,
    wanted: dict[str, str],
) -> tuple[int, list[str]]:
    """Stream one tarball and write the wanted members as 16 kHz mono WAV.

    `wanted` maps member_key to clip_id. Returns how many were written and the
    keys that never appeared in the archive.
    """
    remaining = dict(wanted)
    written = 0

    response = _request_with_retry(
        "GET", tarball_url(accent, split), stream=True, timeout=(30, 300)
    )
    if response is None:
        raise requests.RequestException(
            f"{accent}/{split}: download failed after retries"
        )
    response.raise_for_status()
    response.raw.decode_content = True

    # Stream mode ("r|gz") reads forward only and never seeks, which is what
    # allows this to run against a socket instead of a downloaded file.
    with tarfile.open(fileobj=response.raw, mode="r|gz") as archive:
        for member in archive:
            if not remaining:
                break
            if not member.isfile():
                continue
            key = member_key(member.name)
            clip_id = remaining.pop(key, None)
            if clip_id is None:
                continue

            payload = archive.extractfile(member)
            if payload is None:
                continue
            samples, rate = sf.read(io.BytesIO(payload.read()), dtype="float64")
            sf.write(
                config.AUDIO / f"{clip_id}.wav",
                to_mono_16k(samples, rate),
                config.TARGET_SAMPLE_RATE,
                subtype="PCM_16",
            )
            written += 1

    return written, sorted(remaining)


def fetch(manifest: pd.DataFrame | None = None) -> pd.DataFrame:
    """Fetch every manifest clip that is not already on disk."""
    if manifest is None:
        manifest = pd.read_csv(config.MANIFEST)
    config.AUDIO.mkdir(parents=True, exist_ok=True)

    missing = manifest[
        ~manifest["clip_id"].map(lambda cid: (config.AUDIO / f"{cid}.wav").exists())
    ]
    print(f"{len(manifest)} clips in manifest, {len(missing)} not yet on disk.")
    if missing.empty:
        return manifest

    pairs = needed_tarballs(missing.to_dict("records"))
    sizes = project_download_bytes(pairs)
    total = sum(sizes.values())
    unreachable = [pair for pair, size in sizes.items() if size == 0]

    print(
        f"\nProjected download: {total / 1024**3:.2f} GB across {len(pairs)} tarballs "
        f"(abort rule: {config.MAX_DOWNLOAD_BYTES / 1024**3:.0f} GB)."
    )
    if unreachable:
        print(f"  Unreachable: {unreachable}")
    if total > config.MAX_DOWNLOAD_BYTES:
        raise SystemExit(
            f"Projected download {total / 1024**3:.2f} GB exceeds the "
            f"{config.MAX_DOWNLOAD_BYTES / 1024**3:.0f} GB rule in CLAUDE.md. Stopping."
        )

    never_found: list[str] = []
    for index, (accent, split) in enumerate(pairs, start=1):
        rows = missing[(missing["accent"] == accent) & (missing["split"] == split)]
        wanted = {member_key(row["path"]): row["clip_id"] for _, row in rows.iterrows()}
        size_mb = sizes[(accent, split)] / 1024**2

        try:
            written, absent = _extract_from_stream(accent, split, wanted)
        except (requests.RequestException, tarfile.TarError, OSError) as exc:
            # One bad tarball must not end the run. The gap is reported at the
            # end and shows up in the manifest coverage check either way.
            print(f"[{index:3d}/{len(pairs)}] {accent:16s} FAILED: {exc}")
            never_found += list(wanted)
            continue

        never_found += absent
        note = f", {len(absent)} not in archive" if absent else ""
        print(
            f"[{index:3d}/{len(pairs)}] {accent:16s} {size_mb:7.1f} MB  "
            f"{written}/{len(wanted)} written{note}",
            flush=True,
        )

    on_disk = sum((config.AUDIO / f"{cid}.wav").exists() for cid in manifest["clip_id"])
    print(f"\nAudio on disk: {on_disk}/{len(manifest)} clips.")
    if never_found:
        print(f"Never found in any archive: {len(never_found)} clips.")
    return manifest


if __name__ == "__main__":
    fetch()
    sys.exit(0)
