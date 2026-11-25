"""Elaria alive layer — the always-on reminder line and instruction inbox.

A deterministic, LLM-free, authority-free outpost. It can remind, receive,
acknowledge-as-queued, queue, and converse with strangers at the front door
under zero authority — and nothing else. It holds reminders and an inbox;
it never holds the voiceprint, the owner's keys, the database, or any way to
act. Full Elaria (the laptop) is the only place authority exists, and the
owner's spoken yes is the only key.

Module map:

* ``envelope``    — signed immutable envelopes (the wire format, both sides)
* ``config``      — single-recipient, egress allowlist, caps; refuses bad config
* ``store``       — SQLite state (dedup, write-ahead fired, counters, mutes)
* ``transport``   — the only HTTP in the package; S-0 sends; fake for tests
* ``concierge``   — S-0 deterministic stranger responder (no LLM)
* ``mirror``      — verified reader for the laptop's commitment mirror
* ``reminders``   — write-ahead, capped reminder firing
* ``webhook``     — serverless-shaped receiver: signature → tier → envelope
* ``heartbeat``   — the one mutable object, mac'd
* ``sync``        — fixture + rclone sync backends (Drive is the bus)
* ``serve``       — dev runner; production is any free serverless route
* ``provision``   — key generation + the B16-style self-check

Evidence labels: everything here is [TESTED-ONLY] in the sandbox against fake
Meta payloads and a fake transport. Real registration, real tokens and the
first real reminder are the owner's laptop step — never claimed here.
"""

from .envelope import (  # re-exported so both halves agree on the format
    check_name_hash,
    from_hash,
    load_verified,
    sign,
    verify_mac,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "check_name_hash",
    "from_hash",
    "load_verified",
    "sign",
    "verify_mac",
]
