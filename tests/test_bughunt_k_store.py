"""BH-K22 + forget recount — the store is shared by daemon, CLI, doctor.

K22: the connection used the rollback journal with no explicit busy
    timeout posture. This DB is opened by the daemon AND short-lived CLI
    processes (and doctor): WAL is the mode where readers and a writer
    coexist, and busy_timeout makes contention wait instead of failing a
    user command with "database is locked".
Forget: `forget_facts` by id lacked the `active = 1` filter its topic
    branch has, so forgetting the same id twice reported 1 forgotten
    both times — the count lied.
"""

from __future__ import annotations

from assistant.store import Store


def test_store_uses_wal_and_a_real_busy_timeout(tmp_path):
    store = Store(tmp_path / "s.db")
    try:
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert str(mode).lower() == "wal"
        assert int(busy) >= 5000
    finally:
        store.close()


def test_two_store_instances_interoperate(tmp_path):
    path = tmp_path / "s.db"
    one, two = Store(path), Store(path)
    try:
        one.set_state("k22", "from-one")
        assert two.get_state("k22") == "from-one"
        fid = two.add_fact(ts="2026-10-21T00:00:00+00:00", kind="profile",
                            text="likes tea")
        assert any(f["id"] == fid for f in one.list_facts())
    finally:
        one.close()
        two.close()


def test_forget_by_id_counts_only_what_it_deactivated(tmp_path):
    store = Store(tmp_path / "s.db")
    try:
        fid = store.add_fact(ts="2026-10-21T00:00:00+00:00", kind="profile",
                              text="temporary fact")
        assert store.forget_facts(str(fid)) == 1
        assert store.forget_facts(str(fid)) == 0, (
            "already forgotten must count 0, not recount forever")
    finally:
        store.close()
