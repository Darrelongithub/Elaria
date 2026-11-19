"""Conservative synthetic trap detector, NOT a universal semantic safety claim.

Data never reaches a plan-update API whether or not this detector flags it.
False negatives cannot create steps: the immutable plan is the only task input.
"""
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

ORIGINS = frozenset({"file", "filename", "stdout", "stderr", "retrieved", "tool_output", "phone", "notification", "transcript", "web"})
_IMPERATIVE = re.compile(
    r"\b(?:delete|remove|erase|wipe|execute|run|ignore|send|upload|append|add|pretend)\s+\S+"
    r'|"(?:steps|argv|env_diff)"\s*:', re.IGNORECASE)


@dataclass(frozen=True)
class DataInput:
    origin: str
    text: str

    def __post_init__(self):
        if self.origin not in ORIGINS or not isinstance(self.text, str):
            raise ValueError("invalid data origin")


def suspected(data: DataInput) -> bool:
    return bool(_IMPERATIVE.search(unicodedata.normalize("NFKC", data.text)))


def load_observation(data: DataInput, *, record: Callable[[str, str, str], None]) -> DataInput:
    """Return planner data only after the journal accepts its provenance.

    The recorder must commit or raise. No plan, runner or dispatch callback is
    available here. Even unrecognized instructions remain observation-only.
    """
    if type(data) is not DataInput:
        raise TypeError("expected tagged observation")
    digest = sha256(data.text.encode("utf-8")).hexdigest()
    record(data.origin, digest, "refused" if suspected(data) else "observed")
    return data
