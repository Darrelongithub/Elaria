# Draft — Google bug report: Live transcribe models emit zero transcription output on a valid key (owner files this)

Status: **DRAFT for the owner to file** (work order W7c, 2026-10-31).
The builder drafted; the owner files. Attach the arm A transcript (the
script's output IS the evidence pack core) and dashboard screenshots
before filing.

## Title

gemini-3.5-transcribe-live accepts audio and bills input tokens but has
emitted zero transcription output across every session (valid API key,
Python SDK)

## Summary

Across roughly a week of sessions (2026-10-24 → 2026-10-31) on a valid
API key, the Live transcribe model accepts our audio stream, bills
input tokens (dashboard shows the audio token counts), and returns
setup_complete + voice-activity events — but has emitted ZERO
transcription-family messages (`input_transcription` /
`interim_input_transcription`) in every session and every repro run.

## Environment

- google-genai Python SDK (base install, `uv sync`), Python 3.11 (also
  reproduced shapes on 3.14) — happy to pin exact versions on request.
- Model: `gemini-3.5-transcribe-live` (also `models/gemini-3.5-transcribe-live-preview`).
- Region/account: [owner fills in — account type + region].
- API key: valid; other Gemini calls (generateContent chat/file) on the
  same key work and return output.

## Repro (verbatim-docs, minimal)

The repro uses the Live API docs' Manual-VAD Python example VERBATIM
(live-transcribe docs, "Manual VAD (Push-to-Talk)"), config:

```python
config = types.LiveConnectConfig(
    response_modalities=["TEXT"],
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            disabled=True
        )
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
)
```

Flow: `activity_start` → known-good 10.3 s speech wav streamed as
`audio/pcm;rate=16000` 100 ms chunks → `activity_end` → 30 s listen.

Observed (arm A transcript attached):

- connect + setup_complete: OK (session healthy, zero retries).
- voice-activity events: received, echoing at EXACT offsets of our
  speech (the server hears the audio).
- `server_content.input_transcription` / `interim_input_transcription`:
  **never received — zero messages of any transcription family**, across
  a 30 s post-audio listen window.
- wire message histograms show the sessions carried only
  voice-activity + generic counter messages; no transcription payloads.
- Dashboards (Oct 24–27): input audio tokens billed on these sessions.

## Expected

`input_transcription` messages (final, per docs) as speech completes —
or a documented reason they are withheld (quota gate, model
entitlement, region restriction).

## Asks

1. Is `gemini-3.5-transcribe-live` (and the -preview id) entitled/
   enabled for this API key / account tier / region?
2. Is there a known incident (Oct 24–31) with transcribe-live producing
   no `input_transcription` while billing input tokens?
3. If the side-channel on `gemini-3.8-live`
   (`input_audio_transcription` config) is now the recommended route for
   voice-input transcription, please confirm — we will re-pin.

## Attachments

- arm A raw transcript (verbatim messages, timestamps) —
  `scripts/live_repro.py --arm A` output.
- wire histograms per session (message types, setup_complete, activity
  offsets).
- dashboard screenshots showing billed input audio tokens (Oct 24–27).
- [after arm B] the `gemini-3.8-live` side-channel result (SPOKE or
  SILENT) as the comparison data point.
