"""Voice catalogue resolution — validate a voice against a REAL catalogue.

Stage A, 2026-10-20. The live repro was:

    voice_error: "Voice name Flare is not supported"
    from gemini-2.5-flash-preview-tts

Flare is a Live API voice; a TTS-preview model is the wrong route. Two separate
facts therefore have to be true before any audio is attempted:

1. the configured model is a LIVE model that a real `models.list` can see, and
2. the configured voice is in THAT model's real voice catalogue.

The second fact cannot be hardcoded honestly: Google's published Live list has
30 studio voices, while the Gemini Live app roster (Flare, Glow, Ursa, …) is
wider and may differ per project or rollout. The catalogue is fetched live at
warm time and cached in the store; the committed baseline in
`voice_catalogues.json` exists only so a keyless `doctor`/test can still validate
shape, and it always says `source: baseline` so nobody mistakes it for proof.

A mismatch is a refusal with the allowed list in the message. Never a silent
fallback to another voice, never a different model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

CATALOGUE_STATE_KEY = "voice.catalogue"
BASELINE_PATH = Path(__file__).with_name("voice_catalogues.json")


class VoiceCatalogueError(RuntimeError):
    """Configured model/voice is not in the real catalogue. Carries the list."""

    def __init__(self, message: str, *, allowed: list[str], model: str,
                 source: str):
        super().__init__(message)
        self.allowed = allowed
        self.model = model
        self.source = source


def _read_baseline(path: Path | None = None) -> dict:
    path = path or BASELINE_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "retrieved": None, "models": {}, "studio_voices": [], "app_voices": [],
            "sources": [],
        }


def baseline_voices(baseline: dict | None = None) -> list[str]:
    baseline = baseline or _read_baseline()
    seen: dict[str, str] = {}
    for name in [*(baseline.get("studio_voices") or []),
                 *(baseline.get("app_voices") or [])]:
        seen.setdefault(str(name).lower(), str(name))
    return list(seen.values())


def baseline_catalogue(model: str, baseline: dict | None = None) -> dict:
    """A catalogue dict from the committed baseline. Never labelled verified."""
    baseline = baseline or _read_baseline()
    models = baseline.get("models") or {}
    entry = models.get(model) or {}
    voices = baseline_voices(baseline)
    return {
        "model": model,
        "voices": voices,
        "known_models": sorted(models),
        "source": "baseline",
        "verified": False,
        "retrieved": baseline.get("retrieved"),
        "notes": entry.get("notes") or "",
        "sources": baseline.get("sources") or [],
        "reason": ("no live catalogue fetched yet — the warm/`assist voice models` "
                   "path queries the real API and replaces this"),
    }


def live_catalogue(model: str, voices: list[str], *,
                   known_models: list[str] | None = None,
                   retrieved: str | None = None,
                   baseline: dict | None = None) -> dict:
    """A catalogue assembled from a real API response (the authoritative one).

    `voices.list()` is authoritative for the TTS/studio catalogue. The Gemini
    Live *app* roster (Flare, Glow, …) is not always returned there even when a
    Live session accepts it, so app voices absent from the live list are carried
    as explicitly-labelled candidates: the first real Live turn validates them.
    A candidate is never reported as verified-by-list.
    """
    cleaned = sorted({str(v) for v in voices if str(v).strip()})
    known = {v.lower() for v in cleaned}
    candidates = sorted({
        str(v) for v in (baseline or {}).get("app_voices", [])
        if str(v).lower() not in known
    })
    return {
        "model": model,
        "voices": cleaned,
        "candidate_voices": candidates,
        "known_models": sorted(known_models or [model]),
        "source": "live-api",
        "verified": True,
        "retrieved": retrieved or datetime.now(UTC).isoformat(timespec="seconds"),
        "reason": (f"live catalogue from the Gemini API ({len(cleaned)} voices)"
                   + (f"; {len(candidates)} app-roster candidate(s) validated by "
                      "the first real Live turn" if candidates else "")),
    }


def load_cached(store, model: str) -> dict | None:
    """The warm-time catalogue cached by a previous verified fetch."""
    if store is None:
        return None
    raw = store.get_state(CATALOGUE_STATE_KEY)
    if not raw:
        return None
    try:
        cached = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(cached, dict) or cached.get("model") != model:
        return None
    if not cached.get("verified"):
        return None
    return cached


def save_cached(store, catalogue: dict) -> None:
    if store is not None and catalogue.get("verified"):
        store.set_state(CATALOGUE_STATE_KEY, json.dumps(catalogue, sort_keys=True))


def resolve_catalogue(model: str, *, store=None, fetched: dict | None = None,
                      refresh: bool = False) -> dict:
    """Cached-live > freshly fetched > baseline, in that order of authority.

    `fetched` is what a transport returned from a real API call; it is persisted
    so warm is one call, not four, and so the exact catalogue that validated a
    voice is auditable later.
    """
    if fetched and fetched.get("verified") and fetched.get("model") == model:
        save_cached(store, fetched)
        return fetched
    if not refresh:
        cached = load_cached(store, model)
        if cached:
            return cached
    return baseline_catalogue(model)


def validate_voice(model: str, voice: str, catalogue: dict) -> dict:
    """Validate one voice against a catalogue. Returns a result, never guesses."""
    allowed = list(catalogue.get("voices") or [])
    candidates = list(catalogue.get("candidate_voices") or [])
    wanted = str(voice or "").strip()
    listed = bool(wanted) and wanted.lower() in {v.lower() for v in allowed}
    candidate = bool(wanted) and wanted.lower() in {v.lower() for v in candidates}
    ok = listed or candidate
    if ok:
        # Preserve the catalogue's spelling (Flare, not flare) for the request.
        pool = allowed if listed else candidates
        canonical = next(v for v in pool if v.lower() == wanted.lower())
        return {
            "ok": True, "model": model, "voice": canonical,
            "allowed": [*allowed, *candidates], "source": catalogue.get("source"),
            "verified": bool(catalogue.get("verified")),
            "provisional": candidate and not listed,
            "reason": (f"voice {canonical!r} is in the {catalogue.get('source')} "
                       f"catalogue for {model} ({len(allowed)} voices)"
                       if listed else
                       f"voice {canonical!r} is an app-roster candidate for {model}; "
                       "voices.list did not return it, so the first real Live turn "
                       "is the validation"),
        }
    shown = ", ".join([*allowed, *candidates]) if (allowed or candidates) else "(catalogue empty)"
    return {
        "ok": False, "model": model, "voice": wanted, "allowed": allowed,
        "source": catalogue.get("source"),
        "verified": bool(catalogue.get("verified")),
        "error": (f"voice {wanted!r} is not supported by model {model!r} — "
                  f"allowed ({len(allowed) + len(candidates)}): {shown}. Catalogue source: "
                  f"{catalogue.get('source')}. Fix [gemini] voice (or widen "
                  f"[gemini] allowed_voices deliberately), or set "
                  f"[gemini] gemini_voice_model to a Live model that offers it."),
    }


def validate_or_raise(model: str, voice: str, catalogue: dict) -> dict:
    result = validate_voice(model, voice, catalogue)
    if not result["ok"]:
        raise VoiceCatalogueError(
            result["error"], allowed=result["allowed"], model=model,
            source=str(catalogue.get("source")))
    return result
