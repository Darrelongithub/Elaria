"""Response-shape extraction fix (2026-11-03) — the ruled semantics.

Evidence: the owner-hardware diagnostic paste (2026-11-03T11:38:42+03:00,
HEAD be9183c) — `response.text` reported 0 chars while
`part.audio_transcription.text` held the full 44-character transcript in
the same response object. This file pins the fix's ruled semantics:

- read `part.text` AND `part.audio_transcription.text`, part-order join;
- a part carrying both fields is read ONCE and the collision is a
  RECORDED token ('text+audio_transcription'), never silent precedence;
- candidate[0] only;
- `language_code` is returned raw — None is "the model declared
  nothing", a third state that must stay visible, never agreement;
- `finished` is NOT load-bearing (None on a complete transcript);
- the probe shares the helper so instrument and production cannot
  diverge again.
[TESTED-ONLY] — S2's clean-audio run is the hardware confirmation.
"""

from __future__ import annotations

import asyncio

from assistant import asr
from assistant.gemini_client import extract_transcript


class _Transcript:
    def __init__(self, text=None, finished=None, language_code=None):
        self.text = text
        self.finished = finished
        self.language_code = language_code


class _Part:
    def __init__(self, text=None, audio_transcription=None, thought=False,
                 extra=None):
        self.text = text
        self.audio_transcription = audio_transcription
        self.thought = thought
        self._extra = extra or {}

    def model_dump(self, exclude=None):
        data = {"text": self.text, "thought": self.thought,
                "thought_signature": None,
                "audio_transcription": self.audio_transcription}
        data.update(self._extra)
        for key in (exclude or set()):
            data.pop(key, None)
        return data


class _Resp:
    def __init__(self, parts, text=None):
        content = type("C", (), {"parts": parts})()
        self.candidates = [type("K", (), {"content": content})()]
        self.text = text


# ------------------------------------------------------------- the helper
def test_text_only_parts_are_joined_in_part_order():
    resp = _Resp([_Part(text="one "), _Part(text="two")], text="one two")
    assert extract_transcript(resp) == ("one two", None, ["text", "text"])


def test_audio_transcription_parts_carry_the_answer():
    """The owner's clean-ref shape: response.text is '' and the answer is
    in part.audio_transcription.text."""
    resp = _Resp([_Part(audio_transcription=_Transcript(
        text="The quick brown fox jumps over the lazy dog."))], text=None)
    text, language, seen = extract_transcript(resp)
    assert text == "The quick brown fox jumps over the lazy dog."
    assert language is None, "the model declared nothing — raw absence"
    assert seen == ["audio_transcription"]


def test_parts_join_in_order_across_kinds():
    resp = _Resp([
        _Part(text="first"),
        _Part(audio_transcription=_Transcript(text="second")),
        _Part(text="third"),
    ])
    text, _language, seen = extract_transcript(resp)
    assert text == "first second third"
    assert seen == ["text", "audio_transcription", "text"]


def test_collision_is_read_once_and_recorded():
    """Ruling (a): audio_transcription.text wins, the part is read ONCE,
    and the collision is a recorded token — never silent precedence."""
    resp = _Resp([_Part(text="the text copy",
                        audio_transcription=_Transcript(text="the audio copy"))])
    text, _language, seen = extract_transcript(resp)
    assert text == "the audio copy"
    assert seen == ["text+audio_transcription"]


def test_collision_with_empty_audio_falls_to_text_once():
    """The one sub-case the ruling did not cover: audio present but
    empty, text readable — the part still contributes ONCE, from its
    readable content, and the collision stays recorded."""
    resp = _Resp([_Part(text="the only copy",
                        audio_transcription=_Transcript(text=None))])
    text, _language, seen = extract_transcript(resp)
    assert text == "the only copy"
    assert seen == ["text+audio_transcription"]


def test_language_code_is_returned_raw_when_declared():
    resp = _Resp([_Part(audio_transcription=_Transcript(
        text="habari", language_code="sw"))])
    text, language, _seen = extract_transcript(resp)
    assert (text, language) == ("habari", "sw")


def test_thought_parts_contribute_no_text_but_are_visible():
    resp = _Resp([_Part(text="thinking", thought=True),
                  _Part(text="answer")])
    text, _language, seen = extract_transcript(resp)
    assert text == "answer"
    assert "text+thought" in seen[0]


def test_other_part_types_are_named_not_ignored():
    resp = _Resp([_Part(extra={"function_call": {"name": "x"}})])
    text, _language, seen = extract_transcript(resp)
    assert text == ""
    assert "function_call" in seen[0], "unparsed needs the part types seen"


def test_no_candidates_and_empty_parts_are_honest():
    class _Empty:
        def __init__(self):
            self.candidates = []

    assert extract_transcript(_Empty()) == ("", None, [])
    assert extract_transcript(_Resp([])) == ("", None, [])


def test_no_parts_falls_back_to_the_response_text_accessor():
    """A response with no candidates/parts at all: the response-level
    `text` is the only readable source (the SDK's own fallback), and the
    mark names it as such — never pretending a part was read."""
    class _Bare:
        def __init__(self):
            self.text = "meeting transcript"

    assert extract_transcript(_Bare()) == ("meeting transcript", None,
                                           ["response.text"])


def test_parts_present_never_mask_an_empty_read_with_the_fallback():
    """The ruled semantics hold: when parts exist but read empty, we
    report empty — we never reach for the accessor that already failed."""
    resp = _Resp([_Part()], text="do not read me")
    assert extract_transcript(resp) == ("", None, ["empty"])


# ------------------------------------------------ the two wire call sites
class _FakeStore:
    def log_llm_call(self, **kwargs):
        return None


class _SdkFiles:
    def upload(self, *, file, config=None):
        return object()


class _SdkModels:
    def __init__(self, response):
        self._response = response

    def generate_content(self, *, model, contents, config=None):
        return self._response


def _live_client(response):
    from assistant.config import load_config
    from assistant.gemini_client import GeminiClient, _SdkTransport

    config = load_config()
    config.raw.setdefault("gemini", {})["model_default"] = \
        "gemini-3.5-flash-lite"
    client = GeminiClient(config, _FakeStore())
    # The wire seams short-circuit in mock mode (no key in the sandbox);
    # these tests exercise the live extraction path with a fake transport.
    client.mode = "live"
    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = type("S", (), {
        "files": _SdkFiles(), "models": _SdkModels(response)})()
    client._transport = transport
    return client


def _wav(tmp_path):
    import wave

    path = tmp_path / "x.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * 1600)
    return path


def test_sync_wire_extraction_feeds_the_result_dict(tmp_path):
    resp = _Resp([_Part(audio_transcription=_Transcript(
        text="forty four characters of answer here!!", language_code="en"))])
    client = _live_client(resp)
    text, language, seen = client._sdk_transcribe(
        _wav(tmp_path), "gemini-3.5-transcribe", "prompt", "corr", 1.0)
    assert text == "forty four characters of answer here!!"
    assert language == "en"
    assert seen == ["audio_transcription"]
    result = client.transcribe_batch(_wav(tmp_path), "en",
                                     model="gemini-3.5-transcribe")
    assert result["text"] == "forty four characters of answer here!!"
    assert result["language_code"] == "en"
    assert result["part_types_seen"] == ["audio_transcription"]


def test_async_wire_extraction_feeds_the_result_dict(tmp_path):
    class _AioModels:
        def __init__(self, response):
            self._response = response

        async def generate_content(self, *, model, contents, config=None):
            return self._response

    class _AioFiles:
        async def upload(self, *, file, config=None):
            return object()

    resp = _Resp([_Part(audio_transcription=_Transcript(text="spoken words"))])
    client = _live_client(resp)
    transport = client._transport
    transport._client = type("S", (), {
        "files": _AioFiles(),
        "models": _AioModels(resp),
        "aio": type("A", (), {"files": _AioFiles(),
                              "models": _AioModels(resp)})()})()
    result = asyncio.run(client.transcribe_batch_async(
        _wav(tmp_path), "en", model="gemini-3.5-transcribe"))
    assert result["text"] == "spoken words"
    assert result["language_code"] is None
    assert result["part_types_seen"] == ["audio_transcription"]


# ------------------------------------------------ ruling (b): language
class _DictClient:
    def __init__(self, result):
        self._result = result

    def transcribe_batch(self, audio_path, language, **kwargs):
        return self._result


def _backend(result):
    return asr.GeminiBatchBackend(_DictClient(result))


def test_language_none_takes_configured_and_stays_visible():
    """Amendment (b): the model declaring nothing is NOT a disagreement —
    Transcript.language takes the configured value and the absence is
    recorded (model_language=None), not silently reconciled."""
    transcript = _backend({
        "text": "words", "language_code": None,
        "part_types_seen": ["audio_transcription"]}).transcribe(
            "x.wav", "en")
    assert transcript.language == "en"
    assert transcript.model_language is None


def test_language_declared_feeds_transcript_and_marks_divergence(
        monkeypatch):
    result = {"text": "habari", "language_code": "sw",
              "part_types_seen": ["audio_transcription"]}
    transcript = _backend(result).transcribe("x.wav", "en")
    assert transcript.language == "sw", "the model's fact is emitted"
    assert transcript.model_language == "sw"

    # The walk marks the divergence through the BH-K19 machinery: the
    # model's value is emitted, the divergence is marked, never silent.
    from assistant.asr import transcribe_file

    class _Config:
        def section(self, name):
            return {"languages": ["en"], "assert_output_language": True}

    monkeypatch.setattr(asr, "batch_chain",
                        lambda *a, **k: [_backend(result)])
    walked = transcribe_file(_Config(), None, "x.wav", session_id="s1")
    assert walked.language == "sw"
    assert walked.model_language == "sw"
    assert walked.language_ok is False, "the divergence is marked"


def test_finished_is_not_load_bearing():
    """The hardware returned finished=None on a COMPLETE transcript — the
    fix never gates on it; completeness is whatever the populated fields
    carry."""
    resp = _Resp([_Part(audio_transcription=_Transcript(
        text="complete answer", finished=None))])
    text, _language, _seen = extract_transcript(resp)
    assert text == "complete answer"


# --------------------------------------------------- the probe shares it
def test_probe_raw_pass_uses_the_shared_helper():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / \
        "file_leg_probe.py"
    spec = importlib.util.spec_from_file_location("probe_under_test", script)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    resp = _Resp([_Part(audio_transcription=_Transcript(
        text="The quick brown fox jumps over the lazy dog."))], text=None)
    lines = []
    probe.raw_sdk_pass(type("S", (), {
        "files": _SdkFiles(), "models": _SdkModels(resp)})(),
        "gemini-3.5-transcribe", "prompt", "x.wav", printer=lines.append)
    out = "\n".join(lines)
    assert "raw model text (0 chars): ''" in out
    assert ("extracted transcript (44 chars, parts=['audio_transcription'], "
            "model_language=None)" in out)
    assert "audio_transcription.text (44 chars)" in out
    assert "the answer is in the part" in out, \
        "the reading line must not call an unread answer a stump"
