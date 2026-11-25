#!/usr/bin/env python3
"""Train the "Elaria" wake head for `wake_guard.OpenWakeWordModel`  (lane J).

    python3 scripts/train_elaria_head.py --out models/elaria_head.onnx \
        --fixture tests/fixtures/j_elaria_head_holdout.npz \
        --report-json /tmp/elaria_head_numbers.json

WHAT THIS PRODUCES
    A small ONNX classifier head with fixed input ``[1, 4, 96]`` — the last
    four speech embeddings of a window, exactly the tensor
    `OpenWakeWordModel.head_inputs` hands to a head at the default
    ``[hotword] keyword_window_s = 1.0``. It sits ON TOP of the two
    openWakeWord feature models (``melspectrogram.onnx`` +
    ``embedding_model.onnx``); it does not replace them.

WHY IT IS BUILT THIS WAY
    * The trainer does NOT re-implement feature extraction. Every clip goes
      through ``OpenWakeWordModel.embedding_frames`` — the same object, the
      same ``x/10 + 2`` melspec transform, the same 76-frame/step-8 windows
      the daemon uses. A head fitted on a second extractor is a green test
      over a dead product.
    * Training is plain numpy (a 2-hidden-layer MLP, Adam, BCE) so the repo
      gains no PyTorch/sklearn dependency it does not ship.
    * All audio is synthetic: espeak-ng (via ``espeakng-loader``) speaks the
      phrase and the negatives. **No real human "Elaria" audio exists in this
      environment, so no real-voice recall is claimed here** — the
      pre-committed Stage-A bars in `docs/hotword-training-plan.md` are
      measured on the owner's ~120-take corpus, not this file.
    * ``[hotword] keyword_threshold`` is NOT touched. It stays 0.5. The
      numbers below are reported at that frozen threshold, so a weak head
      shows up as a weak number instead of being tuned away.

EVALUATION PROTOCOL (pre-committed before any training run)
    * Voices are split train / val / test by *voice variant*, never by clip:
      no voice used to fit the head appears in either report set.
    * Val drives early stopping; the test split is scored once.
    * Headline numbers: false-accept rate on held-out negatives and
      false-reject rate on held-out positives, both at 0.5, plus the same
      broken down by negative class (`near` is the hard one).
    * ``--fixture`` writes a small held-out npz (test-split voices only) that
      carries the clips, the runtime embeddings produced for them, and the
      labels, so `tests/test_j_elaria_head.py` can check the shipped file off
      this machine.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assistant.wake_guard import OpenWakeWordModel

SR_SYNTH = 22050          # espeak-ng default output rate
SR_PCM = 16000            # the daemon's capture rate
HEAD_FRAMES = 4           # -> keyword_window_s 1.0 -> 4 embedding windows
WINDOW_S = 1.0            # the runtime's default trailing keyword window
FROZEN_THRESHOLD = 0.5    # [hotword] keyword_threshold — never lowered

# One seed for everything; the recipe is reproducible or it is not a recipe.
SEED = 93

# ---------------------------------------------------------------------------
# espeak-ng (synthesis only — never used by the daemon at runtime)
# ---------------------------------------------------------------------------
_ESPEAK = {"lib": None, "sr": None, "chunks": []}


class SynthUnavailable(RuntimeError):
    pass


def _synth_cb(wav, n, events):  # pragma: no cover - ctypes callback
    if n > 0:
        _ESPEAK["chunks"].append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
    return 0


def espeak_init():
    if _ESPEAK["lib"] is not None:
        return _ESPEAK["lib"]
    try:
        import espeakng_loader
    except ImportError as exc:
        raise SynthUnavailable(
            "espeak-ng is unavailable: `pip install espeakng-loader` in the "
            "TRAINING environment (it is not a daemon dependency)") from exc
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    lib.espeak_Initialize.restype = ctypes.c_int
    sr = lib.espeak_Initialize(2, 0, espeakng_loader.get_data_path().encode(), 0)
    if sr <= 0:
        raise SynthUnavailable("espeak-ng failed to initialise (no data path)")
    cb_type = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    cb = cb_type(_synth_cb)                       # keep the ref alive
    lib.espeak_SetSynthCallback.argtypes = [cb_type]
    lib.espeak_SetSynthCallback(cb)
    lib.espeak_Synth.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint),
        ctypes.c_void_p, ctypes.c_void_p]
    lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    lib.espeak_SetVoiceByName.restype = ctypes.c_int
    _ESPEAK.update(lib=lib, sr=sr, cb=cb)
    return lib


ACCENTS = ("en", "en-us", "en-gb")


def espeak_voices():
    """The `!v` variant voices on all three English accents: ~200 timbres.

    The voice, not the clip, is the unit that gets split — so nothing here
    shares a timbre with anything in the report sets.
    """
    import espeakng_loader

    base = Path(espeakng_loader.get_data_path()) / "voices" / "!v"
    names = sorted(p.name for p in base.iterdir()) if base.is_dir() else []
    lib = espeak_init()
    ok = []
    for accent in ACCENTS:
        for name in names:
            if lib.espeak_SetVoiceByName(f"{accent}+{name}".encode()) == 0:
                ok.append(f"{accent}+{name}")
    if not ok:
        raise SynthUnavailable(f"no usable espeak en variants under {base}")
    return ok


def deterministic_voices(voices):
    """Keep only voices whose synthesis is byte-stable in this espeak build.

    Most variant voices (`en+Annie`, `en+Demonic`, ...) mix in a random breath
    component, so two runs produce different PCM and therefore a different
    head. Voices that synthesise identically twice give a run whose artefacts
    are byte-reproducible; the recipe is worth more than 170 extra timbres.
    """
    stable = []
    for voice in voices:
        try:
            first = say("Elaria", voice, 160, 50, 100)
            second = say("Elaria", voice, 160, 50, 100)
        except SynthUnavailable:
            continue
        if first.shape == second.shape and np.array_equal(first, second):
            stable.append(voice)
    return stable


def say(text, voice, rate, pitch, amplitude):
    """Synthesize one utterance -> float32 mono at SR_SYNTH."""
    lib = espeak_init()
    if lib.espeak_SetVoiceByName(voice.encode()) != 0:
        raise SynthUnavailable(f"unknown espeak voice {voice!r}")
    lib.espeak_SetParameter(1, int(rate), 0)        # speed (words/min)
    lib.espeak_SetParameter(3, int(pitch), 0)       # pitch 0..99
    lib.espeak_SetParameter(2, int(amplitude), 0)   # amplitude 0..200
    _ESPEAK["chunks"] = []
    raw = text.encode()
    rc = lib.espeak_Synth(raw, len(raw) + 1, 0, 1, 0, 0, None, None, None)
    if rc != 0:
        raise SynthUnavailable(f"espeak_Synth failed ({rc}) for {text!r}")
    chunks = _ESPEAK["chunks"]
    if not chunks:
        raise SynthUnavailable(f"espeak produced no audio for {text!r}")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def resample(x, sr_in, sr_out):
    """Frequency-domain resample (numpy only, no aliasing on rate changes)."""
    if sr_in == sr_out:
        return x.astype(np.float32)
    n_out = round(len(x) * sr_out / sr_in)
    if n_out <= 0:
        return np.zeros(0, np.float32)
    spec = np.fft.rfft(x)
    m = n_out // 2 + 1
    if m <= spec.size:
        spec = spec[:m]
    else:
        spec = np.concatenate([spec, np.zeros(m - spec.size, spec.dtype)])
    return (np.fft.irfft(spec, n_out) * (n_out / len(x))).astype(np.float32)


# ---------------------------------------------------------------------------
# synthetic sound beds — the noise/hard-negative material
# ---------------------------------------------------------------------------
def pink(n, rng):
    """1/f noise via spectral shaping — a decent room-tone stand-in."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR_PCM)
    f[0] = f[1] if len(f) > 1 else 1.0
    out = np.fft.irfft(spec / np.sqrt(f), n)
    return (out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def room_tone(n, rng):
    """Pink noise + mains hum + a couple of keyboard-ish clicks."""
    bed = pink(n, rng) * 0.7
    t = np.arange(n) / SR_PCM
    bed += 0.05 * np.sin(2 * np.pi * 50 * t + rng.uniform(0, 6.3))
    bed += 0.03 * np.sin(2 * np.pi * 100 * t + rng.uniform(0, 6.3))
    for _ in range(int(rng.integers(0, 4))):
        at = int(rng.integers(0, max(1, n - 400)))
        span = min(400, n - at)
        click = rng.standard_normal(span) * np.linspace(1, 0, span)
        bed[at:at + span] += 0.25 * click
    return (bed / (np.max(np.abs(bed)) + 1e-9)).astype(np.float32)


def music_bed(n, rng):
    """A crude harmonic "radio in the next room" — music is a classic FA source."""
    t = np.arange(n) / SR_PCM
    root = rng.uniform(110, 330)
    out = np.zeros(n, np.float32)
    for k in range(1, 6):
        out += (1.0 / k) * np.sin(2 * np.pi * root * k * t + rng.uniform(0, 6.3))
    out *= 0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(1.0, 4.0) * t)
    return (out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def babble(n, rng, voice_pool, sentences):
    """Overlapping other-speaker speech — the hardest realistic negative."""
    out = np.zeros(n, np.float32)
    for _ in range(int(rng.integers(2, 4))):
        v = voice_pool[int(rng.integers(0, len(voice_pool)))]
        clip = utter(rng, sentences[int(rng.integers(0, len(sentences)))], v,
                     rate=(140, 200), pitch=(25, 70), amp=(70, 120))
        if clip.size == 0:
            continue
        at = int(rng.integers(0, max(1, n - clip.size))) if clip.size < n else 0
        seg = clip[: max(1, n - at)]
        out[at:at + seg.size] += seg
    return (out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def mix(speech, bed, snr_db):
    """Mix a speech clip into a bed at a target SNR (RMS ratio)."""
    if speech.size == 0:
        return bed
    s_rms = float(np.sqrt(np.mean(speech ** 2)) + 1e-9)
    b_rms = float(np.sqrt(np.mean(bed ** 2)) + 1e-9)
    return (speech + bed * (s_rms / (10 ** (snr_db / 20.0)) / b_rms)).astype(np.float32)


def to_pcm16(x, peak_dbfs=-3.0):
    """float32 -> s16le bytes at a controlled peak level."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0:
        x = x * (10 ** (peak_dbfs / 20.0) / peak)
    if np.max(np.abs(x)) > 1.0:                     # pragma: no cover - clip guard
        x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype("<i2").tobytes()


# ---------------------------------------------------------------------------
# phrase material
# ---------------------------------------------------------------------------
POSITIVE_TEXTS = ["Elaria", "Elaria", "Elaria", "hey Elaria", "hi Elaria",
                  "okay Elaria", "Elaria,"]

# Near-words are the point of the exercise: "malaria" and "Elaria" differ by
# one phoneme, so a head that only learns the ending will eat the room.
NEAR_WORDS = ["malaria", "Larry", "hilary", "area", "scenario", "Aaliyah",
              "Ilaria", "Elena", "Maria", "lariat", "alarm", "Arya",
              "el area", "la ria", "Alicia", "Alaria", "Valeria", "Zaria",
              "Amelia", "Alexa"]
# The `-aria` tail is the trap: dozens of English words and names end in it,
# and each one is a false-accept waiting to happen on an unseen voice.
NEAR_ARIA = ["Maria", "Aria", "Zaria", "Daria", "Sofia", "Lucia", "Victoria",
             "Gloria", "Marina", "Karina", "Sabrina", "Anastasia", "Julia",
             "Olivia", "Amelia", "Cecilia", "Natalia", "Camila", "Adriana",
             "Eliana", "Juliana", "Liliana", "Ana Maria", "Santa Maria"]

NEAR_SENTENCES = [
    "The malaria outbreak spread across the region.",
    "That area of the house is always cold.",
    "I told Larry to call the plumber.",
    "Hilary is coming over for dinner tonight.",
    "It was a scenario nobody planned for.",
    "Maria left the keys on the counter.",
    "Please set the alarm for six in the morning.",
    "We drove past the lariat ranch on the way.",
    "Alicia said the meeting moved to Thursday.",
    "The area code changed last spring.",
    "Ilaria said the order should arrive on Friday.",
    "Aaliyah sang the whole song without a break.",
    "The area around the lake is protected land.",
    "Elena took the early train to the coast.",
    "He called Larry again about the invoice.",
    "The scenario we rehearsed never actually happened.",
    "Malaria cases fell after the rains stopped.",
]

TV_SENTENCES = [
    "The weather tomorrow will be cloudy with light rain.",
    "Prices at the market rose again this quarter.",
    "Police reported no injuries in the accident.",
    "The team won the match in the final minutes.",
    "A new study says sleep matters more than exercise.",
    "The train to the city leaves every twenty minutes.",
    "She opened the letter and read it twice.",
    "The building was closed for repairs all week.",
    "Local farmers expect a good harvest this year.",
    "The film starts at eight in the main hall.",
    "He walked to the corner and waited for the bus.",
    "The library extended its opening hours.",
    "Traffic on the bridge was slow all morning.",
    "They painted the kitchen a pale green.",
    "The concert sold out within an hour.",
    "Our neighbours adopted a small black dog.",
]

FREE_SPEECH = [
    ("So anyway I was telling him about the thing with the car, and he "
     "just laughed and said it happens to everyone eventually."),
    ("The problem was never the plan itself, it was that nobody agreed "
     "on what order the steps were supposed to happen in."),
    ("I think we should wait until the morning and then decide, because "
     "nothing good comes out of deciding these things at midnight."),
]


# ---------------------------------------------------------------------------
# clip builders — every clip is a full 1.0 s runtime window
# ---------------------------------------------------------------------------
def shift_pitch(x, rng, semitones=2.0):
    """Resample-based pitch/formant shift — new speakers from old ones.

    The head has to generalise to voices espeak cannot produce, so every
    clip passes through this: a clip is a voice, a rate, a pitch AND a random
    shift, never a fixed timbre.
    """
    factor = 2.0 ** (float(rng.uniform(-semitones, semitones)) / 12.0)
    n = max(1, round(x.size / factor))
    idx = np.linspace(0, x.size - 1, n)
    return np.interp(idx, np.arange(x.size), x).astype(np.float32)


def reverb(x, rng, wet=0.25):
    """One or two early reflections — espeak is bone dry, rooms are not."""
    out = x.copy()
    for _ in range(int(rng.integers(1, 3))):
        delay = int(rng.integers(round(0.015 * SR_PCM), round(0.075 * SR_PCM)))
        if delay < len(x):
            out[delay:] += wet * x[:-delay] * float(rng.uniform(0.4, 1.0))
    return out


def _fit_length(speech, limit):
    """Whole utterance inside `limit` samples — compressed, never truncated.

    Cutting the front off "Elaria" leaves "laria"/"aria", which is exactly a
    near-word: a truncated positive teaches the head to fire on the negative
    class. Speed it up instead.
    """
    if speech.size <= limit:
        return speech
    idx = np.linspace(0, speech.size - 1, limit)
    return np.interp(idx, np.arange(speech.size), speech).astype(np.float32)


def place(speech, rng, window_n, tail_s=0.28):
    """Put a WHOLE utterance in the window so its end lands near the end.

    The daemon scores the trailing ``keyword_window_s`` slice right after a
    trigger, so the phrase sits at the tail — with 0-0.28 s of lead-out for
    trigger lag — and only noise precedes it, never a phrase mid-window.
    """
    speech = np.atleast_1d(_fit_length(speech, int(window_n * 0.98)))
    out = np.zeros(window_n, np.float32)
    max_tail = window_n - speech.size
    cap = min(round(tail_s * SR_PCM), max_tail)
    tail = int(rng.integers(0, cap + 1)) if cap > 0 else 0
    start = window_n - tail - speech.size
    out[start:start + speech.size] = speech
    return out


def utter(rng, text, voice, rate=(105, 205), pitch=(20, 80), amp=(80, 140)):
    """espeak -> 16 kHz, with a random speaker shift (see `shift_pitch`)."""
    speech = resample(say(text, voice,
                          int(rng.integers(*rate)),
                          int(rng.integers(*pitch)),
                          int(rng.integers(*amp))), SR_SYNTH, SR_PCM)
    return shift_pitch(speech, rng)


def positive_clip(rng, voice, texts, window_n):
    text = texts[int(rng.integers(0, len(texts)))]
    speech = utter(rng, text, voice)
    core = place(reverb(speech, rng), rng, window_n) * float(rng.uniform(0.5, 1.0))
    bed = room_tone(window_n, rng)
    if rng.random() < 0.25:
        bed = bed + music_bed(window_n, rng) * 0.4
    snr = float(rng.choice([99.0, 20.0, 12.0, 6.0, 3.0], p=[.18, .27, .27, .18, .10]))
    return mix(core, bed, snr)


def negative_clip(rng, voice, kind, window_n, pool):
    if kind == "near":
        roll = rng.random()
        if roll < 0.40:
            speech = utter(rng, NEAR_WORDS[int(rng.integers(0, len(NEAR_WORDS)))], voice)
        elif roll < 0.80:
            speech = utter(rng, NEAR_ARIA[int(rng.integers(0, len(NEAR_ARIA)))], voice)
        else:
            speech = utter(rng, NEAR_SENTENCES[int(rng.integers(0, len(NEAR_SENTENCES)))],
                           voice, rate=(140, 200))
        core = place(speech, rng, window_n)
        return mix(core, room_tone(window_n, rng),
                   float(rng.choice([99.0, 20.0, 12.0, 6.0], p=[.25, .3, .3, .15])))
    if kind == "tv":
        speech = utter(rng, TV_SENTENCES[int(rng.integers(0, len(TV_SENTENCES)))],
                       voice, rate=(140, 210), pitch=(20, 75), amp=(80, 130))
        return mix(place(speech, rng, window_n), room_tone(window_n, rng), 12.0)
    if kind == "freespeech":
        speech = utter(rng, FREE_SPEECH[int(rng.integers(0, len(FREE_SPEECH)))],
                       voice, rate=(150, 200), pitch=(25, 70), amp=(80, 130))
        if speech.size > window_n:                 # a slice of continuous talk
            at = int(rng.integers(0, speech.size - window_n))
            return mix(speech[at:at + window_n], room_tone(window_n, rng), 15.0)
        return mix(place(speech, rng, window_n), room_tone(window_n, rng), 15.0)
    if kind == "babble":
        return babble(window_n, rng, pool, TV_SENTENCES + NEAR_SENTENCES) * 0.5
    if kind == "music":
        return music_bed(window_n, rng) * float(rng.uniform(0.2, 0.7))
    return room_tone(window_n, rng) * float(rng.uniform(0.15, 0.8))   # ambient


# ---------------------------------------------------------------------------
# features — through the runtime's own pipeline
# ---------------------------------------------------------------------------
def features_for(model, pcm, head_frames=HEAD_FRAMES):
    """PCM -> (head_frames, 96) the way the daemon will feed the head."""
    emb = model.embedding_frames(pcm)
    if emb is None:                      # window too short to hold a mel window
        return None
    if emb.shape[0] < head_frames:       # same front-pad rule as head_inputs
        pad = np.repeat(emb[:1], head_frames - emb.shape[0], axis=0)
        emb = np.concatenate([pad, emb], axis=0)
    return emb[-head_frames:].astype(np.float32)


def build_dataset(model, voices, rng, n_pos, n_neg, window_n, pool):
    """[(features, label, pcm, kind)] for one split, plus per-kind counts."""
    rows = []
    let = {}
    for _ in range(n_pos):
        v = voices[int(rng.integers(0, len(voices)))]
        pcm = to_pcm16(positive_clip(rng, v, POSITIVE_TEXTS, window_n),
                       peak_dbfs=float(rng.uniform(-20.0, -3.0)))
        feats = features_for(model, pcm)
        if feats is not None:
            rows.append((feats, 1, pcm, "positive"))
    # Near-words are the whole difficulty of this task (see NEAR_ARIA), so
    # they get the largest share of the negative budget. This is a DATA
    # allocation, not a threshold: `keyword_threshold` stays 0.5.
    kinds = ["near"] * 6 + ["tv", "freespeech", "babble", "music", "ambient"]
    for i in range(n_neg):
        kind = kinds[i % len(kinds)]
        v = voices[int(rng.integers(0, len(voices)))]
        pcm = to_pcm16(negative_clip(rng, v, kind, window_n, pool),
                       peak_dbfs=float(rng.uniform(-20.0, -3.0)))
        feats = features_for(model, pcm)
        if feats is not None:
            rows.append((feats, 0, pcm, kind))
            let[kind] = let.get(kind, 0) + 1
    return rows, let


# ---------------------------------------------------------------------------
# the head — two hidden layers, numpy, Adam
# ---------------------------------------------------------------------------
class Head:
    """(N, 96) embeddings -> score. Two ReLU layers, normalization folded in.

    Two layers (not one) because the positive/negative boundary here is not
    linear: "malaria" and "Elaria" differ in one phoneme, so the head needs a
    composed feature ("-aria tail AND not a leading m/l/h") rather than a
    single hyperplane. Still ~470 KB at 4x96 -> 256 -> 64.
    """

    def __init__(self, d_in, hidden, rng, hidden2=None):
        self.hidden2 = int(hidden2 or max(16, hidden // 4))
        self.mean = np.zeros(d_in, np.float32)
        self.std = np.ones(d_in, np.float32)
        self.w1 = (rng.standard_normal((d_in, hidden)) * math.sqrt(2.0 / d_in)).astype(np.float32)
        self.b1 = np.zeros(hidden, np.float32)
        self.w2 = (rng.standard_normal((hidden, self.hidden2))
                   * math.sqrt(2.0 / hidden)).astype(np.float32)
        self.b2 = np.zeros(self.hidden2, np.float32)
        self.w3 = (rng.standard_normal((self.hidden2, 1))
                   * math.sqrt(1.0 / self.hidden2)).astype(np.float32)
        self.b3 = np.zeros(1, np.float32)

    def norm(self, x):
        return (x - self.mean) / self.std

    def forward(self, x):
        z = self.norm(x)
        h1 = np.maximum(0.0, z @ self.w1 + self.b1)
        h2 = np.maximum(0.0, h1 @ self.w2 + self.b2)
        logit = h2 @ self.w3 + self.b3
        return logit[:, 0], h2, z, h1

    def predict(self, x):
        logit = self.forward(x)[0]
        return 1.0 / (1.0 + np.exp(-logit))


def augment_batch(xb, rng, scale=0.06, frames=None):
    """Embedding-space augmentation: small jitter + frame dropout.

    Real mics, codecs and rooms move these 96-dim vectors; teaching the head
    that neighbourhood (instead of memorising exact espeak vectors) is what
    buys generalisation to voices it has never heard.
    """
    if scale <= 0:
        return xb
    xb = xb * (1.0 + scale * rng.standard_normal(xb.shape).astype(np.float32))
    if frames:
        drop = rng.random((xb.shape[0], frames)) < 0.05
        for f in range(frames):
            sel = drop[:, f]
            if sel.any():
                xb[sel, f * 96:(f + 1) * 96] = 0.0
    return xb.astype(np.float32)


def fit(head, x, y, xv, yv, epochs=60, batch=128, lr=3e-3, l2=3e-4, seed=SEED,
        aug=0.06, frames=None):
    rng = np.random.default_rng(seed)
    params = ["w1", "b1", "w2", "b2", "w3", "b3"]
    m = {k: np.zeros_like(getattr(head, k)) for k in params}
    v = {k: np.zeros_like(getattr(head, k)) for k in params}
    step = 0
    best = (-1.0, {k: getattr(head, k).copy() for k in params}, -1)
    n = x.shape[0]
    for epoch in range(epochs):
        order = rng.permutation(n)
        for at in range(0, n, batch):
            idx = order[at:at + batch]
            xb = augment_batch(x[idx], rng, scale=aug, frames=frames)
            yb = y[idx].astype(np.float32)
            logit, h2, z, h1 = head.forward(xb)
            p = 1.0 / (1.0 + np.exp(-logit))
            d_logit = ((p - yb) / len(idx))[:, None]          # BCE gradient
            g = {"w3": h2.T @ d_logit + l2 * head.w3,
                 "b3": d_logit.sum(axis=0)}
            d_h2 = d_logit @ head.w3.T
            d_h2[h2 <= 0] = 0.0
            g["w2"] = h1.T @ d_h2 + l2 * head.w2
            g["b2"] = d_h2.sum(axis=0)
            d_h1 = d_h2 @ head.w2.T
            d_h1[h1 <= 0] = 0.0
            g["w1"] = z.T @ d_h1 + l2 * head.w1
            g["b1"] = d_h1.sum(axis=0)
            step += 1
            for k in params:
                m[k] = 0.9 * m[k] + 0.1 * g[k]
                v[k] = 0.999 * v[k] + 0.001 * (g[k] ** 2)
                mhat = m[k] / (1 - 0.9 ** step)
                vhat = v[k] / (1 - 0.999 ** step)
                getattr(head, k)[...] -= lr * mhat / (np.sqrt(vhat) + 1e-8)
        # selection on the HELD-OUT VOICES, at the frozen threshold
        bal = _balanced_acc(yv, head.predict(xv), FROZEN_THRESHOLD)
        if bal > best[0]:
            best = (bal, {k: getattr(head, k).copy() for k in params}, epoch)
        elif epoch - best[2] > 12:
            break
    for k in params:
        getattr(head, k)[...] = best[1][k]
    return best[0], best[2]


def _balanced_acc(y, p, thr):
    y = np.asarray(y).astype(int)
    pred = (p >= thr).astype(int)
    tpr = float(np.mean(pred[y == 1] == 1)) if np.any(y == 1) else 0.0
    tnr = float(np.mean(pred[y == 0] == 0)) if np.any(y == 0) else 0.0
    return 0.5 * (tpr + tnr)


def roc_auc(y, p):
    y = np.asarray(y).astype(int)
    pos, neg = p[y == 1], p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, allv.size + 1)
    for val in np.unique(allv):                        # average ranks over ties
        sel = allv == val
        if sel.sum() > 1:
            ranks[sel] = ranks[sel].mean()
    r_pos = ranks[: pos.size].sum()
    return float((r_pos - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


# ---------------------------------------------------------------------------
# ONNX export — normalization folded into the graph
# ---------------------------------------------------------------------------
def export_onnx(head, path, head_frames=HEAD_FRAMES, opset=14):
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    d_in = head.w1.shape[0]
    per_frame = d_in // head_frames
    nodes = [
        helper.make_node("Sub", ["input", "feat_mean"], ["centered"]),
        helper.make_node("Div", ["centered", "feat_std"], ["normalized"]),
        helper.make_node("Flatten", ["normalized"], ["flat"], axis=1),
        helper.make_node("Gemm", ["flat", "w1", "b1"], ["hidden_pre"], alpha=1.0),
        helper.make_node("Relu", ["hidden_pre"], ["hidden"]),
        helper.make_node("Gemm", ["hidden", "w2", "b2"], ["hidden2_pre"], alpha=1.0),
        helper.make_node("Relu", ["hidden2_pre"], ["hidden2"]),
        helper.make_node("Gemm", ["hidden2", "w3", "b3"], ["logit"], alpha=1.0),
        helper.make_node("Sigmoid", ["logit"], ["score"]),
    ]
    inits = [
        numpy_helper.from_array(
            head.mean.reshape(1, head_frames, per_frame).astype(np.float32), "feat_mean"),
        numpy_helper.from_array(
            np.maximum(head.std, 1e-6).reshape(1, head_frames, per_frame)
            .astype(np.float32), "feat_std"),
        numpy_helper.from_array(head.w1.astype(np.float32), "w1"),
        numpy_helper.from_array(head.b1.astype(np.float32), "b1"),
        numpy_helper.from_array(head.w2.astype(np.float32), "w2"),
        numpy_helper.from_array(head.b2.astype(np.float32), "b2"),
        numpy_helper.from_array(head.w3.astype(np.float32), "w3"),
        numpy_helper.from_array(head.b3.astype(np.float32), "b3"),
    ]
    graph = helper.make_graph(
        nodes, "elaria_wake_head",
        [helper.make_tensor_value_info(
            "input", TensorProto.FLOAT, [1, head_frames, per_frame])],
        [helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])],
        inits)
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", opset)],
        producer_name="elaria-train_elaria_head",
        doc_string=("Elaria wake head: (1,4,96) openWakeWord embeddings -> "
                    "sigmoid score. Trained on synthetic espeak-ng positives "
                    "and near-word/room/TV/babble negatives. A hit grants "
                    "nothing; ECAPA verifies the command window."))
    model.ir_version = 8
    onnx.checker.check_model(model)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, path)
    return path


# ---------------------------------------------------------------------------
def per_kind_error(rows, scores, labels):
    """Error per negative class (or recall for `positive`)."""
    out = {}
    for kind in sorted({r[3] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r[3] == kind]
        sel = labels[idx] == 1
        if sel.any():
            out[kind] = round(float(np.mean(scores[idx][sel] < FROZEN_THRESHOLD)), 4)
        else:
            out[kind] = round(float(np.mean(scores[idx] >= FROZEN_THRESHOLD)), 4)
    return out


def write_fixture(path, model, voices, rng_seed):
    """Held-out npz for tests/test_j_elaria_head.py — test-split voices only.

    Carries three things, and all three matter:

    * ``clips``  — the raw 16 kHz s16le windows, so a test can push them
      through the runtime pipeline itself;
    * ``feats``  — the head input ``OpenWakeWordModel.embedding_frames``
      produced for each clip *at fixture time*;
    * ``labels`` — 1 = "Elaria", 0 = anything else.

    A test that only checked ``feats -> head -> score`` would still pass if
    the runtime's feature path were silently replaced. Comparing
    ``clips -> runtime pipeline -> feats`` is what makes the check fail when
    the wiring is removed.
    """
    rng = np.random.default_rng(rng_seed)
    clips, feats, labels, names = [], [], [], []
    planned = ([(1, "pos")] * 20
               + [(0, "near")] * 10 + [(0, "tv")] * 5 + [(0, "babble")] * 5
               + [(0, "music")] * 3 + [(0, "ambient")] * 3
               + [(0, "freespeech")] * 4)
    for i, (label, kind) in enumerate(planned):
        v = voices[i % len(voices)]
        if label:
            pcm = to_pcm16(positive_clip(rng, v, POSITIVE_TEXTS, int(WINDOW_S * SR_PCM)),
                           peak_dbfs=float(rng.uniform(-14.0, -6.0)))
            names.append(f"pos_{i}_{v}")
        else:
            pcm = to_pcm16(negative_clip(rng, v, kind, int(WINDOW_S * SR_PCM), voices),
                           peak_dbfs=float(rng.uniform(-14.0, -6.0)))
            names.append(f"neg_{kind}_{i}_{v}")
        f = features_for(model, pcm)
        if f is None:                                  # pragma: no cover - short clip
            continue
        clips.append(np.frombuffer(pcm, dtype="<i2"))
        feats.append(f)
        labels.append(label)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, clips=np.array(clips), feats=np.array(feats, np.float32),
                        labels=np.array(labels), names=np.array(names),
                        sample_rate=np.array(SR_PCM),
                        threshold=np.array(FROZEN_THRESHOLD),
                        notes=np.array(
                            "held-out (test-split voices); feats are the runtime "
                            "embedding_frames output; labels 1=Elaria 0=not"))
    print(f"fixture -> {path} ({Path(path).stat().st_size} bytes, "
          f"{len(clips)} clips, voices outside the training split)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="models/elaria_head.onnx")
    ap.add_argument("--melspec", default="models/melspectrogram.onnx")
    ap.add_argument("--embedding", default="models/embedding_model.onnx")
    ap.add_argument("--positives", type=int, default=1500)
    ap.add_argument("--negatives", type=int, default=2400)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--augment", type=float, default=0.08,
                    help="embedding-space jitter std (0 disables)")
    ap.add_argument("--voices", choices=("all", "deterministic"), default="all",
                    help="`deterministic` keeps only byte-stable voices (the "
                         "exported head is then reproducible bit-for-bit)")
    ap.add_argument("--report-json", default="")
    ap.add_argument("--fixture", default="",
                    help="write held-out npz for tests/test_j_elaria_head.py")
    args = ap.parse_args()

    try:
        voices = espeak_voices()
        if args.voices == "deterministic":
            voices = deterministic_voices(voices)
            if len(voices) < 6:
                print(f"refused: only {len(voices)} byte-stable voices in this "
                      "espeak build — too few to train on", file=sys.stderr)
                return 2
    except SynthUnavailable as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    for p in (args.melspec, args.embedding):
        if not Path(p).is_file():
            print(f"refused: missing feature model {p!r} — this lane needs "
                  "openWakeWord v0.5.1 melspectrogram.onnx + "
                  "embedding_model.onnx in models/", file=sys.stderr)
            return 2
    import onnxruntime as ort

    def make(p):
        return ort.InferenceSession(p, providers=["CPUExecutionProvider"])

    # Only the two feature sessions are live while fitting; the head session
    # is created after export, because until then there is no head file.
    model = OpenWakeWordModel("head-not-built-yet.onnx", args.melspec, args.embedding)
    model._sessions = (make(args.melspec), make(args.embedding), None)

    rng = np.random.default_rng(SEED)
    shuffled = list(voices)
    rng.shuffle(shuffled)
    n_test = max(1, round(len(shuffled) * 0.20))
    n_val = max(1, round(len(shuffled) * 0.10))
    test_voices = shuffled[:n_test]
    val_voices = shuffled[n_test:n_test + n_val]
    train_voices = shuffled[n_test + n_val:]
    print(f"voices: {len(voices)} total -> {len(train_voices)} train / "
          f"{len(val_voices)} val / {len(test_voices)} test (split by voice)")

    window_n = int(WINDOW_S * SR_PCM)
    print(f"synthesizing {args.positives} positives + {args.negatives} negatives ...")
    train_rows, _train_kinds = build_dataset(
        model, train_voices, np.random.default_rng(SEED + 1),
        args.positives, args.negatives, window_n, train_voices)
    val_rows, _ = build_dataset(
        model, val_voices, np.random.default_rng(SEED + 2),
        max(60, args.positives // 6), max(60, args.negatives // 6), window_n, val_voices)
    test_rows, test_kinds = build_dataset(
        model, test_voices, np.random.default_rng(SEED + 3),
        max(40, args.positives // 5), max(40, args.negatives // 5), window_n, test_voices)
    print(f"features: train {len(train_rows)} / val {len(val_rows)} / "
          f"test {len(test_rows)}")

    def stack(rows):
        x = np.array([r[0] for r in rows], np.float32).reshape(len(rows), -1)
        y = np.array([r[1] for r in rows], np.int8)
        return x, y

    x, y = stack(train_rows)
    xv, yv = stack(val_rows)
    xt, yt = stack(test_rows)

    head = Head(x.shape[1], args.hidden, np.random.default_rng(SEED))
    head.mean = x.mean(axis=0)
    head.std = np.maximum(x.std(axis=0), 1e-3)

    bal, best_epoch = fit(head, x, y, xv, yv, epochs=args.epochs,
                          aug=args.augment, frames=HEAD_FRAMES)

    p_tr, p_v, p_t = head.predict(x), head.predict(xv), head.predict(xt)
    numbers = {
        "threshold": FROZEN_THRESHOLD,
        "head_frames": HEAD_FRAMES,
        "window_s": WINDOW_S,
        "hidden": args.hidden,
        "augment": args.augment,
        "seed": SEED,
        "voices_mode": args.voices,
        "voices_available": len(voices),
        "epochs_best": int(best_epoch),
        "n_train": len(train_rows),
        "n_val": len(val_rows),
        "n_test": len(test_rows),
        "voices_train": len(train_voices),
        "voices_val": len(val_voices),
        "voices_test": len(test_voices),
        "test_positives": int(np.sum(yt == 1)),
        "test_negatives": int(np.sum(yt == 0)),
        "ballacc_train": float(_balanced_acc(y, p_tr, FROZEN_THRESHOLD)),
        "ballacc_val": float(bal),
        "auc_test": roc_auc(yt, p_t),
        "false_accept_rate_test": float(np.mean(p_t[yt == 0] >= FROZEN_THRESHOLD)),
        "false_reject_rate_test": float(np.mean(p_t[yt == 1] < FROZEN_THRESHOLD)),
        "false_accept_by_kind_val": per_kind_error(val_rows, p_v, yv),
        "false_accept_rate_by_kind_test": per_kind_error(test_rows, p_t, yt),
        "negatives_by_kind_test": test_kinds,
        "score_mean_pos_test": float(p_t[yt == 1].mean()),
        "score_mean_neg_test": float(p_t[yt == 0].mean()),
        "score_p05_pos_test": float(np.quantile(p_t[yt == 1], 0.05)),
        "score_p95_neg_test": float(np.quantile(p_t[yt == 0], 0.95)),
    }
    export_onnx(head, args.out, HEAD_FRAMES)
    numbers["sha256"] = hashlib.sha256(Path(args.out).read_bytes()).hexdigest()
    numbers["bytes"] = Path(args.out).stat().st_size
    numbers["path"] = args.out

    # Re-score the exported graph through the runtime loader on the SAME PCM
    # windows: the numbers above come from the numpy model, so this proves the
    # shipped file, driven by the runtime feature path, reproduces them.
    exported = OpenWakeWordModel.load(args.out, args.melspec, args.embedding)
    max_delta = 0.0
    disagree = 0
    for feats, _label, pcm, _kind in test_rows:
        numpy_score = float(head.predict(feats.reshape(1, -1))[0])
        shipped = float(exported.score_window(pcm))
        max_delta = max(max_delta, abs(shipped - numpy_score))
        disagree += int((shipped >= FROZEN_THRESHOLD) != (numpy_score >= FROZEN_THRESHOLD))
    numbers["exported_vs_numpy_max_delta"] = float(max_delta)
    numbers["exported_vs_numpy_verdict_disagreements"] = int(disagree)

    if args.fixture:
        model._sessions = (model._sessions[0], model._sessions[1],
                           exported._load_sessions()[2])
        write_fixture(args.fixture, model, test_voices, rng_seed=SEED + 77)
        numbers["fixture"] = args.fixture

    print("validation per-kind error "
          + json.dumps(numbers["false_accept_by_kind_val"], sort_keys=True))
    print("false_accept_rate_by_kind_test "
          + json.dumps(numbers["false_accept_rate_by_kind_test"], sort_keys=True))
    print(json.dumps(numbers, indent=2, sort_keys=True))
    print(f"exported-vs-numpy max |delta| on {len(test_rows)} held-out windows: "
          f"{max_delta:.3g} ({disagree} verdict flips at {FROZEN_THRESHOLD})")
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(numbers, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
