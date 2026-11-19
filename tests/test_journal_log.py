"""D-SAFETY acceptance tests — the unified action+observation journal.

Binaries with numbers, per 00-REPORT-PROTOCOL: every test asserts on
journal *state on disk* (parsed records), never on vibes.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from assistant.journal_log import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_REFUSED,
    OUTCOME_SEEN,
    Denied,
    GovernedAction,
    JournalCorrupt,
    JournalLog,
    JournalStateError,
    deny_beats_consent,
)
from assistant.safety import PolicyDecision


@pytest.fixture
def journal(tmp_path):
    return JournalLog(tmp_path / "state" / "journal.jsonl")


def read_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# -- 1 · the journal-pair invariant -------------------------------------------

def test_governed_action_yields_exactly_one_pair(journal, tmp_path):
    with journal.governed("D", "test.move", target="/tmp/x",
                          detail={"bytes": 3}) as handle:
        assert isinstance(handle, GovernedAction)
    records = read_records(journal.path)
    actions = [r for r in records if r["kind"] == "action"]
    observations = [r for r in records if r["kind"] == "observation"]
    assert len(actions) == 1 and len(observations) == 1
    action, observation = actions[0], observations[0]
    assert observation["action_id"] == action["id"] == handle.id
    assert observation["correlation_id"] == action["correlation_id"]
    assert observation["outcome"] == OUTCOME_OK
    assert action["actor"] == "D" and action["action"] == "test.move"
    assert action["target"] == "/tmp/x" and action["detail"] == {"bytes": 3}
    assert action["consent_present"] is False


def test_failing_body_journals_failed_and_reraises(journal):
    with pytest.raises(RuntimeError, match="boom"), \
            journal.governed("E", "phone.send", target="+254700000000", consent=True):
        raise RuntimeError("boom")
    records = read_records(journal.path)
    assert len(records) == 2
    assert records[1]["outcome"] == OUTCOME_FAILED
    assert records[1]["detail"]["error_type"] == "RuntimeError"
    assert "boom" in records[1]["detail"]["error"]


def test_exactly_one_observation_enforced(journal):
    with journal.governed("D", "test.once") as handle:
        handle.conclude(OUTCOME_OK)
        with pytest.raises(JournalStateError):
            handle.conclude(OUTCOME_OK)
    result = journal.verify()
    assert result["actions_with_multiple_observations"] == 0
    assert result["observations"] == 1


def test_attribution_is_mandatory(journal):
    with pytest.raises(ValueError):
        journal.begin("", "test.noauthority")
    with pytest.raises(ValueError):
        journal.begin("   ", "test.noauthority")
    with pytest.raises(ValueError):
        journal.begin("D", "")
    assert journal.outstanding() == []


def test_journal_survives_process_boundary(journal, tmp_path):
    with journal.governed("B", "memory.write", target="facts"):
        pass
    reopened = JournalLog(journal.path)  # a fresh instance reads what the first wrote
    result = reopened.verify()
    assert result["ok"], result
    assert result["pairs"] == 1


def test_journal_file_is_private(journal):
    with journal.governed("D", "test.perms"):
        pass
    mode = stat.S_IMODE(os.stat(journal.path).st_mode)
    assert mode == 0o600, oct(mode)


def test_preexisting_loose_journal_is_tightened(journal):
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("", encoding="utf-8")
    os.chmod(journal.path, 0o644)
    journal.begin("D", "test.tighten")
    assert stat.S_IMODE(os.stat(journal.path).st_mode) == 0o600


# -- 2 · DENY BEATS CONSENT ----------------------------------------------------

def test_deny_beats_consent_table():
    assert deny_beats_consent(True, True) is True
    assert deny_beats_consent(True, False) is True
    assert deny_beats_consent(False, True) is False
    assert deny_beats_consent(False, False) is False


def test_denied_action_refused_even_with_consent_and_journaled(journal):
    ran = []
    policy = lambda action, target, detail: PolicyDecision(False, "protected path", "deny")
    with pytest.raises(Denied) as excinfo, \
            journal.governed("D", "organise.move", target="~/.ssh/id",
                             policy=policy, consent=True, consent_via="owner-hotkey"):
        ran.append(True)  # pragma: no cover - must never execute
    assert ran == [], "denied action executed — deny-beats-consent violated"
    assert excinfo.value.consent_present is True  # consent existed and lost
    records = read_records(journal.path)
    assert len(records) == 2
    action, observation = records
    assert observation["outcome"] == OUTCOME_REFUSED
    assert observation["detail"]["consent_present"] is True
    assert observation["detail"]["denied"] is True
    assert observation["detail"]["reason"] == "protected path"
    assert action["consent_present"] is True
    assert action["consent_via"] == "owner-hotkey"


def test_denied_tuple_and_bool_policies_also_win_over_consent(journal):
    for policy in (lambda a, t, d: (False, "nope"), lambda a, t, d: False):
        with pytest.raises(Denied), \
                journal.governed("O", "hands.exec", policy=policy, consent=True):
            pass
    assert journal.verify()["observations"] == 2


def test_allowed_policy_with_consent_runs_and_pairs(journal):
    ran = []
    policy = lambda action, target, detail: PolicyDecision(True, "within policy")
    with journal.governed("C", "planner.apply", policy=policy, consent=True):
        ran.append(True)
    assert ran == [True]
    outcomes = [r["outcome"] for r in read_records(journal.path)
                if r["kind"] == "observation"]
    assert outcomes == [OUTCOME_OK]


def test_missing_consent_refuses_and_is_journaled(journal):
    ran = []
    with pytest.raises(Denied, match="consent required"), \
            journal.governed("E", "phone.sms.send", target="+254700000000",
                             consent=False, consent_required=True):
        ran.append(True)
    assert ran == []
    observation = next(r for r in read_records(journal.path) if r["kind"] == "observation")
    assert observation["outcome"] == OUTCOME_REFUSED
    assert observation["detail"]["reason"] == "consent required and not present"


def test_refusal_pairs_do_not_depend_on_policy_object_shape(journal):
    class WeirdVerdict:  # no .allowed — must fail loudly, not silently allow
        pass

    policy = lambda a, t, d: WeirdVerdict()
    with pytest.raises(TypeError), \
            journal.governed("D", "test.shape", policy=policy, consent=True):
        pass


# -- 3 · crash recovery and verification ---------------------------------------

def test_outstanding_intent_is_listed_after_simulated_crash(journal):
    journal.begin("T", "backup.partial", target="/data/x")  # process "died" here
    outstanding = journal.outstanding()
    assert len(outstanding) == 1
    assert outstanding[0]["action"] == "backup.partial"
    result = journal.verify()
    assert result["unpaired_actions"] == 1
    assert result["ok"] is False


def test_verify_flags_orphan_observation(journal, tmp_path):
    # Hand-craft an observation with no action — must be reported, never skipped.
    journal.path.parent.mkdir(parents=True, exist_ok=True)
    orphan = {"v": 1, "kind": "observation", "id": "obs_x", "action_id": "act_missing",
              "ts": "2026-11-19T00:00:00+00:00", "actor": "D", "correlation_id": "c",
              "outcome": "ok", "detail": {}}
    journal.path.write_text(json.dumps(orphan) + "\n", encoding="utf-8")
    result = journal.verify()
    assert result["observations_unknown_action"] == 1
    assert result["ok"] is False


def test_corrupt_line_fails_closed(journal):
    journal.path.parent.mkdir(parents=True, exist_ok=True)
    journal.path.write_text('{"v": 1, "kind": "action"\n', encoding="utf-8")
    with pytest.raises(JournalCorrupt) as excinfo:
        list(journal.records())
    assert excinfo.value.line_no == 1


def test_unsupported_version_line_fails_closed(journal):
    journal.path.parent.mkdir(parents=True, exist_ok=True)
    journal.path.write_text(
        json.dumps({"v": 999, "kind": "action"}) + "\n", encoding="utf-8")
    with pytest.raises(JournalCorrupt):
        list(journal.records())


def test_clean_journal_verifies_with_numbers(journal):
    for n in range(3):
        with journal.governed("A", f"voice.op{n}"):
            pass
    result = journal.verify()
    assert result == {
        "ok": True,
        "path": str(journal.path),
        "actions": 3,
        "observations": 3,
        "pairs": 3,
        "unpaired_actions": 0,
        "actions_with_multiple_observations": 0,
        "observations_unknown_action": 0,
        "duplicate_observations": 0,
        "unknown_outcomes": 0,
    }


def test_empty_journal_verifies_clean_and_says_zero(journal):
    result = journal.verify()
    assert result["ok"] is True
    assert result["actions"] == 0 and result["pairs"] == 0


# -- 4 · untrusted input (IF-6 doctrine) ----------------------------------------

def test_untrusted_input_is_journaled_as_seen_never_used(journal):
    marker = "ghp_secretTOKENvalue12345"
    action_id = journal.note_untrusted_input(
        "ipc:ingress-window", actor="O", detail={"bytes": len(marker)})
    raw = journal.path.read_text(encoding="utf-8")
    assert marker not in raw, "journal must never persist untrusted content"
    records = read_records(journal.path)
    assert len(records) == 2
    action, observation = records
    assert action["id"] == action_id
    assert action["action"] == "untrusted_input.load"
    assert observation["outcome"] == OUTCOME_SEEN
    assert observation["detail"]["disposition"] == "seen_never_used"
