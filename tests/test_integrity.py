"""Automated integrity checks that stand in for the human spot-listen.

prompts/02-sample.md blocks on Suwaid listening to 20 clips before transcription
starts. Nobody is awake during an overnight run, so these checks run instead and
the listen happens retroactively. They have to catch the same class of problem:
audio that does not match the transcript beside it.

The stop condition is deliberately hard to trip by accident, because a false
positive here halts a run that has hours of downloading behind it.
"""

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from src.integrity import (
    check_duplicate_pairings,
    check_duration,
    check_rms,
    check_speech_rate,
    should_halt,
    speech_rate_bounds,
)


def write_wav(path, seconds=10.0, rate=16_000, amplitude=0.2):
    samples = amplitude * np.sin(
        2 * np.pi * 220 * np.arange(int(seconds * rate)) / rate
    )
    sf.write(path, samples.astype(np.float32), rate, subtype="PCM_16")
    return path


class TestDuration:
    def test_a_matching_duration_passes(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", seconds=10.0)
        assert check_duration(path, expected=10.0) is None

    def test_tolerates_half_to_one_and_a_half_times(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", seconds=10.0)
        assert check_duration(path, expected=7.0) is None
        assert check_duration(path, expected=19.0) is None

    def test_flags_audio_far_shorter_than_the_manifest_says(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", seconds=2.0)
        assert "duration" in check_duration(path, expected=20.0)

    def test_flags_audio_far_longer_than_the_manifest_says(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", seconds=30.0)
        assert "duration" in check_duration(path, expected=5.0)

    def test_flags_a_missing_file(self, tmp_path):
        assert "missing" in check_duration(tmp_path / "gone.wav", expected=10.0)


class TestRms:
    def test_normal_speech_level_passes(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", amplitude=0.2)
        assert check_rms(path) is None

    def test_flags_digital_silence(self, tmp_path):
        sf.write(tmp_path / "s.wav", np.zeros(16_000, dtype=np.float32), 16_000)
        assert "silen" in check_rms(tmp_path / "s.wav").lower()

    def test_flags_audio_below_the_threshold(self, tmp_path):
        path = write_wav(tmp_path / "c.wav", amplitude=0.0001)
        assert check_rms(path) is not None


class TestSpeechRate:
    def test_a_normal_rate_passes(self):
        # 30 words in 10 seconds is 3 words per second, near this corpus's median.
        assert check_speech_rate(" ".join(["word"] * 30), 10.0) is None

    def test_a_slow_but_human_rate_passes(self):
        # 0.8 words per second is a careful reader of long drug names. 12.2
        # percent of the test split sits below 1.0, so this must not flag.
        assert check_speech_rate(" ".join(["word"] * 8), 10.0) is None

    def test_flags_an_implausibly_slow_rate(self):
        # 2 words in 10 seconds is a fifth of the corpus median and usually
        # means the transcript belongs to a different clip.
        assert check_speech_rate("two words", 10.0) is not None

    def test_flags_an_implausibly_fast_rate(self):
        assert check_speech_rate(" ".join(["word"] * 100), 10.0) is not None

    def test_honours_explicit_bounds(self):
        assert check_speech_rate(" ".join(["w"] * 10), 10.0, low=0.5, high=5.0) is None
        assert (
            check_speech_rate(" ".join(["w"] * 10), 10.0, low=2.0, high=5.0) is not None
        )

    def test_flags_zero_duration_rather_than_dividing_by_it(self):
        assert check_speech_rate("some words", 0.0) is not None


class TestSpeechRateBounds:
    def test_derives_bounds_from_the_manifest_median(self):
        # 20 words in 10 seconds is 2.0 w/s, so bounds are 0.5 and 8.0.
        manifest = pd.DataFrame(
            {"transcript": [" ".join(["w"] * 20)] * 5, "duration": [10.0] * 5}
        )
        low, high = speech_rate_bounds(manifest)
        assert low == pytest.approx(0.5)
        assert high == pytest.approx(8.0)

    def test_falls_back_when_the_manifest_is_empty(self):
        low, high = speech_rate_bounds(pd.DataFrame({"transcript": [], "duration": []}))
        assert low > 0 and high > low


class TestDuplicatePairings:
    def test_clean_manifest_reports_nothing(self):
        rows = [
            {
                "clip_id": "a",
                "transcript": "one",
                "speaker_id": "s1",
                "path": "/p/a.wav",
            },
            {
                "clip_id": "b",
                "transcript": "two",
                "speaker_id": "s2",
                "path": "/p/b.wav",
            },
        ]
        assert check_duplicate_pairings(rows) == {"suspicious": [], "expected": []}

    def test_same_prompt_from_two_speakers_is_expected_not_suspicious(self):
        # AfriSpeech has many speakers read the same prompt. Flagging that as an
        # indexing bug would halt an overnight run on the dataset's own design.
        rows = [
            {
                "clip_id": "a",
                "transcript": "same",
                "speaker_id": "s1",
                "path": "/p/a.wav",
            },
            {
                "clip_id": "b",
                "transcript": "same",
                "speaker_id": "s2",
                "path": "/p/b.wav",
            },
        ]
        result = check_duplicate_pairings(rows)
        assert result["suspicious"] == []
        assert len(result["expected"]) == 1

    def test_same_transcript_from_one_speaker_is_suspicious(self):
        rows = [
            {
                "clip_id": "a",
                "transcript": "same",
                "speaker_id": "s1",
                "path": "/p/a.wav",
            },
            {
                "clip_id": "b",
                "transcript": "same",
                "speaker_id": "s1",
                "path": "/p/b.wav",
            },
        ]
        assert len(check_duplicate_pairings(rows)["suspicious"]) == 1

    def test_two_clips_pointing_at_one_audio_file_is_suspicious(self):
        # The real indexing bug: two manifest rows resolving to the same audio.
        rows = [
            {
                "clip_id": "a",
                "transcript": "one",
                "speaker_id": "s1",
                "path": "/p/x.wav",
            },
            {
                "clip_id": "b",
                "transcript": "two",
                "speaker_id": "s2",
                "path": "/p/x.wav",
            },
        ]
        assert len(check_duplicate_pairings(rows)["suspicious"]) == 1


class TestShouldHalt:
    def test_does_not_halt_on_a_clean_run(self):
        assert should_halt(flagged=0, suspicious=[]) is False

    def test_tolerates_two_flagged_clips(self):
        # The overnight prompt halts on more than 2 of 20, not on 2.
        assert should_halt(flagged=2, suspicious=[]) is False

    def test_halts_on_three_flagged_clips(self):
        assert should_halt(flagged=3, suspicious=[]) is True

    def test_halts_on_any_suspicious_pairing(self):
        assert should_halt(flagged=0, suspicious=["a/b"]) is True
