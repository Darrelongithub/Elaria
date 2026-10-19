"""Phase 6 (§3.4/§12.4): meeting mode — dual channels, segmentation,
channel diarization, labelled transcripts, pyannote seam honesty.

Done-when under test: a call gets a proper labelled transcript. With
payments-mock batch the words are synthetic, but segmentation, labels,
ordering, merge and note-writing are all the real pipeline."""

import math
import struct

import pytest

from assistant.capture import mix_pcm, write_wav
from assistant.diarize import Turn, assign_speakers, format_transcript, merge_adjacent
from assistant.gemini_client import GeminiClient
from assistant.meeting import MeetingService, segment_utterances
from assistant.store import Store


def tone_pcm(seconds: float, rate: int = 16000, freq: int = 440, amp: int = 12000) -> bytes:
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate)))


def silence_pcm(seconds: float, rate: int = 16000) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


def test_mix_pcm_clamps_and_pads():
    loud = struct.pack("<2h", 30000, -30000)
    assert struct.unpack("<2h", mix_pcm(loud, loud)) == (32767, -32768)  # saturate
    assert len(mix_pcm(struct.pack("<1h", 5), loud)) == 4  # padded to longest


def test_segmentation_finds_speech_around_gaps():
    pcm = silence_pcm(0.5) + tone_pcm(0.8) + silence_pcm(1.2) + tone_pcm(0.9)
    segments = segment_utterances(pcm, 16000)
    assert len(segments) == 2
    assert segments[0][0] == pytest.approx(0.5, abs=0.15)
    assert segment_utterances(silence_pcm(2.0), 16000) == []


def test_dual_transcription_labels_and_orders(config, tmp_path):
    rate = 16000
    fb = rate * 20 // 1000 * 2  # 20ms mono s16 frames
    def frames_of(pcm):
        return [pcm[i:i + fb] for i in range(0, len(pcm) - fb + 1, fb)]

    mic = write_wav(tmp_path / "mic.wav",
                    frames_of(tone_pcm(0.8, freq=300) + silence_pcm(1.5)), rate)
    system = write_wav(tmp_path / "sys.wav",
                       frames_of(silence_pcm(1.2) + tone_pcm(0.8, freq=900)), rate)
    store = Store(tmp_path / "t.db")
    result = MeetingService(config, store, GeminiClient(config, store)).transcribe_dual(
        mic, system, title="Rehearsal call")
    speakers = [t.speaker for t in result.turns]
    assert speakers[0] == "You" and "Them" in speakers  # channels labelled exactly
    you_turn = next(t for t in result.turns if t.speaker == "You")
    them_turn = next(t for t in result.turns if t.speaker == "Them")
    assert you_turn.start_s < them_turn.start_s  # merged on one timeline
    note = result.note_path.read_text()
    assert "type: meeting" in note and "You:" in note and "Them:" in note
    assert "[00:" in result.transcript  # timestamps rendered
    transcript = store.recent_transcripts(1)[0]
    assert transcript["backend"].startswith("meeting:")  # record kept (§3.5)


def test_overlap_assignment_for_pyannote_turns():
    utterances = [Turn("Them", 0.0, 2.0, "hello"),
                  Turn("Them", 2.5, 4.0, "agreed"),
                  Turn("Them", 5.0, 6.0, "bye")]
    speakers = [Turn("SPEAKER_00", 0.0, 2.2), Turn("SPEAKER_01", 2.4, 6.5)]
    labelled = assign_speakers(utterances, speakers)
    assert [t.speaker for t in labelled] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]


def test_merge_adjacent_glues_breaths_not_people():
    turns = [Turn("You", 0.0, 1.0, "hi"), Turn("You", 1.4, 2.0, "there"),
             Turn("Them", 2.2, 3.0, "hello")]
    merged = merge_adjacent(turns)
    assert len(merged) == 2 and merged[0].text == "hi there"
    assert format_transcript(merged).count("\n") == 1


def test_pyannote_unavailable_is_an_honest_error():
    from assistant.diarize import PyannoteDiarizer
    with pytest.raises(RuntimeError, match="diarize|HF_TOKEN"):
        PyannoteDiarizer()


def test_daemon_meeting_round_trip(config, running_daemon):
    from assistant.ipc import call

    started = call(config.socket_path, "meeting.start", {"simulation": True},
                   timeout=15.0)
    assert started["state"] == "meeting"
    stopped = call(config.socket_path, "meeting.stop", {"title": "Sim call"},
                   timeout=120.0)
    assert stopped["state"] == "idle"
    assert stopped["backend"] == "channel-diarization"
    assert stopped["note_path"].endswith(".md")
