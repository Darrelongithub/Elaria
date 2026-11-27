"""WATCH-BUILD-2 — ingestion filter + RAM store (design §6 + §5.1).

Pure, no bus. Canary suite from design §3 rail 1 (fake nodes whose property
getters raise/record access), journal-lines-contain-no-names, AST import
test (rail 4: no executor/hands/intents/pointer-draw/provider clients),
caps (128/256/20k), seq-gap → stale, RAM-only (never serialised).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from assistant import watch_ingest
from assistant.watch_ingest import Node, Tombstone, ingest_delta, ingest_node
from assistant.watch_store import WatchStore, Window

REPO = Path(__file__).resolve().parents[1]

# Forbidden for rail 4: authority + provider paths. Watching confers zero
# authority (DISPATCH-WATCH rail 4); the store/filter must never reach them.
FORBIDDEN_IMPORTS = frozenset({
    "assistant.executor", "assistant.hands", "assistant.intents",
    "assistant.nus_pointer", "assistant.gemini_client",
    "assistant.live_client", "assistant.provider_router",
    "assistant.planner", "assistant.planner_llm",
    "assistant.daemon", "assistant.store",
})
FORBIDDEN_STDLIB = frozenset({"http", "urllib", "socket", "requests", "httpx"})


class FakeNode:
    """AT-SPI-like node. rect is (x, y, w, h) in window coords."""

    def __init__(self, rect=(0, 0, 10, 10), *children, name="", role="frame",
                 component=True):
        self.rect = rect
        self.children = children
        self.name = name
        self.role = role
        self.component = component

    def get_role(self):
        return self.role

    get_role_name = get_role

    def get_name(self):
        return self.name

    def get_component_iface(self):
        return self if self.component else None

    def get_extents(self, coord_type):
        assert coord_type in ("screen", "window")
        return NS(**dict(zip(("x", "y", "width", "height"), self.rect)))

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, i):
        return self.children[i]


def _window(key="w1", **kw):
    base = {"key": key, "pid": 42, "app": "Files", "title": "Files",
            "rect": (0, 0, 300, 166), "output": "eDP-1", "workspace": 1,
            "visible": True, "focus_rank": 0, "seq": 0, "synced_at": 0.0,
            "state": "live"}
    base.update(kw)
    return Window(**base)


# ---------------------------------------------------------------------------
# rail 1 canary: password nodes never read content
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("component", [True, False])
def test_password_never_reads_content(component, journal_stream):
    accesses = []
    canary = "WATCH-BUILD-2-PRIVATE-CANARY"

    class Password(FakeNode):
        def forbidden(self, *args):
            accesses.append(canary)
            raise AssertionError(canary)

        get_name = get_description = get_text = get_value = forbidden
        get_text_iface = get_editable_text_iface = get_value_iface = forbidden
        get_role_name = get_child_count = get_child_at_index = forbidden

    password = Password((30, 60, 210, 32), name=canary,
                        role="password text", component=component)
    result = ingest_node(password, "w1")
    assert accesses == []
    assert canary not in repr(result)
    assert canary not in journal_stream.getvalue()
    if component:
        assert isinstance(result, Tombstone)
        assert result.role == "password text"
        assert result.rect == (30.0, 60.0, 210.0, 32.0)
        assert result.sensitive is True
        assert result.kind == "tombstone"
    else:
        assert result is None  # no geometry → skipped, still no read


def test_tombstone_has_no_name_field():
    """Type proof (§6.2): the tombstone cannot hold a name or value."""
    tomb = Tombstone(window="w1", parent=None, role="password text",
                     rect=(0.0, 0.0, 10.0, 10.0))
    assert not hasattr(tomb, "name")
    assert not hasattr(tomb, "value")
    assert not hasattr(tomb, "text")
    with pytest.raises(AttributeError):
        tomb.name  # noqa: B018 - proving the attribute does not exist


def test_secret_name_becomes_tombstone(journal_stream):
    canary = "WATCH-BUILD-2-SECRET-CANARY"
    node = FakeNode((10, 10, 100, 20), name=f"api key {canary}", role="entry")
    result = ingest_node(node, "w1")
    assert isinstance(result, Tombstone)
    assert canary not in repr(result)
    assert canary not in journal_stream.getvalue()
    assert "secret-name" in journal_stream.getvalue()


def test_password_role_wins_over_secret_name(journal_stream):
    """Role check precedes the name screen: password + secret name → tombstone."""
    node = FakeNode((10, 10, 100, 20), name="password hunter2",
                    role="password text")
    result = ingest_node(node, "w1")
    assert isinstance(result, Tombstone)
    assert "hunter2" not in repr(result)
    assert "hunter2" not in journal_stream.getvalue()


# ---------------------------------------------------------------------------
# caps + D1 geometry-only
# ---------------------------------------------------------------------------
def test_name_capped_at_64():
    long_name = "A" * 200
    node = FakeNode((10, 10, 100, 20), name=long_name, role="push button")
    result = ingest_node(node, "w1")
    assert isinstance(result, Node)
    assert result.name == "A" * 64
    assert len(result.name) == 64


@pytest.mark.parametrize("role", ["label", "static", "paragraph", "terminal", "document"])
def test_d1_geometry_only_roles_drop_name(role):
    node = FakeNode((10, 10, 100, 20), name="Displayed text", role=role)
    result = ingest_node(node, "w1")
    assert isinstance(result, Node)
    assert result.name is None
    assert result.rect == (10.0, 10.0, 100.0, 20.0)
    assert result.role == role


@pytest.mark.parametrize("role", ["push button", "button", "entry", "menu item",
                                  "check box", "combo box", "link", "slider"])
def test_control_roles_keep_name(role):
    node = FakeNode((10, 10, 100, 20), name="Cancel", role=role)
    result = ingest_node(node, "w1")
    assert isinstance(result, Node)
    assert result.name == "Cancel"


def test_title_filtering():
    assert watch_ingest.filter_title("My password vault") == ""
    assert watch_ingest.filter_title("api key settings") == ""
    assert watch_ingest.filter_title("Files — Home") == "Files — Home"
    assert len(watch_ingest.filter_title("T" * 200)) == 64
    assert watch_ingest.filter_app("secret app") == ""
    assert watch_ingest.filter_app("Files") == "Files"


def test_ingest_delta_defence_in_depth(journal_stream):
    # Child missed a SECRET name → daemon drops it anyway.
    canary = "WATCH-BUILD-2-DELTA-CANARY"
    result = ingest_delta({"role": "entry", "name": f"password {canary}",
                           "rect": [10, 10, 100, 20]}, "w1")
    assert isinstance(result, Tombstone)
    assert canary not in repr(result)
    assert canary not in journal_stream.getvalue()
    # Geometry-only via delta.
    result = ingest_delta({"role": "label", "name": "Hello", "rect": [0, 0, 10, 10]}, "w1")
    assert isinstance(result, Node) and result.name is None
    # Password via delta.
    result = ingest_delta({"role": "password text", "name": canary, "rect": [0, 0, 10, 10]}, "w1")
    assert isinstance(result, Tombstone)
    assert canary not in repr(result)


# ---------------------------------------------------------------------------
# journal lines contain no names (rail 1, §8 metadata-only)
# ---------------------------------------------------------------------------
def test_journal_lines_contain_no_names(journal_stream):
    canaries = ["WATCH-BUILD-2-J1", "WATCH-BUILD-2-J2", "WATCH-BUILD-2-J3"]
    ingest_node(FakeNode((0, 0, 10, 10), name=canaries[0], role="password text"), "w1")
    ingest_node(FakeNode((0, 0, 10, 10), name=f"password {canaries[1]}", role="entry"), "w1")
    ingest_delta({"role": "password text", "name": canaries[2], "rect": [0, 0, 10, 10]}, "w1")
    store = WatchStore()
    store.upsert_window(_window("w1"))
    store.apply_nodes("w1", 5, [])  # seq gap → stale journal line
    text = journal_stream.getvalue()
    for canary in canaries:
        assert canary not in text
    # Metadata lines exist (tombstone + stale), names do not.
    assert "tombstone" in text
    assert "stale" in text


# ---------------------------------------------------------------------------
# WatchStore: caps, seq-gap → stale, RAM-only
# ---------------------------------------------------------------------------
def test_store_caps_windows():
    store = WatchStore()
    for i in range(128):
        store.upsert_window(_window(f"w{i}", synced_at=float(i)))
    assert store.window_count() == 128
    store.upsert_window(_window("w128", synced_at=999.0))
    assert store.window_count() == 128
    assert store.get_window("w128") is not None
    # Oldest-synced evicted.
    assert store.get_window("w0") is None


def test_store_caps_per_window():
    store = WatchStore()
    store.upsert_window(_window("w1"))
    nodes = [Node(window="w1", parent=None, role="push button",
                  rect=(0.0, 0.0, 10.0, 10.0), name=f"N{i}") for i in range(300)]
    assert store.apply_nodes("w1", 1, nodes) is True
    assert len(store.nodes_for_window("w1")) == 256
    assert store.total_nodes() == 256


def test_store_caps_total():
    store = WatchStore()
    # 79 windows × 256 = 20224 > 20000 → total cap engages.
    for w in range(79):
        key = f"w{w}"
        store.upsert_window(_window(key, synced_at=float(w)))
        nodes = [Node(window=key, parent=None, role="push button",
                      rect=(0.0, 0.0, 10.0, 10.0), name="N") for _ in range(256)]
        assert store.apply_nodes(key, 1, nodes) is True
    assert store.total_nodes() <= 20_000


def test_seq_gap_marks_stale():
    store = WatchStore()
    store.upsert_window(_window("w1", seq=0))
    nodes = [Node(window="w1", parent=None, role="push button",
                  rect=(0.0, 0.0, 10.0, 10.0), name="Cancel")]
    assert store.apply_nodes("w1", 1, nodes) is True
    assert store.get_window("w1").state == "live"
    # Gap: 1 → 5 (missed 2,3,4).
    assert store.apply_nodes("w1", 5, nodes) is True
    assert store.get_window("w1").state == "stale"
    assert store.is_stale("w1") is True
    # Duplicate/out-of-order ignored.
    assert store.apply_nodes("w1", 5, nodes) is False
    assert store.apply_nodes("w1", 3, nodes) is False
    # Resync clears stale.
    assert store.mark_live("w1") is True
    assert store.get_window("w1").state == "live"


def test_view_excludes_stale_and_clear():
    store = WatchStore()
    store.upsert_window(_window("w1"))
    store.upsert_window(_window("w2"))
    n1 = Node(window="w1", parent=None, role="push button",
              rect=(0.0, 0.0, 10.0, 10.0), name="A")
    n2 = Node(window="w2", parent=None, role="push button",
              rect=(0.0, 0.0, 10.0, 10.0), name="B")
    store.apply_nodes("w1", 1, [n1])
    store.apply_nodes("w2", 1, [n2])
    assert len(store.view()) == 2
    store.mark_stale("w2")
    assert store.view() == (n1,)
    store.clear()
    assert store.window_count() == 0
    assert store.total_nodes() == 0
    assert store.view() == ()


def test_store_is_ram_only_no_serialisation():
    """No file/pickle/db imports in either module (RAM-only, never serialised)."""
    for name in ("watch_ingest.py", "watch_store.py"):
        source = (REPO / "src/assistant" / name).read_text()
        tree = ast.parse(source, filename=name)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
                if node.level:
                    imported.add(f"level{node.level}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
        assert "pickle" not in imported, name
        assert "sqlite3" not in imported, name
        assert "json" not in imported or "dump" not in source, name
        # No open()/Path.write calls.
        assert ".write_text" not in source and ".write_bytes" not in source, name
        assert "open(" not in source, name


# ---------------------------------------------------------------------------
# rail 4: AST import test — no authority / provider paths
# ---------------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                out.add(f"assistant.{node.module}" if node.module else "assistant")
            elif node.module:
                out.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
    return out


@pytest.mark.parametrize("name", ["watch_ingest.py", "watch_store.py"])
def test_no_authority_or_provider_imports(name):
    path = REPO / "src/assistant" / name
    imported = _imports(path)
    offenders = imported & FORBIDDEN_IMPORTS
    assert not offenders, f"{name} imports forbidden: {offenders}"
    stdlib_offenders = {m for m in imported if m.split(".")[0] in FORBIDDEN_STDLIB}
    assert not stdlib_offenders, f"{name} imports network: {stdlib_offenders}"
    # No subprocess / socket / http calls either.
    source = path.read_text()
    for needle in ("subprocess", "socket.", "urllib", "requests.", "httpx"):
        assert needle not in source, f"{name} contains {needle}"
