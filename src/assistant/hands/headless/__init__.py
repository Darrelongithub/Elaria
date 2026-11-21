"""P · HANDS-HEADLESS — headless kitty host substrate.

Owns the HEADLESS KITTY HOST lifecycle + the WORKER CONTRACT (P-HEADLESS.md).
Consent is REMOVED (act-first/journal-after), but deny-beats-consent and
never-allowlist-an-interpreter survive. The instance fails CLOSED on a version
mismatch BEFORE creating any directory, and only the three verbs
ls/get-text/send-text are reachable at the remote-control level.
"""

from .consent import (
    ConsentFlow,
    Denied,
    InMemoryJournal,
    Journal,
    JsonlJournal,
)
from .contract import (
    ALLOWED_VERBS,
    DEFAULT_EXTENT_SUBSET,
    ContractViolationError,
    WorkerContract,
)
from .host import HeadlessConfig, HeadlessConfigError, HeadlessHost
from .instance import (
    DEFAULT_VERSION_PIN,
    InstanceCheck,
    InstanceError,
    KittyInstance,
    PinMismatchError,
    PinNotConfiguredError,
    VersionGateError,
    sha256_of,
)
from .worker import RemoteRequest, Worker

__all__ = [
    "ALLOWED_VERBS",
    "DEFAULT_EXTENT_SUBSET",
    "DEFAULT_VERSION_PIN",
    "ConsentFlow",
    "ContractViolationError",
    "Denied",
    "HeadlessConfig",
    "HeadlessConfigError",
    "HeadlessHost",
    "InMemoryJournal",
    "InstanceCheck",
    "InstanceError",
    "Journal",
    "JsonlJournal",
    "KittyInstance",
    "PinMismatchError",
    "PinNotConfiguredError",
    "RemoteRequest",
    "VersionGateError",
    "Worker",
    "WorkerContract",
    "sha256_of",
]
