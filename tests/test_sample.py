"""Stratified sampling, SPEC section 3.

The manifest is committed and the benchmark's numbers are only reproducible if
this draw is. So determinism is tested as hard as the quotas are.
"""

import pandas as pd
import pytest

from src.sample import annotate, check_quotas, compute_tiers, draw_sample

LEXICON = {"metformin", "warfarin", "amoxicillin"}


def accent_stats(**counts) -> dict:
    """Build an accents.json-shaped dict: accent -> total clips and per-split clips."""
    return {
        name: {"num_clips": total, "test": {"num_clips": in_split}}
        for name, (total, in_split) in counts.items()
    }


def clips(
    n: int,
    accent: str,
    domain: str = "clinical",
    transcript: str = "the patient is stable",
    duration: float = 10.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "clip_id": [f"{accent}-{domain}-{i}" for i in range(n)],
            "accent": accent,
            "domain": domain,
            "transcript": transcript,
            "duration": duration,
            "speaker_id": [f"spk-{accent}-{i % 7}" for i in range(n)],
            "gender": "Female",
            "age_group": "26-40",
            "country": "NG",
            "split": "test",
        }
    )


class TestComputeTiers:
    def test_top_five_by_total_clips_are_tier_a(self):
        stats = accent_stats(
            a=(100, 50), b=(90, 50), c=(80, 50), d=(70, 50), e=(60, 50), f=(50, 50)
        )
        tiers = compute_tiers(stats, split="test")
        assert [k for k, v in tiers.items() if v == "A"] == ["a", "b", "c", "d", "e"]

    def test_ranks_six_through_twentyfive_are_tier_b(self):
        stats = accent_stats(**{f"a{i:02d}": (1000 - i, 50) for i in range(30)})
        tiers = compute_tiers(stats, split="test")
        assert tiers["a05"] == "B"  # rank 6
        assert tiers["a24"] == "B"  # rank 25
        assert tiers["a25"] == "C"  # rank 26

    def test_tier_c_needs_a_minimum_presence_in_the_split(self):
        # SPEC section 3: rank 26 and below, and at least 15 clips in the split.
        stats = accent_stats(**{f"a{i:02d}": (1000 - i, 50) for i in range(26)})
        stats["thin"] = {"num_clips": 5, "test": {"num_clips": 3}}
        tiers = compute_tiers(stats, split="test")
        assert "thin" not in tiers

    def test_accent_absent_from_the_split_is_excluded(self):
        stats = accent_stats(a=(100, 50), b=(90, 50))
        stats["trainonly"] = {"num_clips": 80, "train": {"num_clips": 400}}
        tiers = compute_tiers(stats, split="test")
        assert "trainonly" not in tiers

    def test_the_all_pseudo_accent_is_excluded(self):
        stats = accent_stats(a=(100, 50), b=(90, 50))
        stats["all"] = {"num_clips": 99999, "test": {"num_clips": 6319}}
        tiers = compute_tiers(stats, split="test")
        assert "all" not in tiers


class TestAnnotate:
    def test_flags_a_drug(self):
        df = annotate(clips(1, "yoruba", transcript="takes metformin daily"), LEXICON)
        assert bool(df.loc[0, "has_drug"]) is True
        assert df.loc[0, "drug_terms"] == "metformin"

    def test_flags_a_dose(self):
        df = annotate(clips(1, "yoruba", transcript="give 500 mg now"), LEXICON)
        assert bool(df.loc[0, "has_dose"]) is True
        assert df.loc[0, "dose_strings"] == "500.0 mg"

    def test_flags_a_negation(self):
        df = annotate(clips(1, "yoruba", transcript="denies chest pain"), LEXICON)
        assert bool(df.loc[0, "has_negation"]) is True

    def test_flags_nothing_on_neutral_text(self):
        df = annotate(clips(1, "yoruba", transcript="the sky is blue"), LEXICON)
        assert not df.loc[0, "has_drug"]
        assert not df.loc[0, "has_dose"]
        assert not df.loc[0, "has_negation"]

    def test_annotates_against_normalized_text(self):
        # "Five hundred milligrams" only becomes a dose after the normalizer
        # turns the number-words into digits.
        df = annotate(clips(1, "yoruba", transcript="Give five hundred mg."), LEXICON)
        assert bool(df.loc[0, "has_dose"]) is True


class TestDrawSample:
    @pytest.fixture
    def pool(self):
        """Six accents with plenty of clips each, half of them entity bearing."""
        frames = []
        for accent in ["a", "b", "c", "d", "e", "f"]:
            for domain in ["clinical", "general"]:
                entity = clips(60, accent, domain, transcript="takes metformin 500 mg")
                entity["clip_id"] = entity["clip_id"] + "-ent"
                plain = clips(60, accent, domain, transcript="the sky is blue today")
                frames.append(pd.concat([entity, plain], ignore_index=True))
        return annotate(pd.concat(frames, ignore_index=True), LEXICON)

    @pytest.fixture
    def tiers(self):
        return {"a": "A", "b": "A", "c": "B", "d": "B", "e": "C", "f": "C"}

    def test_draws_the_requested_total(self, pool, tiers):
        assert (
            len(draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20}))
            == 60
        )

    def test_respects_the_tier_allocation(self, pool, tiers):
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        assert sample["tier"].value_counts().to_dict() == {"A": 20, "B": 20, "C": 20}

    def test_hits_the_clinical_share_within_a_clip(self, pool, tiers):
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        for tier in "ABC":
            in_tier = sample[sample["tier"] == tier]
            clinical = (in_tier["domain"] == "clinical").sum()
            assert abs(clinical - 0.8 * len(in_tier)) <= 1

    def test_caps_clips_per_accent(self, pool, tiers):
        # Two accents per tier and a cap of 8 leaves room for 16 per tier, so
        # 12 is a target the cap can bind on without starving the draw.
        sample = draw_sample(
            pool, tiers, size=36, per_tier={"A": 12, "B": 12, "C": 12}, max_per_accent=8
        )
        assert sample["accent"].value_counts().max() <= 8

    def test_spreads_across_accents_rather_than_draining_one(self, pool, tiers):
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        for tier in "ABC":
            assert sample[sample["tier"] == tier]["accent"].nunique() >= 2

    def test_prefers_entity_bearing_clips(self, pool, tiers):
        # Half the pool carries an entity, so a blind draw lands near 50 percent.
        # SPEC section 3 wants at least 55, which only happens on purpose.
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        assert sample["has_entity"].mean() >= 0.55

    def test_excludes_clips_outside_the_duration_window(self, pool, tiers):
        # Strided rather than sliced, so every accent keeps a third of its clips.
        # A contiguous slice would empty one tier and test starvation instead.
        pool.loc[pool.index[0::3], "duration"] = 1.0  # under the 3 second floor
        pool.loc[pool.index[1::3], "duration"] = 45.0  # over the 30 second ceiling
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        assert sample["duration"].between(3.0, 30.0).all()

    def test_never_draws_the_same_clip_twice(self, pool, tiers):
        sample = draw_sample(pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})
        assert sample["clip_id"].is_unique

    def test_is_deterministic_under_the_same_seed(self, pool, tiers):
        first = draw_sample(
            pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20}, seed=42
        )
        second = draw_sample(
            pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20}, seed=42
        )
        assert list(first["clip_id"]) == list(second["clip_id"])

    def test_a_different_seed_gives_a_different_draw(self, pool, tiers):
        first = draw_sample(
            pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20}, seed=42
        )
        second = draw_sample(
            pool, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20}, seed=7
        )
        assert list(first["clip_id"]) != list(second["clip_id"])

    def test_reports_rather_than_silently_under_delivering(self, pool, tiers):
        # A tier with nothing in it must not be papered over by stealing clips
        # from another tier, because the tier comparison is the whole point.
        thin = pool[pool["accent"].isin(["a", "b"])]
        with pytest.raises(ValueError, match="Tier B"):
            draw_sample(thin, tiers, size=60, per_tier={"A": 20, "B": 20, "C": 20})


class TestCheckQuotas:
    def test_passes_a_well_formed_manifest(
        self,
    ):
        # 4 accents, 24 clinical and 6 general each: 120 clips, 96 of them
        # clinical, which is exactly the 80 percent share check_quotas enforces.
        frames = []
        for accent in ["a", "b", "c", "d"]:
            for domain, n in [("clinical", 24), ("general", 6)]:
                group = clips(n, accent, domain, transcript="metformin 500 mg")
                group["tier"] = "A"
                frames.append(group)
        manifest = annotate(pd.concat(frames, ignore_index=True), LEXICON)
        manifest["has_entity"] = True
        failures = check_quotas(manifest, size=120, per_tier={"A": 120}, min_accents=4)
        assert failures == []

    def test_reports_a_short_manifest(self):
        manifest = annotate(clips(10, "a", "clinical"), LEXICON)
        manifest["tier"] = "A"
        manifest["has_entity"] = False
        failures = check_quotas(manifest, size=400, per_tier={"A": 400}, min_accents=4)
        assert any("400" in f for f in failures)

    def test_reports_too_few_accents_in_a_tier(self):
        manifest = annotate(clips(50, "a", "clinical"), LEXICON)
        manifest["tier"] = "A"
        manifest["has_entity"] = True
        failures = check_quotas(manifest, size=50, per_tier={"A": 50}, min_accents=4)
        assert any("accent" in f.lower() for f in failures)

    def test_reports_a_missed_entity_quota(self):
        manifest = annotate(clips(50, "a", "clinical"), LEXICON)
        manifest["tier"] = "A"
        manifest["has_entity"] = False
        failures = check_quotas(manifest, size=50, per_tier={"A": 50}, min_accents=1)
        assert any("entity" in f.lower() for f in failures)
