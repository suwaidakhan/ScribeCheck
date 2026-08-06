"""Transcription orchestration: caching, retry, cost accounting, spend cap.

No provider is called here. The orchestrator takes its transcriber as an
argument so the network can be replaced by a stub, and the stub asserts on what
it receives. A double that quietly ignores its arguments would let every test
pass while the real call site sends the wrong file.

What is deliberately not faked: the cache is written to and read from a real
temporary directory, because "did it skip the cached clip" is a question about
files on disk, and a fake cache would be testing itself.
"""

import json

import pandas as pd
import pytest
from src import config, transcribe
from src.transcribe import (
    RateLimited,
    TranscriptionFailed,
    cached_path,
    project_cost,
    run_provider,
)


@pytest.fixture
def manifest():
    return pd.DataFrame(
        {
            "clip_id": ["c1", "c2", "c3"],
            "duration": [10.0, 20.0, 30.0],
            "accent": ["yoruba", "igbo", "twi"],
            "tier": ["A", "A", "B"],
            "domain": ["clinical", "clinical", "general"],
        }
    )


@pytest.fixture
def audio_dir(tmp_path):
    directory = tmp_path / "audio"
    directory.mkdir()
    for clip_id in ["c1", "c2", "c3"]:
        (directory / f"{clip_id}.wav").write_bytes(b"RIFF-fake-wav")
    return directory


class Recorder:
    """A stub transcriber that records exactly what it was asked to do."""

    def __init__(self, text="hello world", fail_on=(), rate_limit_on=()):
        self.calls: list[tuple[str, str]] = []
        self.text = text
        self.fail_on = set(fail_on)
        self.rate_limit_on = set(rate_limit_on)
        self.rate_limited_once: set[str] = set()

    def __call__(self, audio_path, provider_id):
        clip_id = audio_path.stem
        self.calls.append((clip_id, provider_id))
        if clip_id in self.rate_limit_on and clip_id not in self.rate_limited_once:
            self.rate_limited_once.add(clip_id)
            raise RateLimited("slow down")
        if clip_id in self.fail_on:
            raise TranscriptionFailed("provider said no")
        return {"text": f"{self.text} {clip_id}", "latency_ms": 123, "cost_usd": 0.01}

    @property
    def clip_ids(self):
        return [clip for clip, _ in self.calls]


class TestProjectCost:
    def test_multiplies_audio_minutes_by_list_price(self, manifest):
        # 60 seconds of audio at USD 0.0077 per minute.
        assert project_cost(manifest, "dg-general") == pytest.approx(0.0077)

    def test_a_free_tier_provider_projects_zero(self, manifest):
        assert project_cost(manifest, "gemini") == 0.0

    def test_the_whisper_slot_is_free_now_that_groq_hosts_it(self, manifest):
        # Was USD 0.006/min at OpenAI. See DECISIONS D016.
        assert project_cost(manifest, "whisper") == 0.0

    def test_scales_with_the_number_of_clips(self, manifest):
        doubled = pd.concat([manifest, manifest], ignore_index=True)
        assert project_cost(doubled, "dg-general") == pytest.approx(
            2 * project_cost(manifest, "dg-general")
        )


class TestRunProvider:
    def test_writes_one_cache_file_per_clip(self, manifest, audio_dir, tmp_path):
        run_provider("whisper", manifest, Recorder(), audio_dir, tmp_path)
        for clip_id in ["c1", "c2", "c3"]:
            assert cached_path("whisper", clip_id, tmp_path).exists()

    def test_cache_holds_what_the_provider_returned(
        self, manifest, audio_dir, tmp_path
    ):
        run_provider("whisper", manifest, Recorder(text="mango"), audio_dir, tmp_path)
        cached = json.loads(cached_path("whisper", "c2", tmp_path).read_text())
        assert cached["text"] == "mango c2"
        assert cached["latency_ms"] == 123
        assert cached["audio_seconds"] == 20.0

    def test_sends_each_clip_its_own_audio_file(self, manifest, audio_dir, tmp_path):
        # The bug this catches: sending the same file for every clip, which
        # produces a full cache, plausible transcripts and meaningless numbers.
        recorder = Recorder()
        run_provider("whisper", manifest, recorder, audio_dir, tmp_path)
        assert sorted(recorder.clip_ids) == ["c1", "c2", "c3"]

    def test_passes_the_provider_id_through(self, manifest, audio_dir, tmp_path):
        recorder = Recorder()
        run_provider("dg-medical", manifest, recorder, audio_dir, tmp_path)
        assert {provider for _, provider in recorder.calls} == {"dg-medical"}

    def test_never_recalls_a_cached_clip(self, manifest, audio_dir, tmp_path):
        first = Recorder()
        run_provider("whisper", manifest, first, audio_dir, tmp_path)
        second = Recorder()
        run_provider("whisper", manifest, second, audio_dir, tmp_path)
        assert second.calls == []

    def test_resumes_a_partial_run(self, manifest, audio_dir, tmp_path):
        run_provider("whisper", manifest.head(1), Recorder(), audio_dir, tmp_path)
        recorder = Recorder()
        run_provider("whisper", manifest, recorder, audio_dir, tmp_path)
        assert sorted(recorder.clip_ids) == ["c2", "c3"]

    def test_one_failure_does_not_stop_the_run(self, manifest, audio_dir, tmp_path):
        summary = run_provider(
            "whisper", manifest, Recorder(fail_on=["c2"]), audio_dir, tmp_path
        )
        assert summary["clips_ok"] == 2
        assert summary["clips_failed"] == 1
        assert cached_path("whisper", "c3", tmp_path).exists()

    def test_a_failed_clip_is_not_cached(self, manifest, audio_dir, tmp_path):
        # Caching a failure would make the retry pass silently skip it forever.
        run_provider("whisper", manifest, Recorder(fail_on=["c2"]), audio_dir, tmp_path)
        assert not cached_path("whisper", "c2", tmp_path).exists()

    def test_a_rate_limit_backs_off_and_retries(self, manifest, audio_dir, tmp_path):
        recorder = Recorder(rate_limit_on=["c2"])
        summary = run_provider("whisper", manifest, recorder, audio_dir, tmp_path)
        assert summary["clips_ok"] == 3
        assert recorder.clip_ids.count("c2") == 2

    def test_sums_cost_across_clips(self, manifest, audio_dir, tmp_path):
        summary = run_provider("whisper", manifest, Recorder(), audio_dir, tmp_path)
        assert summary["cost_usd"] == pytest.approx(0.03)

    def test_reports_median_latency(self, manifest, audio_dir, tmp_path):
        summary = run_provider("whisper", manifest, Recorder(), audio_dir, tmp_path)
        assert summary["median_latency_ms"] == 123

    def test_stops_before_passing_the_spend_cap(self, manifest, audio_dir, tmp_path):
        # Each clip costs 0.01. A cap of 0.015 allows one and must refuse the rest
        # rather than discovering the overspend after the fact.
        summary = run_provider(
            "whisper", manifest, Recorder(), audio_dir, tmp_path, spend_cap=0.015
        )
        assert summary["cost_usd"] <= 0.015
        assert summary["clips_ok"] < 3
        assert summary["stopped_on_cap"] is True

    def test_skips_a_clip_whose_audio_is_missing(self, manifest, audio_dir, tmp_path):
        (audio_dir / "c2.wav").unlink()
        recorder = Recorder()
        summary = run_provider("whisper", manifest, recorder, audio_dir, tmp_path)
        assert "c2" not in recorder.clip_ids
        assert summary["clips_failed"] == 1

    def test_summary_names_the_provider_and_model(self, manifest, audio_dir, tmp_path):
        summary = run_provider("dg-medical", manifest, Recorder(), audio_dir, tmp_path)
        assert summary["provider"] == "dg-medical"
        assert summary["model"] == "nova-3-medical"


class TestGroqTranscriber:
    """The free replacement for the paid OpenAI slot.

    Groq serves OpenAI's Whisper model on an OpenAI-compatible endpoint, so the
    request shape is nearly identical and the easy mistake is leaving it pointed
    at api.openai.com, where the same key would simply 401. These assert on the
    arguments actually sent rather than on a return value a stub could fake.
    """

    def _capture(self, monkeypatch, payload=None, status=200):
        sent = {}

        class Response:
            status_code = status
            ok = status < 400
            text = ""

            def json(self):
                return payload if payload is not None else {"text": "hello"}

        def fake_post(url, **kwargs):
            sent["url"] = url
            sent.update(kwargs)
            return Response()

        monkeypatch.setattr(transcribe.requests, "post", fake_post)
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        return sent

    def test_calls_groq_and_not_openai(self, monkeypatch, audio_dir):
        sent = self._capture(monkeypatch)
        transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
        assert sent["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
        assert "openai.com" not in sent["url"]

    def test_sends_the_configured_model(self, monkeypatch, audio_dir):
        sent = self._capture(monkeypatch)
        transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
        assert sent["data"]["model"] == config.PROVIDERS["whisper"]["model"]

    def test_authenticates_with_a_bearer_token(self, monkeypatch, audio_dir):
        sent = self._capture(monkeypatch)
        transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
        assert sent["headers"]["Authorization"] == "Bearer test-key"

    def test_returns_the_transcribed_text(self, monkeypatch, audio_dir):
        self._capture(monkeypatch, payload={"text": "takes metformin daily"})
        result = transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
        assert result["text"] == "takes metformin daily"

    def test_costs_nothing_because_the_tier_is_free(self, monkeypatch, audio_dir):
        self._capture(monkeypatch)
        result = transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
        assert result["cost_usd"] == 0.0

    def test_a_missing_key_fails_before_any_request(self, monkeypatch, audio_dir):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        def explode(*args, **kwargs):
            raise AssertionError("called the API without a key")

        monkeypatch.setattr(transcribe.requests, "post", explode)
        with pytest.raises(transcribe.TranscriptionFailed):
            transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")

    def test_a_rate_limit_is_retryable_rather_than_fatal(self, monkeypatch, audio_dir):
        # Groq's free tier is capped per hour, so 429 is expected traffic here,
        # not an error. It must reach the orchestrator's backoff.
        self._capture(monkeypatch, status=429)
        with pytest.raises(transcribe.RateLimited):
            transcribe.transcribe_groq(audio_dir / "c1.wav", "whisper")
