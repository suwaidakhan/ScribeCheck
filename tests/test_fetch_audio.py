"""Audio fetch: tarball selection, member matching, resampling.

The download itself is I/O and is not tested here. What is tested is the join
between a manifest row and a member inside the tarball, which is the step where
a mistake pairs the wrong audio with a transcript and poisons every number
downstream without anything looking broken.
"""

import numpy as np
import pytest
from src.fetch_audio import member_key, needed_tarballs, to_mono_16k


class TestMemberKey:
    def test_takes_the_last_two_path_components(self):
        # The manifest and the tarball agree on session directory and filename,
        # and disagree on everything before that.
        manifest_path = "/AfriSpeech-100/test/4f6beb7f-091c/fd0a2f6f55f3.wav"
        tar_member = "data/data/intron/4f6beb7f-091c/fd0a2f6f55f3.wav"
        assert member_key(manifest_path) == member_key(tar_member)

    def test_two_clips_sharing_a_basename_do_not_collide(self):
        # This is the real case: 46 basenames in the test split repeat across
        # session directories. The session directory is what separates them.
        first = member_key("/AfriSpeech-100/test/aaaa-1111/shared.wav")
        second = member_key("/AfriSpeech-100/test/bbbb-2222/shared.wav")
        assert first != second

    def test_is_insensitive_to_a_leading_slash(self):
        assert member_key("/a/b/c.wav") == member_key("a/b/c.wav")

    def test_appends_the_wav_suffix_when_the_manifest_omits_it(self):
        assert member_key("/x/session/clip") == member_key("data/session/clip.wav")

    def test_a_single_component_path_is_returned_as_is(self):
        assert member_key("clip.wav") == "clip.wav"


class TestNeededTarballs:
    def test_one_tarball_per_accent_and_split(self):
        rows = [
            {"accent": "igala", "split": "test"},
            {"accent": "igala", "split": "test"},
            {"accent": "yoruba", "split": "test"},
        ]
        assert needed_tarballs(rows) == [("igala", "test"), ("yoruba", "test")]

    def test_is_sorted_so_the_download_order_is_reproducible(self):
        rows = [
            {"accent": "zulu", "split": "test"},
            {"accent": "akan", "split": "test"},
        ]
        assert needed_tarballs(rows) == [("akan", "test"), ("zulu", "test")]

    def test_separates_the_same_accent_in_different_splits(self):
        rows = [
            {"accent": "igbo", "split": "test"},
            {"accent": "igbo", "split": "dev"},
        ]
        assert needed_tarballs(rows) == [("igbo", "dev"), ("igbo", "test")]


class TestToMono16k:
    def test_downmixes_stereo_to_mono(self):
        stereo = np.stack([np.ones(1000), np.zeros(1000)], axis=1)
        out = to_mono_16k(stereo, 16_000)
        assert out.ndim == 1
        assert np.allclose(out, 0.5)

    def test_leaves_mono_at_the_target_rate_alone(self):
        mono = np.linspace(-0.5, 0.5, 16_000, dtype=np.float64)
        assert np.allclose(to_mono_16k(mono, 16_000), mono)

    def test_resamples_down_to_the_target_rate(self):
        one_second_at_44100 = np.zeros(44_100)
        assert len(to_mono_16k(one_second_at_44100, 44_100)) == pytest.approx(
            16_000, abs=50
        )

    def test_preserves_duration_in_seconds(self):
        two_seconds = np.zeros(88_200)
        out = to_mono_16k(two_seconds, 44_100)
        assert len(out) / 16_000 == pytest.approx(2.0, abs=0.01)

    def test_keeps_a_tone_recognisable_after_resampling(self):
        # A 440 Hz tone must still be 440 Hz. A resampler that silently drops
        # or repeats samples would shift the pitch and change what the ASR hears.
        t = np.arange(44_100) / 44_100
        tone = np.sin(2 * np.pi * 440 * t)
        out = to_mono_16k(tone, 44_100)
        spectrum = np.abs(np.fft.rfft(out))
        peak_hz = np.fft.rfftfreq(len(out), 1 / 16_000)[np.argmax(spectrum)]
        assert peak_hz == pytest.approx(440, abs=5)

    def test_returns_float32_for_a_smaller_wav(self):
        assert to_mono_16k(np.zeros(16_000), 16_000).dtype == np.float32
