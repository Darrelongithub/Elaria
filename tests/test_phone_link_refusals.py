"""M2 sidecar refusal, approval-gate, and unpair-enforcement test suite.

Promoted from the Wave 1 / Round 1 M2 verification proof so that 28/28
per-verb refusal logging assertions (including bare ``"send-text"``), the
IF-1 approval-before-send gate, and local pairing / ``device.unpair``
guards run in CI against ``FakeAndroidPeer`` with zero ``caelestia``
imports.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pytest
from test_phone_link import BODY, RECIPIENT, FakeAndroidPeer, fake_device

from assistant.drafts import DraftError, DraftStore, MemoryDraftBackend
from assistant.phone_link import (
    NotApproved,
    PairingRegistry,
    PhoneLink,
    Refused,
)

#: Complete 28-verb IF-3 / Round-1 M2 refusal matrix, including bare "send-text".
REFUSED_VERBS_28: tuple[str, ...] = (
    "share.share_text",
    "share.share_files",
    "share.share_url",
    "share.open_folder",
    "clipboard.send_clipboard",
    "send-text",
    "send-text.send",
    "remotecommands",
    "remotecommands.trigger",
    "remotecommands.edit_commands",
    "runcommand",
    "runcommand.add_command",
    "remotecontrol",
    "remotecontrol.move",
    "mousepad",
    "mousepad.move",
    "remotekeyboard",
    "remotekeyboard.send_key",
    "remotekeyboard.send_text",
    "sftp",
    "sftp.browse",
    "sftp.mount",
    "sftp.unmount",
    "lockdevice",
    "lockdevice.set_locked",
    "call",
    "call.sms.send_sms",
    "phoneaudio.toggle",
)


@pytest.fixture
def peer_env(tmp_path: Path):
    peer = FakeAndroidPeer(tmp_path / "ipc.sock", devices=[fake_device()])
    peer.start()
    journal: list[tuple[str, dict[str, Any]]] = []
    registry = PairingRegistry(tmp_path / "pairs.json")
    link = PhoneLink(
        peer.path,
        registry=registry,
        journal=lambda event, **fields: journal.append((event, fields)),
    )
    store = DraftStore(MemoryDraftBackend())
    try:
        yield peer, link, registry, store, journal
    finally:
        link.close()
        peer.stop()


def test_refusal_matrix_has_all_28_verbs() -> None:
    assert len(REFUSED_VERBS_28) == 28
    assert len(set(REFUSED_VERBS_28)) == 28
    assert "send-text" in REFUSED_VERBS_28


@pytest.mark.parametrize("verb", REFUSED_VERBS_28)
def test_m2_all_28_refused_verbs_are_logged_and_send_zero_packets(
    peer_env: tuple[
        FakeAndroidPeer,
        PhoneLink,
        PairingRegistry,
        DraftStore,
        list[tuple[str, dict[str, Any]]],
    ],
    caplog: pytest.LogCaptureFixture,
    verb: str,
) -> None:
    peer, link, _registry, _store, journal = peer_env
    with (
        caplog.at_level(logging.WARNING, logger="assistant.phone_link"),
        pytest.raises(Refused),
    ):
        link.request(verb)

    assert peer.packets == []
    assert peer.calls == []
    assert peer.sends == []
    assert len(link.refusals) == 1
    assert link.refusals[0]["verb"] == verb
    refused_events = [(ev, fields) for ev, fields in journal if ev == "phone.refused"]
    assert len(refused_events) == 1
    assert refused_events[0][1]["verb"] == verb
    assert any(
        rec.levelno == logging.WARNING and f"refused {verb}:" in rec.getMessage()
        for rec in caplog.records
    )


def test_m2_sms_send_gate_blocks_unapproved_and_sends_once_after_approve(
    peer_env: tuple[
        FakeAndroidPeer,
        PhoneLink,
        PairingRegistry,
        DraftStore,
        list[tuple[str, dict[str, Any]]],
    ],
) -> None:
    peer, link, _registry, store, _journal = peer_env
    link.sync_pairing()
    peer.packets.clear()

    # Direct request("sms.send_sms") is always refused.
    with pytest.raises(Refused):
        link.request("sms.send_sms", addresses=[RECIPIENT], message=BODY)
    assert peer.packets == []

    # Pending, rejected, and expired drafts cannot send.
    pending_id = store.create_draft("4242", RECIPIENT, BODY)
    with pytest.raises(NotApproved):
        link.send_approved(pending_id, store=store, device="phone-1")

    rejected_id = store.create_draft("4242", RECIPIENT, BODY)
    store.reject(rejected_id, detail="owner declined")
    with pytest.raises(NotApproved):
        link.send_approved(rejected_id, store=store, device="phone-1")

    expired_id = store.create_draft("4242", RECIPIENT, BODY)
    store.expire_sweeper(now=time.time() + 10_000.0)
    with pytest.raises(NotApproved):
        link.send_approved(expired_id, store=store, device="phone-1")
    assert peer.calls == []
    assert peer.sends == []

    # Approved draft sends exactly once, and repeat approve or resend is blocked.
    approved_id = store.create_draft("4242", RECIPIENT, BODY)
    store.approve(approved_id)
    with pytest.raises(DraftError):
        store.approve(approved_id)

    link.send_approved(approved_id, store=store, device="phone-1")
    assert peer.calls == [("sms", "send_sms", {"addresses": [RECIPIENT], "message": BODY})]
    assert peer.sends == [{"addresses": [RECIPIENT], "message": BODY}]

    with pytest.raises(NotApproved):
        link.send_approved(approved_id, store=store, device="phone-1")
    assert len(peer.sends) == 1


def test_m2_revoke_and_local_unpaired_guard_leave_zero_escape_paths(
    tmp_path: Path,
) -> None:
    sock_path = tmp_path / "ipc.sock"
    peer = FakeAndroidPeer(
        sock_path,
        devices=[fake_device(device_id="phone-1", paired=False, reachable=True)],
    )
    peer.start()
    registry = PairingRegistry(tmp_path / "pairs.json")
    link = PhoneLink(peer.path, registry=registry)
    store = DraftStore(MemoryDraftBackend())
    draft_id = store.create_draft("4242", RECIPIENT, BODY)
    store.approve(draft_id)
    try:
        # Unpaired-but-reachable device must be refused locally with ZERO IPC packets.
        with pytest.raises(Refused):
            link.send_approved(draft_id, store=store, device="phone-1")
        assert peer.packets == []

        # Once paired, revoke() emits device.unpair and hard-blocks subsequent sends.
        peer.devices = [fake_device(device_id="phone-1", paired=True, reachable=True)]
        link.sync_pairing()
        assert registry.is_paired("phone-1")
        link.revoke("phone-1")
        assert peer.unpairs == ["phone-1"]
        packets_after_revoke = len(peer.packets)
        with pytest.raises(Refused):
            link.send_approved(draft_id, store=store, device="phone-1")
        assert len(peer.packets) == packets_after_revoke
        assert peer.sends == []
    finally:
        link.close()
        peer.stop()
