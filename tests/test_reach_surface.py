"""Eye-check 6: Reason-gated interestingness -> initiative.raise_knock(kind='finding')."""

from __future__ import annotations

from assistant.reach import FetchedDoc, InterestingnessGate


class _StubInitiative:
    def __init__(self):
        self.knocks: list[dict] = []

    def raise_knock(self, **kwargs):
        self.knocks.append(kwargs)
        return kwargs


def _doc(title: str, text: str, url: str = "https://example.com/news") -> FetchedDoc:
    return FetchedDoc(
        url=url,
        final_url=url,
        channel="web",
        status_code=200,
        content_type="text/plain",
        title=title,
        text=text,
        excerpt=text[:120],
    )


def test_interestingness_requires_stated_interest_and_dedups():
    gate = InterestingnessGate()
    init = _StubInitiative()

    unrelated = _doc("Gardening tips", "How to water tomatoes in summer.")
    assert gate.evaluate(unrelated, interests=["python release"], initiative=init) is None
    assert init.knocks == []

    relevant = _doc("Python 3.14 release", "Python 3.14 release notes are out.")
    knock = gate.evaluate(relevant, interests=["python release"], initiative=init)
    assert knock is not None
    assert knock["kind"] == "finding"
    assert knock["referent"] == "https://example.com/news"
    assert "https://example.com/news" in knock["reason"]

    # Novelty dedup: same (url, sha256) does not re-knock
    assert gate.evaluate(relevant, interests=["python release"], initiative=init) is None
    assert len(init.knocks) == 1
