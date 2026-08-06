# Provider API notes

Six facts per provider, which is everything this project needs to call them.
Verified against the live APIs on 2026-08-06 with the project's own keys, not
from memory or from a model's training data. Where a fact came from a response
rather than a doc page, the observed response is quoted.

The scope here is deliberately narrow. ScribeCheck sends one 3-to-30-second
16 kHz mono WAV per request and reads plain verbatim text back. Nothing about
streaming, voice agents, summarisation, diarisation, redaction, webhooks or
browser integration is relevant, so none of it is recorded. AssemblyAI's own
integration guide runs to roughly 15,000 words; about 400 of them apply to us,
and they are below.

---

## Groq, Whisper large-v3

| | |
|---|---|
| Endpoint | `POST https://api.groq.com/openai/v1/audio/transcriptions` |
| Auth | `Authorization: Bearer <key>` |
| Model | `whisper-large-v3` in the `model` form field |
| Audio | `multipart/form-data`, field name `file`, ≤25 MB |
| Text at | `text` (top level) |
| Limits | 2,000 requests/day, 7,200 audio seconds/hour, free, no card |

Observed: `{"text":" Remains on ion and travisol.","x_groq":{"id":"req_..."}}`

The leading space on `text` is normal and the Whisper normalizer strips it.
OpenAI-compatible route, so the request shape is OpenAI's; the host is not.
This run is 400 requests and 4,290 audio seconds, inside both ceilings, so a
full pass fits in one hour. Expect 429s only if a pass is repeated quickly.

## Deepgram, nova-3 and nova-3-medical

| | |
|---|---|
| Endpoint | `POST https://api.deepgram.com/v1/listen?model=<model>&smart_format=false` |
| Auth | `Authorization: Token <key>` (the word `Token`, not `Bearer`) |
| Model | `nova-3` and `nova-3-medical`, in the query string |
| Audio | raw bytes as the request body, `Content-Type: audio/wav` |
| Text at | `results.channels[0].alternatives[0].transcript` |
| Limits | USD 200 signup credit; this run bills USD 1.10 against it |

`smart_format=false` matters. Left on, Deepgram rewrites numbers and units into
display form, which would change dosage strings before M3 ever sees them and
score the formatter rather than the recogniser.

Duration for billing comes back at `metadata.duration`, and `metadata.model_info`
names the exact model version that ran, which is worth recording in the writeup:
the medical model reported `medical-nova-3` version `2026-05-18.18466`.

## AssemblyAI, universal-3-5-pro

| | |
|---|---|
| Endpoint | `POST https://sync.assemblyai.com/transcribe` |
| Auth | `Authorization: <key>` **raw, no Bearer prefix** |
| Model | `universal-3-5-pro`, in an `X-AAI-Model` header |
| Audio | `multipart/form-data`, field name `audio`, 80 ms to 120 s, ≤40 MB |
| Text at | `text` (top level) |
| Limits | USD 50 signup credit; this run bills USD 0.25 against it |

Three things here are AssemblyAI-specific and each fails quietly rather than
loudly:

The Bearer prefix. Adding one returns 401, which reads like a bad key.

The model. On the async `/v2/transcript` route the model parameter is optional,
and omitting it makes the API choose its own default. Our first version omitted
it while `config.py` claimed `universal`, so the results would have recorded a
model that never ran. See DECISIONS D017.

The route. The async route is upload, then submit, then poll. Polling makes the
measured latency mostly our own sleep interval, so M5 would have compared a
stopwatch to a calendar. The sync route answers in one request and reports its
own `request_time_ms`, which is what we now record.

Observed: `{"text":"Remains on iron and trevisol.","words":[...],"confidence":0.72,
"audio_duration_ms":7280,"request_time_ms":348.3}`

## Google, gemini-3.6-flash

| | |
|---|---|
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` |
| Auth | `x-goog-api-key: <key>` |
| Model | `gemini-3.6-flash`, version `3.6-flash-07-2026`, in the URL path |
| Audio | base64 in `contents[0].parts[].inline_data.data` with `mime_type` |
| Text at | `candidates[0].content.parts[0].text` |
| Limits | free tier, per-account, not published; expect 429s across 400 clips |

The only configuration that is a general model rather than a speech model, so
it is the only one where the prompt steers the output. `config.GEMINI_PROMPT`
is `"Transcribe this audio verbatim."` and nothing else, per SPEC section 4.

`gemini-2.5-flash` returns 404 for accounts created now: *"no longer available
to new users"*. Model names here churn, so `GET /v1beta/models` is the check
before trusting any of them.

Slow relative to the rest: 16.9 s on a 5-second clip against 0.5 to 1.2 s for
the speech-specific models. Real, and it will show in M5.

A safety block returns a well-formed 200 with no `candidates` key, so the
absence of a candidate has to be handled as a failure rather than as an empty
transcript.

---

## What applies to all four

**Failures are not cached.** Only a successful transcript is written to
`data/cache/`, so a retry pass sees the failures again instead of skipping them
forever.

**Two exception types, and only two.** `RateLimited` for 429 and 5xx, which
backs off and retries; `TranscriptionFailed` for everything else, which logs and
moves on. Anything else escaping a transcriber ends the whole run, which is why
JSON parsing and every provider-reported number go through `_json` and
`_reported_number` rather than being trusted.

**Provider-reported duration beats our own.** Where a provider reports the audio
length it measured, that is what the cost is computed from, because that is what
the invoice will be based on. Deepgram and AssemblyAI both report it; Groq and
Gemini do not, so those fall back to reading the WAV header.
