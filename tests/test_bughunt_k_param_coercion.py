"""BH-K29 (minor batch): bare int(params...) turned client mistakes
into TypeError/KeyError gibberish.

`int(params.get("id"))` (knock accept/decline/later/ignore),
`int(params["item_id"])` (review.decide), `int(params["job_id"])`
(queue approve) and `int(params["commitment_id"])` raised
TypeError/KeyError for a missing or mistyped id. The IPC layer
stringifies those verbatim, so a console/script client that forgot a
field got "TypeError: int() argument must be a string..." instead of
an actionable refusal (ValueError is the daemon's refusal type and
maps to the clean exit-2 path since BH-K12).

Fix: `_int_param` coerces with a ValueError naming the parameter.
"""

from __future__ import annotations

import pytest

from assistant.ipc import DaemonError, call


@pytest.mark.parametrize("method,params,fragment", [
    ("knock.accept", {}, "id"),
    ("knock.decline", {"id": "not-a-number"}, "id"),
    ("knock.ignore", {}, "id"),
    ("knock.later", {}, "id"),
    ("review.decide", {"verdict": "approve"}, "item_id"),
    ("queue.approve", {}, "job_id"),
])
def test_missing_or_bad_id_is_an_actionable_refusal(
        config, running_daemon, method, params, fragment):
    with pytest.raises(DaemonError) as err:
        call(config.socket_path, method, params)
    message = str(err.value)
    assert "TypeError" not in message and "KeyError" not in message, message
    assert fragment in message, message
