"""Meeting mode (Phase 6) — both sides of the call, properly labelled.

Shape: dual capture (mic + sink monitor, SEPARATE channels) → energy
utterance segmentation per channel → batch-transcribe each utterance
(§3.6 post tier — the accurate pass, a few seconds after the call) →
channel diarization (You/Them) → merged, timestamped markdown note.
Optionally, pyannote refines single-channel multi-speaker sides.

Why per-utterance batch instead of Live here: meetings want the RECORD
(§3.6), diarization is post-pass by definition, and Live doesn't
diarize. Raw channel WAVs are always saved first (§3.5 rule).

Setup on Fedora (Step 3C) is the remaining manual piece:
`assist meeting setup` prints your nodes + the loopback plan; actual
capture sources are plain PipeWireCapture targets per channel.
"""

from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import asr
from .capture import write_wav
from .cost import iso_now
from .diarize import Turn, assign_speakers, format_transcript, merge_adjacent


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1, "mono s16 WAV expected"
        return wav.readframes(wav.getnframes()), wav.getframerate()


def segment_utterances(pcm: bytes, sample_rate: int, *, frame_ms: int = 50,
                       energy_threshold: float = 0.05,
                       min_silence_s: float = 0.6,
                       min_utterance_s: float = 0.35) -> list[tuple[float, float]]:
    """(start, end) speech ranges by RMS energy. Same family of gate as
    the §3.6 pre-roll VAD — local, deterministic, language-agnostic."""
    frame_samples = sample_rate * frame_ms // 1000
    frame_bytes = frame_samples * 2
    n_frames = len(pcm) // frame_bytes
    active = []
    for i in range(n_frames):
        chunk = pcm[i * frame_bytes:(i + 1) * frame_bytes]
        samples = struct.unpack(f"<{frame_samples}h", chunk)
        rms = (sum(s * s for s in samples) / max(1, len(samples))) ** 0.5 / 32768.0
        active.append(rms >= energy_threshold)
    silence_run = int(min_silence_s * 1000 // frame_ms)
    segments: list[tuple[int, int]] = []
    start: int | None = None
    quiet = 0
    for i, is_active in enumerate(active):
        if is_active:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet >= silence_run:
                segments.append((start, i - quiet + 1))
                start, quiet = None, 0
    if start is not None:
        segments.append((start, n_frames))
    sec = frame_ms / 1000.0
    return [(s * sec, e * sec) for s, e in segments
            if (e - s) * sec >= min_utterance_s]


def slice_wav(pcm: bytes, sample_rate: int, start_s: float, end_s: float,
              dest: Path) -> Path:
    begin = int(start_s * sample_rate) * 2
    end = int(end_s * sample_rate) * 2
    write_wav(dest, [pcm[begin:end]], sample_rate)
    return dest


@dataclass
class MeetingResult:
    note_path: Path
    mic_wav: Path
    system_wav: Path
    turns: list[Turn]
    transcript: str
    backend: str


class MeetingService:
    def __init__(self, config, store, client):
        self.config = config
        self.store = store
        self.client = client
        self.audio_dir = config.data_dir / "audio"
        self.inbox_dir = Path(config.section("transcribe").get(
            "inbox_dir", "~/.local/share/assistant/inbox")).expanduser()
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def _transcribe_channel(self, wav_path: Path, speaker: str,
                            work_dir: Path) -> list[Turn]:
        pcm, sample_rate = read_pcm(wav_path)
        segments = segment_utterances(pcm, sample_rate)
        turns: list[Turn] = []
        backend = asr.GeminiBatchBackend(self.client, self.config)
        language = asr.primary_language(self.config)
        for idx, (start, end) in enumerate(segments[:400]):  # sane ceiling
            piece = slice_wav(pcm, sample_rate, start, end,
                              work_dir / f"{speaker.lower()}-{idx:03d}.wav")
            transcript = backend.transcribe(str(piece), language)
            if transcript.text:
                turns.append(Turn(speaker=speaker, start_s=start, end_s=end,
                                  text=transcript.text))
        return turns

    def transcribe_dual(self, mic_wav: Path, system_wav: Path, *,
                        title: str | None = None,
                        pyannote_refine: bool = False) -> MeetingResult:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        mic_dest = self.audio_dir / f"meeting-{stamp}-mic.wav"
        sys_dest = self.audio_dir / f"meeting-{stamp}-system.wav"
        if mic_wav.resolve() != mic_dest.resolve():
            mic_dest.write_bytes(mic_wav.read_bytes())
            sys_dest.write_bytes(system_wav.read_bytes())
        work = self.config.data_dir / "meeting-work" / stamp
        work.mkdir(parents=True, exist_ok=True)

        turns = self._transcribe_channel(mic_dest, "You", work)
        turns += self._transcribe_channel(sys_dest, "Them", work)
        backend = "channel-diarization"

        if pyannote_refine:
            try:  # refine the far side only: the near side is one person
                from .diarize import PyannoteDiarizer

                speaker_turns = PyannoteDiarizer().diarize(sys_dest)
                far = [t for t in turns if t.speaker == "Them"]
                assign_speakers(far, speaker_turns)
                backend = "channel + pyannote (far side)"
            except RuntimeError as exc:
                backend = f"channel-diarization (pyannote unavailable: {exc})"

        turns = merge_adjacent(sorted(turns, key=lambda t: t.start_s))
        transcript = format_transcript(turns)
        note_path = self.inbox_dir / f"meeting-{stamp}.md"
        note_path.write_text(
            f"---\ncreated: {iso_now()}\ntype: meeting\ntitle: {title or 'Untitled call'}\n"
            f"diarization: {backend}\nmic: {mic_dest}\nsystem: {sys_dest}\n---\n\n"
            f"# {title or 'Meeting'} — {stamp}\n\n{transcript}\n",
            encoding="utf-8")
        raw = "\n".join(f"{t.speaker}: {t.text}" for t in turns)
        self.store.log_transcript(
            session_id=f"meeting-{stamp}", ts=iso_now(),
            language=",".join(self.config.section("asr").get("languages") or ["en"]),
            raw_text=raw, cleaned_text=raw, flagged=0,
            backend=f"meeting:{backend}",
            duration_s=max((t.end_s for t in turns), default=0.0),
            audio_path=str(mic_dest), inbox_path=str(note_path))
        return MeetingResult(note_path=note_path, mic_wav=mic_dest, system_wav=sys_dest,
                             turns=turns, transcript=transcript, backend=backend)


def meeting_setup_text(nodes: list[dict],
                       sink_monitor: str | None) -> str:
    """The Step-3C plan, printed not applied — creating PipeWire nodes is
    the user's call on their machine, rehearsed before a real call."""
    lines = ["MEETING CAPTURE SETUP (Fedora/Hyprland, Step 3C)", ""]
    lines.append("Discovered nodes:")
    for node in nodes:
        lines.append(f"  {node.get('id'):>4}  {node.get('name', ''):<50} {node.get('kind', '')}")
    lines += [
        "",
        "Meeting mode records TWO channels separately (labels stay exact):",
        "  mic    → your microphone node (config meeting.mic_target)",
        f"  system → {(sink_monitor or 'YOUR_SINK.monitor')} (config meeting.system_target)",
        "",
        "If you need a combined 'mix-mic' node instead (single Live stream),",
        "create it once and verify with pw-link -l:",
        "  pactl load-module module-loopback source=<sink>.monitor sink=mix-mic",
        "  pactl load-module module-loopback source=<mic> sink=mix-mic",
        "then confirm pw-record --target mix-mic hears both you and a test video.",
        "Rehearse with: assist meeting transcribe mic.wav sys.wav",
    ]
    return "\n".join(lines)
