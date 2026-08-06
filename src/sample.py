"""Stratified 400-clip sample, SPEC section 3.

The manifest this writes is committed, and every number the benchmark reports is
computed over it. So the draw has to be reproducible: one seed, no wall-clock, no
set iteration order, no dependence on how pandas happens to order a groupby.

Run:  python -m src.sample
"""

from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd
import requests
from whisper_normalizer.english import EnglishTextNormalizer

from src import config
from src.entities import find_dose_pairs, find_drug_mentions, find_negations
from src.lexicon import load as load_lexicon

# SPEC section 2 names these fields; the real CSV uses different ones. D003.
COLUMN_MAP = {"user_ids": "speaker_id", "audio_paths": "path"}

MANIFEST_COLUMNS = [
    "clip_id",
    "split",
    "accent",
    "tier",
    "domain",
    "duration",
    "transcript",
    "has_drug",
    "drug_terms",
    "has_dose",
    "dose_strings",
    "has_negation",
    "has_entity",
    "gender",
    "age_group",
    "country",
    "speaker_id",
    "path",
]

_normalizer = EnglishTextNormalizer()


def fetch_split(split: str) -> pd.DataFrame:
    """Download one split's transcript CSV and rename SPEC's fields onto it.

    Fetched with `requests` rather than handing the URL to pandas, because
    pandas reaches for urllib, which on this machine has no root CA bundle and
    fails every HTTPS request with CERTIFICATE_VERIFY_FAILED. requests carries
    certifi and works.
    """
    url = f"{config.HF_BASE}/transcripts/{split}.csv"
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    frame = frame.rename(columns=COLUMN_MAP)
    # clip_id is audio_ids, not the filename. 46 filenames in the test split
    # repeat across session directories: the same prompt read by two different
    # speakers is stored under the same basename in two different folders, with
    # different durations and the same transcript. Keying on the basename would
    # have made one clip overwrite the other on extraction and put a duplicate
    # audio-transcript pairing into the manifest. audio_paths and audio_ids are
    # both unique across all 6,319 rows; the basename is unique across 6,273.
    frame["clip_id"] = frame["audio_ids"].astype(str)
    return frame


def choose_split() -> tuple[str, pd.DataFrame]:
    """First split whose transcript CSV loads with non-empty transcripts.

    SPEC section 2 asks for test, then dev, then train, and says to verify at
    run time rather than assume, because the 2023 challenge withheld the test
    transcripts and released them later.
    """
    problems = []
    for split in config.SPLIT_PREFERENCE:
        try:
            frame = fetch_split(split)
        except (requests.RequestException, ValueError, OSError) as exc:
            problems.append(f"{split}: {exc}")
            continue
        usable = frame["transcript"].astype(str).str.strip().str.len() > 0
        if usable.sum() == 0:
            problems.append(f"{split}: loaded {len(frame)} rows, all transcripts empty")
            continue
        print(f"Split: {split}. {len(frame)} rows, {usable.sum()} with a transcript.")
        return split, frame[usable].reset_index(drop=True)
    raise RuntimeError(
        "No split loaded with usable transcripts:\n  " + "\n  ".join(problems)
    )


def fetch_accent_stats() -> dict:
    """accents.json, the per-accent clip counts the tiers are computed from."""
    response = requests.get(f"{config.HF_BASE}/accents.json", timeout=60)
    response.raise_for_status()
    return json.loads(response.text)


def compute_tiers(accent_stats: dict, split: str) -> dict[str, str]:
    """Accent to tier, per SPEC section 3.

    Tier A is the top 5 accents by total clip count across the whole dataset,
    B is ranks 6 through 25, and C is rank 26 and below with at least 15 clips
    in the chosen split. Accents missing from the split are dropped: an accent
    with no audio to draw from is not a tier member, it is a gap.
    """
    present = {
        accent: stats
        for accent, stats in accent_stats.items()
        if accent != "all" and isinstance(stats, dict) and split in stats
    }
    # Sort by clip count, then by name, so ties never depend on dict order.
    ranked = sorted(present.items(), key=lambda kv: (-kv[1].get("num_clips", 0), kv[0]))

    tiers: dict[str, str] = {}
    for rank, (accent, stats) in enumerate(ranked):
        in_split = stats[split].get("num_clips", 0)
        if rank < 5:
            tiers[accent] = "A"
        elif rank < 25:
            tiers[accent] = "B"
        elif in_split >= config.MIN_TIER_C_CLIPS_IN_SPLIT:
            tiers[accent] = "C"
    return tiers


def annotate(frame: pd.DataFrame, lexicon: set[str]) -> pd.DataFrame:
    """Add the entity columns, computed on normalized text.

    Normalizing here and nowhere else is what lets the manifest's annotations be
    compared against scoring-time extraction later: both see the same string.
    Returns a new frame; the argument is not touched.
    """
    out = frame.copy()
    normalized = out["transcript"].astype(str).map(_normalizer)

    drugs = normalized.map(lambda text: find_drug_mentions(text, lexicon))
    doses = normalized.map(find_dose_pairs)
    negations = normalized.map(find_negations)

    out["has_drug"] = drugs.map(bool)
    out["drug_terms"] = drugs.map("|".join)
    out["has_dose"] = doses.map(bool)
    out["dose_strings"] = doses.map(
        lambda pairs: "|".join(f"{v} {u}" for v, u in pairs)
    )
    out["has_negation"] = negations.map(bool)
    out["has_entity"] = out["has_drug"] | out["has_dose"] | out["has_negation"]
    return out


def _draw_stratum(
    candidates: pd.DataFrame,
    target: int,
    accent_counts: dict[str, int],
    max_per_accent: int,
    rng: np.random.Generator,
) -> list[int]:
    """Round-robin across accents, entity-bearing clips first within each accent.

    Round-robin is what satisfies "spread across at least 4 accents" without a
    separate rule for it, and taking entity-bearing clips on the early passes is
    what lifts entity coverage above the blind-draw rate. Returns row labels.
    """
    queues: dict[str, list[int]] = {}
    for accent in sorted(candidates["accent"].unique()):
        rows = candidates[candidates["accent"] == accent]
        shuffled = rows.iloc[rng.permutation(len(rows))]
        # Stable sort, so entity-bearing clips lead while the shuffle survives.
        ordered = shuffled.sort_values("has_entity", ascending=False, kind="stable")
        queues[accent] = list(ordered.index)

    chosen: list[int] = []
    while len(chosen) < target:
        took_any = False
        for accent in sorted(queues):
            if len(chosen) >= target:
                break
            if accent_counts.get(accent, 0) >= max_per_accent:
                continue
            if not queues[accent]:
                continue
            chosen.append(queues[accent].pop(0))
            accent_counts[accent] = accent_counts.get(accent, 0) + 1
            took_any = True
        if not took_any:
            break  # Every accent is exhausted or capped.
    return chosen


def draw_sample(
    frame: pd.DataFrame,
    tiers: dict[str, str],
    size: int = config.SAMPLE_SIZE,
    per_tier: dict[str, int] | None = None,
    max_per_accent: int = config.MAX_CLIPS_PER_ACCENT,
    clinical_share: float = config.CLINICAL_SHARE,
    seed: int = config.SEED,
) -> pd.DataFrame:
    """Draw the stratified sample. Raises rather than under-delivering a tier.

    A tier that cannot be filled is a finding about the dataset, not something
    to paper over by taking extra clips from a richer tier. The tier comparison
    is the benchmark's whole question, so a silently unbalanced draw would make
    the headline number meaningless.
    """
    per_tier = per_tier or dict(config.TIER_ALLOCATION)
    rng = np.random.default_rng(seed)

    pool = frame.copy()
    pool["tier"] = pool["accent"].map(tiers)
    pool = pool[pool["tier"].notna()]
    pool = pool[pool["duration"].between(config.MIN_DURATION_S, config.MAX_DURATION_S)]
    # One stable order before any drawing, so row labels never depend on the
    # order the transcript CSV happened to arrive in.
    pool = pool.sort_values("clip_id", kind="stable")

    picked: list[int] = []
    for tier in sorted(per_tier):
        tier_target = per_tier[tier]
        in_tier = pool[pool["tier"] == tier]
        accent_counts: dict[str, int] = {}

        clinical_target = round(tier_target * clinical_share)
        targets = [
            ("clinical", clinical_target),
            ("general", tier_target - clinical_target),
        ]

        tier_picked: list[int] = []
        for domain, domain_target in targets:
            candidates = in_tier[in_tier["domain"] == domain]
            tier_picked += _draw_stratum(
                candidates, domain_target, accent_counts, max_per_accent, rng
            )

        if len(tier_picked) < tier_target:
            raise ValueError(
                f"Tier {tier}: only {len(tier_picked)} of {tier_target} clips "
                f"available. {in_tier['accent'].nunique()} accents in tier, "
                f"{len(in_tier)} clips after the duration filter. Widen the tier "
                f"or lower the allocation; do not backfill from another tier."
            )
        picked += tier_picked

    sample = pool.loc[picked].copy()
    if len(sample) != size:
        raise ValueError(f"Drew {len(sample)} clips, expected {size}.")
    return sample.sort_values(["tier", "accent", "clip_id"]).reset_index(drop=True)


def check_quotas(
    manifest: pd.DataFrame,
    size: int = config.SAMPLE_SIZE,
    per_tier: dict[str, int] | None = None,
    min_accents: int = config.MIN_ACCENTS_PER_TIER,
    max_per_accent: int = config.MAX_CLIPS_PER_ACCENT,
    min_entity_share: float = config.MIN_ENTITY_SHARE,
) -> list[str]:
    """Every SPEC section 3 quota, as a list of failures. Empty means it passed."""
    per_tier = per_tier or dict(config.TIER_ALLOCATION)
    failures: list[str] = []

    if len(manifest) != size:
        failures.append(f"Manifest has {len(manifest)} rows, expected {size}.")

    counts = manifest["tier"].value_counts().to_dict()
    for tier, expected in per_tier.items():
        if counts.get(tier, 0) != expected:
            failures.append(
                f"Tier {tier} has {counts.get(tier, 0)} clips, expected {expected}."
            )

    for tier in sorted(manifest["tier"].unique()):
        in_tier = manifest[manifest["tier"] == tier]
        if in_tier["accent"].nunique() < min_accents:
            failures.append(
                f"Tier {tier} spans {in_tier['accent'].nunique()} accents, "
                f"needs at least {min_accents}."
            )
        clinical = (in_tier["domain"] == "clinical").mean()
        if abs(clinical - config.CLINICAL_SHARE) > 0.02:
            failures.append(
                f"Tier {tier} is {clinical:.1%} clinical, expected "
                f"{config.CLINICAL_SHARE:.0%}."
            )

    worst_accent = manifest["accent"].value_counts()
    if not worst_accent.empty and worst_accent.iloc[0] > max_per_accent:
        failures.append(
            f"Accent {worst_accent.index[0]} has {worst_accent.iloc[0]} clips, "
            f"cap is {max_per_accent}."
        )

    entity_share = manifest["has_entity"].mean()
    if entity_share < min_entity_share:
        failures.append(
            f"Entity coverage is {entity_share:.1%}, needs at least "
            f"{min_entity_share:.0%}."
        )

    outside = ~manifest["duration"].between(
        config.MIN_DURATION_S, config.MAX_DURATION_S
    )
    if outside.any():
        failures.append(
            f"{outside.sum()} clips fall outside the 3 to 30 second window."
        )

    if not manifest["clip_id"].is_unique:
        failures.append("Manifest holds duplicate clip_ids.")

    return failures


def print_sample_sheet(manifest: pd.DataFrame, split: str) -> None:
    """The breakdown SPEC section 3 asks to be printed after the draw."""
    total_minutes = manifest["duration"].sum() / 60
    print(
        f"\n{'=' * 68}\nSAMPLE SHEET  ({len(manifest)} clips from the {split} split)\n{'=' * 68}"
    )

    print("\nBy tier:")
    for tier in sorted(manifest["tier"].unique()):
        in_tier = manifest[manifest["tier"] == tier]
        print(
            f"  Tier {tier}: {len(in_tier):3d} clips, "
            f"{in_tier['accent'].nunique():2d} accents, "
            f"{(in_tier['domain'] == 'clinical').mean():.0%} clinical, "
            f"{in_tier['has_entity'].mean():.0%} entity, "
            f"{in_tier['duration'].sum() / 60:5.1f} min"
        )

    print("\nBy domain:")
    for domain, group in manifest.groupby("domain"):
        print(
            f"  {domain:9s}: {len(group):3d} clips, {group['duration'].sum() / 60:5.1f} min"
        )

    print("\nBy accent:")
    for tier in sorted(manifest["tier"].unique()):
        in_tier = manifest[manifest["tier"] == tier]
        counts = in_tier["accent"].value_counts()
        listed = ", ".join(f"{a} {n}" for a, n in counts.items())
        print(f"  Tier {tier}: {listed}")

    print("\nEntity coverage:")
    for column, label in [
        ("has_drug", "drug mention"),
        ("has_dose", "dosage"),
        ("has_negation", "negation"),
        ("has_entity", "any entity"),
    ]:
        print(
            f"  {label:13s}: {manifest[column].sum():3d} clips ({manifest[column].mean():.1%})"
        )

    print(
        f"\nTotal audio: {total_minutes:.1f} minutes ({total_minutes / 60:.2f} hours)"
    )


def build() -> pd.DataFrame:
    """Draw the sample, check every quota, and write data/manifest.csv."""
    lexicon = load_lexicon()
    print(f"Lexicon: {len(lexicon)} terms.")

    split, frame = choose_split()
    stats = fetch_accent_stats()
    tiers = compute_tiers(stats, split)
    by_tier: dict[str, int] = {}
    for tier in tiers.values():
        by_tier[tier] = by_tier.get(tier, 0) + 1
    print(
        f"Tiers: A={by_tier.get('A', 0)}, B={by_tier.get('B', 0)}, C={by_tier.get('C', 0)} accents."
    )

    annotated = annotate(frame, lexicon)
    manifest = draw_sample(annotated, tiers)

    failures = check_quotas(manifest)
    print_sample_sheet(manifest, split)

    print("\nQuota checks:")
    if failures:
        for failure in failures:
            print(f"  FAIL  {failure}")
    else:
        print("  PASS  every SPEC section 3 quota.")

    manifest = manifest.reindex(columns=MANIFEST_COLUMNS)
    config.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(config.MANIFEST, index=False)
    print(f"\nWrote {config.MANIFEST}")

    if failures:
        raise SystemExit(1)
    return manifest


if __name__ == "__main__":
    sys.exit(0 if build() is not None else 1)
