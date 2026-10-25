"""assist-voice-test — wake-word + voiceprint live test harness (§13.10).

Built FIRST, before the daemon (§9 build order): a standalone script that
proves "Elaria, in YOUR voice" works in your actual rooms before voice
activation is wired into anything.

    assist-voice-test run [--source synthetic|pipewire|wav:FILE]
      → mic opens LOCALLY, ring buffer only, nothing recorded or sent
      → keyword + voiceprint match → LED lights (terminal + Waybar state
        file) and the event is logged {time, keyword_score,
        speaker_score, latency_ms}
      → one-key labelling: f = "that was wrong" (false trigger),
        m = "that was me and it missed", q = quit
    assist-voice-test report
      → false triggers/hour · missed-keyword rate · speaker false-accepts
        · average/p95 latency · score distributions + suggested threshold
    assist-voice-test corpus-check --embeddings DIR
      → recompute ECAPA consistency from per-file embedding sidecars
        (validates the measured 0.96 baseline handling; aggregates only)

Privacy contract (§13.10): the ring buffer holds ~2s in memory and is
never written to disk. Event logs contain timestamps + scores only.
Near-miss clips are OFF by default (`save_near_miss_clips = false`) and
purge after 24h when enabled. voiceprint.json is a biometric template:
it lives outside the repo and is gitignored.

Honest limits: the harness (ring buffer, event log, LED, labelling,
report, threshold maths) is complete and dependency-free. The *models*
are pluggable backends — openWakeWord-class keyword spotting and
ECAPA embeddings need the `voice` extra on the Fedora machine and a
trained "Elaria" keyword model. Until then, --source synthetic and
embedding sidecars exercise every line of the harness except the neural
scorers, and the built-in energy scorer is labelled PLUMBING ONLY so it
can never be mistaken for keyword accuracy numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import struct
import subprocess
import tempfile
import time
import wave
from collections import deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .config import load_config, state_home

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
TARGETS = {"false_per_day": "<1", "deliberate_caught_pct": ">95%",
           "latency_ms": "<150ms wake→listening (§18)"}


# --------------------------------------------------------------------------
# Embedding maths (pure stdlib — 192-d ECAPA vectors need nothing heavier)
# --------------------------------------------------------------------------
def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise ValueError("cannot average zero embeddings")
    dim = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in mean)) or 1.0
    return [x / norm for x in mean]


def mean_pairwise_cosine(vectors: list[list[float]]) -> float:
    """Self-consistency — the number measured as 0.96 on the owner's corpus.

    Self-similarity ALONE cannot set an accept threshold (no impostors);
    thresholds come from the gap to impostor scores in the report (§13.10).
    """
    if len(vectors) < 2:
        return 1.0
    scores = [cosine(vectors[i], vectors[j])
              for i in range(len(vectors)) for j in range(i + 1, len(vectors))]
    return sum(scores) / len(scores)


# A biometric template is not a config file: it is only ever 0600 (§13.10).
BIOMETRIC_FILE_MODE = 0o600


def voiceprint_path(config) -> Path:
    """Where the speaker template lives — configurable, default `~/voiceprint.json`."""
    settings = config.section("voice_test") if config else {}
    return Path(str(settings.get("voiceprint_path") or "~/voiceprint.json")).expanduser()


def voiceprint_health(path: Path, *, expected_dimension: int | None = None,
                      expected_model: str | None = None) -> dict:
    """Is the speaker template usable, and stored like the biometric it is? (VB-9)

    `assist doctor` used to ask one question — does the file exist — and answer
    "ok" for a zero-byte file, a file that is not JSON, a centroid that does not
    match its own declared dimension, a template from a different model, or a copy
    the whole machine can read. Absent is still only a warning (enrolment is the
    user's call); anything present-but-wrong is a failure, because `load_voiceprint`
    would raise at the first real score and the user would meet that later, mid-
    sentence, with no explanation.
    """
    path = Path(path).expanduser()
    problems: list[str] = []
    if not path.exists():
        return {"state": "absent", "ok": True, "problems": [], "path": str(path),
                "detail": "absent — enrolment pending; `assist-voice-test enroll` builds it"}
    try:
        size = path.stat().st_size
    except OSError as exc:                        # unreadable path, broken link
        return {"state": "unusable", "ok": False, "problems": [f"cannot stat: {exc}"],
                "path": str(path), "detail": f"cannot be inspected: {exc}"}
    if size == 0:
        problems.append("the file is 0 bytes (a truncated or interrupted enrolment)")
    mode = path.stat().st_mode & 0o777
    if mode & ~BIOMETRIC_FILE_MODE:
        problems.append(f"permissions are 0{mode:o}, not 0{BIOMETRIC_FILE_MODE:o}: a "
                        f"biometric template must not be readable by group or others")
    data: dict = {}
    if not problems:                              # nothing worth parsing yet
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"not parseable JSON: {type(exc).__name__}: {exc}")
    if not problems and not isinstance(data, dict):
        problems.append(f"expected a JSON object, found {type(data).__name__}")
    if not problems:
        for key in ("model", "dimension", "centroid"):
            if key not in data:
                problems.append(f"missing '{key}'")
        centroid_ = data.get("centroid")
        if "centroid" in data:
            if not isinstance(centroid_, list) or not centroid_:
                problems.append("'centroid' is not a non-empty list of numbers")
                centroid_ = []
            else:
                try:
                    numbers = [float(v) for v in centroid_]
                except (TypeError, ValueError) as exc:
                    problems.append(f"'centroid' holds non-numeric values: {exc}")
                    numbers = []
                if numbers:
                    if not all(math.isfinite(v) for v in numbers):
                        problems.append("'centroid' contains a NaN or infinity")
                    declared = data.get("dimension")
                    if isinstance(declared, int) and len(numbers) != declared:
                        problems.append(f"centroid length {len(numbers)} != declared "
                                        f"dimension {declared}")
                    if expected_dimension and len(numbers) != int(expected_dimension):
                        problems.append(
                            f"template dimension {len(numbers)} does not match "
                            f"[voice_test] embedding_dim {int(expected_dimension)} — "
                            f"it was enrolled by a different model")
        model = data.get("model")
        if expected_model and model and str(model) != str(expected_model):
            problems.append(f"template model {model!r} != configured "
                            f"{expected_model!r}")
    state = "present" if not problems else "unusable"
    detail = (f"{path} — {len(data.get('centroid', []) or [])}-d vector from "
              f"{data.get('model', 'unknown model')}, mode 0{mode:o}")
    return {"state": state, "ok": not problems, "problems": problems, "path": str(path),
            "detail": detail if not problems else f"UNUSABLE: {'; '.join(problems)}"}


def load_voiceprint(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("model", "dimension", "centroid"):
        if key not in data:
            raise ValueError(f"{path} missing '{key}' — expected shape from "
                             "PROCESS-AUDIO-PROMPT.md deliverable B")
    if len(data["centroid"]) != int(data["dimension"]):
        raise ValueError(f"centroid len {len(data['centroid'])} != dimension "
                         f"{data['dimension']} in {path}")
    return data


def speaker_score(embedding: list[float], voiceprint: dict) -> float:
    return cosine(embedding, voiceprint["centroid"])


# --------------------------------------------------------------------------
# Audio ring buffer — processed locally, never stored (§13.10.1)
# --------------------------------------------------------------------------
class RingBuffer:
    """~2s of frames in memory. Anything older is discarded continuously."""

    def __init__(self, seconds: float = 2.0, frame_ms: int = FRAME_MS):
        self._frames: deque[bytes] = deque(maxlen=int(seconds * 1000 / frame_ms))
        self.seconds_held = seconds

    def push(self, frame: bytes) -> None:
        self._frames.append(frame)

    def snapshot(self) -> bytes:
        return b"".join(self._frames)

    def __len__(self) -> int:
        return len(self._frames)


# --------------------------------------------------------------------------
# Sources (frame iterators) and scorers (pluggable models)
# --------------------------------------------------------------------------
@dataclass
class ScoredEvent:
    """One detection moment — exactly what the log may contain, no audio."""

    ts: str
    keyword_score: float
    speaker_score: float | None
    latency_ms: float
    decision: str  # accepted | rejected-speaker | below-threshold
    label: str | None = None  # correct | false-trigger | missed-me (one-key)


class KeywordScorer(Protocol):
    name: str

    def score(self, pcm: bytes) -> float: ...


class EnergyScorer:
    """PLUMBING ONLY: loudness, not keyword spotting. Exists so the
    harness (LED/log/report) can be exercised before a trained 'Elaria'
    model does. Numbers from this scorer say NOTHING about accuracy."""

    name = "energy-stub-plumbing-only"

    def score(self, pcm: bytes) -> float:
        if len(pcm) < 2:
            return 0.0
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) - len(pcm) % 2])
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
        return min(1.0, rms * 4)


class OnnxKeywordScorer:
    """The harness adapter to the daemon's single ONNX keyword implementation.

    Optional `uv sync --extra voice` plus the owner's real .onnx model. The
    synthetic/energy plumbing harness still runs without either; it does not
    claim keyword accuracy. No openWakeWord/TFLite inference path remains.
    """

    name = "onnx"

    def __init__(self, model_path: str):
        from .wake_guard import OnnxKeywordModel

        self._model = OnnxKeywordModel.load(model_path)

    def score(self, pcm: bytes) -> float:
        return self._model.score_window(pcm)


class SyntheticSource:
    """Deterministic scripted detections — demos/tests on any machine.

    Emits (frame, forced_scores) via the detector's synthetic path:
    instead of audio, it yields markers the Runner interprets with
    seeded scores, so a full run→label→report cycle is reproducible.
    """

    def __init__(self, keyword_events: list[tuple[float, float]], seed: int = 7):
        # (keyword_score, speaker_score) per scripted event
        self.events = keyword_events
        self._rng = random.Random(seed)

    def frames(self) -> Iterator[bytes]:
        silence = b"\x00\x00" * FRAME_SAMPLES
        for _ in self.events:
            yield silence  # placeholder frame; scores come from the script


class WavSource:
    """Replay a WAV file frame-by-frame (offline corpus validation)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def frames(self) -> Iterator[bytes]:
        with wave.open(str(self.path), "rb") as wav:
            if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1:
                raise ValueError(f"{self.path}: need 16kHz mono WAV "
                                 f"(got {wav.getframerate()}Hz x{wav.getnchannels()})")
            while chunk := wav.readframes(FRAME_SAMPLES):
                yield chunk


class PipeWireSource:  # pragma: no cover - Fedora runtime only
    """Live mic via pw-record s16le PCM stdout (§3.4). Local only."""

    def __init__(self, target: str | None = None):
        from .capture import pw_record_pcm_stream_command, tool_available

        if not tool_available("pw-record"):
            raise RuntimeError("pw-record not found — live mic source needs the "
                               "Fedora target (pipewire-utils). Use "
                               "--source synthetic or wav:FILE here.")
        self._cmd = pw_record_pcm_stream_command(target)

    def frames(self) -> Iterator[bytes]:
        proc = subprocess.Popen(self._cmd, stdout=subprocess.PIPE)
        try:
            assert proc.stdout is not None
            while chunk := proc.stdout.read(FRAME_SAMPLES * 2):
                yield chunk
        finally:
            proc.terminate()


# --------------------------------------------------------------------------
# LED indicator — terminal + Waybar state file (+ optional notify-send)
# --------------------------------------------------------------------------
class LedIndicator:
    def __init__(self, state_path: Path, notify: bool = False):
        self.state_path = Path(state_path)
        self.notify = notify

    def set(self, lit: bool, event: ScoredEvent | None = None) -> dict:
        state = {
            # Waybar custom-module shape: text/class/tooltip (§3.9).
            "text": "● ELARIA" if lit else "○ elaria",
            "class": "voice-test-lit" if lit else "voice-test-idle",
            "tooltip": (f"keyword={event.keyword_score:.2f} "
                        f"speaker={event.speaker_score} "
                        f"latency={event.latency_ms:.0f}ms" if event else "listening…"),
            "lit": lit,
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        print(f"\r{'● LED ON ' if lit else '○ led off'} {state['tooltip']:60}", 
              end="" if not lit else "\n", flush=True)
        if lit and self.notify:  # pragma: no cover - desktop only
            subprocess.run(["notify-send", "Elaria voice-test",
                            "Keyword + voiceprint matched"], check=False)
        return state


# --------------------------------------------------------------------------
# Event log (scores + timestamps ONLY) and one-key labelling
# --------------------------------------------------------------------------
class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: ScoredEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event)) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def label_last(self, label: str) -> bool:
        """One-key labelling: mark the most recent event (f/m keys)."""
        events = self.read_all()
        if not events:
            return False
        events[-1]["label"] = label
        self.path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                             encoding="utf-8")
        return True


def purge_near_miss_clips(directory: Path, max_age_hours: float = 24.0,
                          now: float | None = None) -> int:
    """Near-miss clips (off by default) delete after 24h (§13.10)."""
    if not directory.exists():
        return 0
    cutoff = (now or time.time()) - max_age_hours * 3600
    removed = 0
    for clip in directory.glob("*.wav"):
        if clip.stat().st_mtime < cutoff:
            clip.unlink()
            removed += 1
    return removed


# --------------------------------------------------------------------------
# Runner: source → ring buffer → keyword → voiceprint → LED + log
# --------------------------------------------------------------------------
class Runner:
    def __init__(self, *, keyword_scorer: KeywordScorer,
                 voiceprint: dict | None,
                 embedding_of: callable | None = None,
                 keyword_threshold: float = 0.5,
                 speaker_threshold: float = 0.75,
                 log: EventLog, led: LedIndicator):
        self.keyword_scorer = keyword_scorer
        self.voiceprint = voiceprint
        self.embedding_of = embedding_of  # pcm -> embedding | None
        self.keyword_threshold = keyword_threshold
        self.speaker_threshold = speaker_threshold
        self.log = log
        self.led = led
        self.ring = RingBuffer(seconds=2.0)

    def process_frame(self, frame: bytes, *,
                      forced: tuple[float, float | None] | None = None) -> ScoredEvent | None:
        started = time.monotonic()
        self.ring.push(frame)
        if forced is not None:
            kw_score, spk_score = forced
        else:
            kw_score = self.keyword_scorer.score(self.ring.snapshot())
            spk_score = None
        if kw_score < self.keyword_threshold:
            return None  # ordinary speech/TV must NOT light up — and isn't logged
        if forced is None and self.voiceprint is not None and self.embedding_of:
            embedding = self.embedding_of(self.ring.snapshot())
            spk_score = speaker_score(embedding, self.voiceprint) if embedding else None
        accepted = spk_score is None or spk_score >= self.speaker_threshold
        event = ScoredEvent(
            ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
            keyword_score=round(kw_score, 4),
            speaker_score=round(spk_score, 4) if spk_score is not None else None,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            decision="accepted" if accepted else "rejected-speaker",
        )
        self.log.append(event)
        if accepted:
            self.led.set(True, event)
        return event

    def run_synthetic(self, source: SyntheticSource) -> list[ScoredEvent]:
        events = []
        for frame, scores in zip(source.frames(), source.events):
            event = self.process_frame(frame, forced=scores)
            if event:
                events.append(event)
        self.led.set(False)
        return events

    def run_live(self, source, key_reader=None) -> None:  # pragma: no cover - interactive
        print("Listening locally (ring buffer only, nothing recorded). "
              "Keys: f=false trigger, m=missed me, q=quit")
        self.led.set(False)
        for frame in source.frames():
            self.process_frame(frame)
            if key_reader:
                key = key_reader()
                if key == "f":
                    self.log.label_last("false-trigger")
                elif key == "m":
                    self.log.label_last("missed-me")
                elif key == "q":
                    break
        self.led.set(False)


def _tty_key_reader():  # pragma: no cover - interactive terminal only
    import select
    import sys
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def read():
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    return read, lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


# --------------------------------------------------------------------------
# Report — accuracy from labels + score distributions, threshold from data
# --------------------------------------------------------------------------
def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


def _histogram(values: list[float], buckets: int = 10) -> list[dict]:
    counts = [0] * buckets
    for value in values:
        counts[min(buckets - 1, max(0, int(value * buckets)))] += 1
    return [{"range": f"{i / buckets:.1f}-{(i + 1) / buckets:.1f}", "count": c}
            for i, c in enumerate(counts)]


def suggest_threshold(events: list[dict]) -> dict:
    """Threshold from the gap between TRUE scores and FALSE scores (§13.10):
    the owner's lowest genuine speaker scores vs the highest impostor
    scores — swept for best separation on labelled data. Self-consistency
    (0.96) alone can never set this; impostor data can."""
    true_scores = [e["speaker_score"] for e in events
                   if e.get("label") == "correct" and e.get("speaker_score") is not None]
    false_scores = [e["speaker_score"] for e in events
                    if e.get("label") == "false-trigger" and e.get("speaker_score") is not None]
    if not true_scores or not false_scores:
        return {"suggested": None,
                "reason": "insufficient labelled data — run the test in real life "
                          "(TV, other voices, tired morning voice) and label with "
                          "f/m keys. UNTUNED strict default stands meanwhile; "
                          "consistency 0.96 says strict is affordable, not where."}
    best_thresholds: list[float] = []
    best_errors: int | None = None
    for step in range(1001):
        threshold = step / 1000
        errors = (sum(1 for s in true_scores if s < threshold)
                  + sum(1 for s in false_scores if s >= threshold))
        if best_errors is None or errors < best_errors:
            best_thresholds = [threshold]
            best_errors = errors
        elif errors == best_errors:
            best_thresholds.append(threshold)
    best_threshold = round((best_thresholds[0] + best_thresholds[-1]) / 2, 4)
    return {
        "suggested": best_threshold,
        "separation_errors_at_suggestion": best_errors,
        "true_score_min": min(true_scores),
        "false_score_max": max(false_scores),
        "gap": round(min(true_scores) - max(false_scores), 4),
    }


def build_report(events: list[dict], *, window_hours: float | None = None) -> dict:
    if events:
        first = datetime.fromisoformat(events[0]["ts"])
        last = datetime.fromisoformat(events[-1]["ts"])
        span_h = max((last - first).total_seconds() / 3600, 1e-6)
    else:
        span_h = 0.0
    window = window_hours or span_h or 1.0
    accepted = [e for e in events if e["decision"] == "accepted"]
    false_triggers = [e for e in accepted if e.get("label") == "false-trigger"]
    missed = [e for e in events if e.get("label") == "missed-me"]
    correct = [e for e in accepted if e.get("label") == "correct"]
    rejected_speaker = [e for e in events if e["decision"] == "rejected-speaker"]
    latencies = [e["latency_ms"] for e in events]
    deliberate = len(correct) + len(missed)
    return {
        "events": len(events),
        "window_hours": round(window, 3),
        "accepted": len(accepted),
        "false_triggers": len(false_triggers),
        "false_triggers_per_hour": round(len(false_triggers) / window, 3),
        "false_triggers_per_day": round(len(false_triggers) / window * 24, 2),
        "missed_me": len(missed),
        "missed_keyword_rate": (round(len(missed) / deliberate, 4) if deliberate else None),
        "deliberate_caught_pct": (round(100 * len(correct) / deliberate, 1)
                                  if deliberate else None),
        "speaker_rejections": len(rejected_speaker),
        "speaker_false_accepts": len(false_triggers),  # accepted + labelled not-me
        "latency_ms_avg": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "latency_ms_p95": round(_percentile(latencies, 95), 2),
        "keyword_score_distribution": _histogram([e["keyword_score"] for e in events]),
        "speaker_score_distribution": _histogram(
            [e["speaker_score"] for e in events if e.get("speaker_score") is not None]),
        "threshold": suggest_threshold(events),
        "targets": TARGETS,
        "note": "Rates need labelled real-life data (f/m keys). Unlabelled "
                "accepted events count as neither correct nor false.",
    }


# --------------------------------------------------------------------------
# Corpus check — validate the measured baseline handling (aggregates only)
# --------------------------------------------------------------------------
def corpus_check(embeddings_dir: Path) -> dict:
    """Recompute voiceprint consistency from per-file ECAPA embedding
    sidecars ({file}.embedding.json: {"embedding": [...], "speech_seconds": n}).
    Content is never read — vectors and durations only (privacy rules)."""
    vectors, total_speech_s = [], 0.0
    for sidecar in sorted(Path(embeddings_dir).glob("*.embedding.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        vectors.append(data["embedding"])
        total_speech_s += float(data.get("speech_seconds", 0))
    if not vectors:
        raise ValueError(f"no *.embedding.json sidecars in {embeddings_dir}")
    return {
        "files": len(vectors),
        "dimension": len(vectors[0]),
        "mean_pairwise_cosine": round(mean_pairwise_cosine(vectors), 4),
        "negative_corpus_hours": round(total_speech_s / 3600, 2),
        "baseline_measured_oct_2026": {"consistency": 0.96, "corpus_hours": 3.90},
        "centroid_ready": True,
    }


def _write_voiceprint_atomic(out_path: Path, payload: bytes) -> None:
    """Publish a complete owner template with owner-only mode from creation (I5)."""
    out_path = Path(out_path)
    fd = None
    temporary = None
    try:
        fd, name = tempfile.mkstemp(
            prefix=f".{out_path.name}.", suffix=".tmp", dir=out_path.parent)
        temporary = Path(name)
        os.fchmod(fd, BIOMETRIC_FILE_MODE)
        handle = os.fdopen(fd, "wb")
        fd = None  # `handle` owns and closes the descriptor from here.
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, out_path)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def enroll(embeddings_dir: Path, out_path: Path, model: str) -> dict:
    """Build voiceprint.json (centroid) from embedding sidecars.

    Deliberate keyword samples (~20, varied tone/distance) are the
    positive set the corpus can't supply (§13.10); natural voice notes
    give the robust variance. Output stays OUT of git.
    """
    vectors, total_speech_s = [], 0.0
    for sidecar in sorted(Path(embeddings_dir).glob("*.embedding.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        vectors.append(data["embedding"])
        total_speech_s += float(data.get("speech_seconds", 0))
    centre = centroid(vectors)
    voiceprint = {
        "model": model,
        "dimension": len(centre),
        "centroid": centre,
        "mean_pairwise_cosine": round(mean_pairwise_cosine(vectors), 4),
        "file_count": len(vectors),
        "total_speech_seconds": total_speech_s,
    }
    payload = json.dumps(voiceprint, indent=2).encode("utf-8")
    # The private temp inode is complete before this atomic publish. No 0644
    # final path or half-written template is ever observable (I5 / VB-9).
    _write_voiceprint_atomic(out_path, payload)
    return {k: v for k, v in voiceprint.items() if k != "centroid"}


# --------------------------------------------------------------------------
def _paths(config) -> tuple[Path, Path]:
    state = state_home() / "assistant"
    return state / "voice-test-events.jsonl", state / "voice-test-led.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assist-voice-test",
        description="Wake-word ('Elaria') + voiceprint live test (§13.10). "
                    "Local only: nothing is recorded or sent anywhere.")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="listen and light the LED on match")
    run_p.add_argument("--source", default="synthetic",
                       help="synthetic | pipewire | wav:FILE (default synthetic)")
    run_p.add_argument("--voiceprint", help="path to voiceprint.json (out of git!)")
    run_p.add_argument("--notify", action="store_true", help="also notify-send on match")
    rep_p = sub.add_parser("report", help="accuracy report from the event log")
    rep_p.add_argument("--json", action="store_true")
    lab_p = sub.add_parser("label", help="label the last event (non-tty labelling)")
    lab_p.add_argument("label", choices=["correct", "false-trigger", "missed-me"])
    cc_p = sub.add_parser("corpus-check", help="consistency from embedding sidecars")
    cc_p.add_argument("--embeddings", required=True)
    en_p = sub.add_parser("enroll", help="build voiceprint.json from sidecars")
    en_p.add_argument("--embeddings", required=True)
    en_p.add_argument("--out", default="voiceprint.json")
    en_p.add_argument("--model", default="ECAPA-TDNN (VoxCeleb2, 192-d)")
    args = parser.parse_args(argv)

    config = load_config()
    settings = config.section("voice_test")
    log_path, led_path = _paths(config)

    if args.command == "report":
        report = build_report(EventLog(log_path).read_all())
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Events: {report['events']} over {report['window_hours']}h · "
                  f"accepted {report['accepted']} · speaker rejections {report['speaker_rejections']}")
            print(f"False triggers: {report['false_triggers']} "
                  f"({report['false_triggers_per_day']}/day, target {TARGETS['false_per_day']})")
            print(f"Deliberate caught: {report['deliberate_caught_pct']}% "
                  f"(target {TARGETS['deliberate_caught_pct']}) · missed rate {report['missed_keyword_rate']}")
            print(f"Latency: avg {report['latency_ms_avg']}ms, p95 {report['latency_ms_p95']}ms "
                  f"(budget {TARGETS['latency_ms']})")
            print(f"Threshold: {json.dumps(report['threshold'])}")
            print(report["note"])
        return 0

    if args.command == "label":
        ok = EventLog(log_path).label_last(args.label)
        print("labelled" if ok else "no events to label")
        return 0 if ok else 1

    if args.command == "corpus-check":
        print(json.dumps(corpus_check(Path(args.embeddings)), indent=2))
        return 0

    if args.command == "enroll":
        summary = enroll(Path(args.embeddings), Path(args.out), args.model)
        print(json.dumps(summary, indent=2))
        print("Reminder: voiceprint.json is a biometric template — keep it "
              "out of git and out of any public repo (§13.10).")
        return 0

    # run
    purge_near_miss_clips(state_home() / "assistant" / "near-miss")
    voiceprint = load_voiceprint(Path(args.voiceprint)) if args.voiceprint else None
    runner = Runner(
        keyword_scorer=EnergyScorer(),
        voiceprint=voiceprint,
        keyword_threshold=float(settings.get("keyword_threshold", 0.5)),
        speaker_threshold=float(settings.get("speaker_threshold", 0.75)),
        log=EventLog(log_path),
        led=LedIndicator(led_path, notify=args.notify),
    )
    if args.source == "synthetic":
        demo = SyntheticSource(keyword_events=[
            (0.92, 0.97),   # owner says Elaria → LED
            (0.88, 0.41),   # someone else / TV → speaker rejected
            (0.20, 0.99),   # owner talking normally → no trigger, no log noise
            (0.95, 0.93),   # owner again → LED
        ])
        events = runner.run_synthetic(demo)
        print(f"\nsynthetic run complete: {len(events)} logged event(s) in {log_path}")
        print("Label them (`assist-voice-test label correct|false-trigger|missed-me`) "
              "then `assist-voice-test report`.")
        return 0
    if args.source == "pipewire":  # pragma: no cover - Fedora interactive
        read_key, restore = _tty_key_reader()
        try:
            runner.run_live(PipeWireSource(), key_reader=read_key)
        finally:
            restore()
        return 0
    if args.source.startswith("wav:"):
        source = WavSource(Path(args.source[4:]))
        found = [e for frame in source.frames() if (e := runner.process_frame(frame))]
        runner.led.set(False)
        print(f"\nwav replay complete: {len(found)} event(s) logged "
              f"(EnergyScorer = plumbing only, not keyword accuracy)")
        return 0
    parser.error(f"unknown --source {args.source!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
