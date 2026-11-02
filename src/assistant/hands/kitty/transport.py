"""One-shot encrypted kitty RC transport. No process, discovery, retries or plaintext fallback.

Linux AF_UNIX only. Each connection walks directory fds with O_NOFOLLOW, lstat-checks
its endpoint, and checks SO_PEERCRED. This cannot defend against a compromised same UID.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import stat
import struct
import time
from contextlib import contextmanager
from pathlib import Path

PREFIX = b"\x1bP@kitty-cmd"
SUFFIX = b"\x1b\\"
VERSION = [0, 47, 1]


class TransportError(RuntimeError):
    """Sanitized error: never include a server response, payload, path or password."""


@contextmanager
def directory_fd(path: Path):
    """Walk absolute directory components without following even ancestor symlinks."""
    if not path.is_absolute() or ".." in path.parts or path == Path("/tmp") or Path("/tmp") in path.parents:
        raise PermissionError("unsafe runtime path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            info = os.lstat(component, dir_fd=fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
                    or info.st_uid not in {0, os.getuid()}):
                raise PermissionError("unsafe ancestor")
            new = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            opened = os.fstat(new)
            if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
                os.close(new)
                raise PermissionError("ancestor changed")
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


@contextmanager
def endpoint(path: Path, runtime: Path):
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if not configured or runtime != Path(configured) or not path.is_absolute() or path.parent != runtime:
        raise PermissionError("socket must be directly under current XDG_RUNTIME_DIR")
    with directory_fd(runtime) as fd:
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise PermissionError("runtime must be owned and mode 0700")
        info = os.lstat(path.name, dir_fd=fd)  # lstat semantics
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("endpoint must be an owned socket, not a symlink")
        yield fd, info


def read_password(path: Path) -> str:
    with directory_fd(path.parent) as fd:
        raw = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(raw)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise PermissionError("password must be an owned single-link regular 0600 file")
            value = os.read(raw, 4097)
        finally:
            os.close(raw)
    if len(value) > 4096:
        raise PermissionError("invalid password file")
    password = value.decode("utf-8").rstrip()
    if not password or any(ord(c) < 32 for c in password):
        raise PermissionError("invalid password file")
    return password


def encrypt(command: dict, password: str, public_key: str) -> bytes:
    # Optional local dependency; deliberately no dependency/config edits to frozen files.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    protocol, encoded = public_key.split(":", 1)
    if protocol != "1":
        raise ValueError("unsupported kitty encryption protocol")
    peer = X25519PublicKey.from_public_bytes(base64.b85decode(encoded))
    private = X25519PrivateKey.generate()
    key = hashlib.sha256(private.exchange(peer)).digest()
    iv = os.urandom(12)
    inner = dict(command, password=password, timestamp=time.time_ns())
    plaintext = json.dumps(inner, ensure_ascii=True, allow_nan=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    envelope = {"version": VERSION, "iv": base64.b85encode(iv).decode(),
                "tag": base64.b85encode(ciphertext[-16:]).decode(),
                "pubkey": base64.b85encode(public).decode(),
                "encrypted": base64.b85encode(ciphertext[:-16]).decode()}
    return PREFIX + json.dumps(envelope).encode("ascii") + SUFFIX


class Transport:
    """Connect for exactly one command. The trusted caller selects its tier password."""

    def __init__(self, path: Path, runtime: Path, passwords: dict[str, Path], public_key: str,
                 *, timeout: float = 5, max_response_bytes: int = 8 * 1024 * 1024):
        if not 0 < timeout <= 60 or not 1024 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("invalid transport bounds")
        if set(passwords) != {"K1", "K2", "K3"}:
            raise ValueError("three password paths required")
        self.path, self.runtime, self.passwords = path, runtime, dict(passwords)
        self.public_key, self.timeout, self.max_response_bytes = public_key, timeout, max_response_bytes

    def request(self, verb: str, payload: dict, tier: str, *, no_response: bool = False,
                async_id: str | None = None, cancel: bool = False, stream: bool = False, cancel_event=None):
        try:
            command = {"cmd": verb, "version": VERSION, "payload": payload, "no_response": no_response}
            if async_id:
                command["async"] = async_id
            if cancel:
                command["cancel_async"] = True
            password = read_password(self.passwords[tier])
            payloads = [payload]
            if stream:
                command.update(stream=True, stream_id=secrets.token_urlsafe(24))
                data = payload.get("data", "")
                if data != "-" and not data.startswith("index:"):
                    raw = base64.b64decode(data, validate=True)
                    if len(raw) > 1024 * 1024:
                        raise ValueError("stream exceeds one-shot bound")
                    payloads = [dict(payload, data=base64.b64encode(raw[i:i + 512]).decode("ascii"))
                                for i in range(0, len(raw), 512)] + [dict(payload, data="")]
            frames = [encrypt(dict(command, payload=p), password, self.public_key) for p in payloads]
            if cancel_event is not None and cancel_event.is_set():
                raise TransportError("cancel requested before connect")
            # This context is entered for EVERY request, including verification and async cancel.
            with endpoint(self.path, self.runtime) as (fd, info), socket.socket(socket.AF_UNIX) as conn:
                deadline = time.monotonic() + self.timeout
                conn.settimeout(self.timeout)
                conn.connect(f"/proc/self/fd/{fd}/{self.path.name}")
                _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                after = os.lstat(self.path.name, dir_fd=fd)
                if uid != os.getuid() or (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino):
                    raise PermissionError("endpoint identity changed")
                for frame in frames:
                    if cancel_event is not None and cancel_event.is_set():
                        raise TransportError("cancel requested; effect unknown")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    conn.settimeout(remaining)
                    conn.sendall(frame)
                conn.shutdown(socket.SHUT_WR)
                if no_response:
                    return None  # NOT a claim that the command took effect
                data = bytearray()
                received = 0
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise TransportError("cancel requested; effect unknown")
                    while SUFFIX in data:
                        end = data.index(SUFFIX)
                        frame = bytes(data[:end])
                        del data[:end + len(SUFFIX)]
                        if not frame.startswith(PREFIX):
                            raise TransportError("invalid response frame")
                        response = json.loads(frame[len(PREFIX):])
                        if type(response) is not dict or response.get("ok") is not True:
                            raise TransportError("remote command refused")
                        if response.get("stream") is not True:
                            return response.get("data")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    conn.settimeout(min(remaining, 0.1) if cancel_event is not None else remaining)
                    try:
                        part = conn.recv(min(65536, self.max_response_bytes + 1 - received))
                    except TimeoutError:
                        if cancel_event is None:
                            raise
                        continue
                    if not part:
                        raise TransportError("incomplete response")
                    data.extend(part)
                    received += len(part)
                    if received > self.max_response_bytes:
                        raise TransportError("response too large")
        except Exception:
            # No exception text/chaining: kitty error and traceback may echo private payloads.
            raise TransportError("kitty transport failed; effect unknown, do not replay") from None
