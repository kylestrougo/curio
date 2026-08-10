"""The page cache: a tap anyone has tapped before must skip the LLM entirely.

The important properties are negative ones — a hit makes NO model call and
burns NO quota, surprise pages never touch the cache, and failures never
poison it.
"""
import json

import pytest

from curio import llm, pagecache
from curio.db import execute, query


@pytest.fixture()
def stub_page(monkeypatch):
    payload = {
        "title": "Meanders",
        "blurb": "Rivers wander because straight lines are unstable.",
        "buttons": [{"label": f"door {i}", "type": "fact"} for i in range(5)],
    }
    monkeypatch.setattr(llm, "_post", lambda *a, **k: json.dumps(payload))
    return payload


def _gen_count(app):
    with app.app_context():
        row = query(
            "SELECT SUM(count) AS n FROM usage_counters WHERE subject LIKE 'ip:%'",
            (), one=True,
        )
        return row["n"] or 0


class TestCacheReadWrite:
    def test_miss_generates_then_populates(self, client, app, stub_page):
        r = client.post("/api/page", json={"label": "Why do rivers meander?", "kind": "question"})
        assert r.status_code == 200
        with app.app_context():
            row = query("SELECT * FROM page_cache", (), one=True)
            assert row["title"] == "Meanders"
            assert row["kind"] == "question"

    def test_hit_makes_no_model_call_and_burns_no_quota(self, client, app, stub_page):
        client.post("/api/page", json={"label": "Why do rivers meander?", "kind": "question"})
        burned = _gen_count(app)

        # From here on, any model call is a bug.
        def explode(*a, **k):
            raise AssertionError("cache hit reached the LLM")

        import unittest.mock as mock
        with mock.patch.object(llm, "_post", explode):
            r = client.post("/api/page", json={"label": "Why do rivers meander?", "kind": "question"})
        assert r.status_code == 200
        assert r.get_json()["title"] == "Meanders"
        assert _gen_count(app) == burned  # quota counts generations, not requests

    def test_key_normalises_case_and_whitespace(self, client, app, stub_page):
        client.post("/api/page", json={"label": "The Radium Girls", "kind": "topic"})
        import unittest.mock as mock
        with mock.patch.object(llm, "_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError())):
            r = client.post("/api/page", json={"label": "  the radium girls ", "kind": "topic"})
        assert r.status_code == 200

    def test_same_label_different_kind_is_a_different_entry(self, client, app, stub_page):
        client.post("/api/page", json={"label": "Honey", "kind": "topic"})
        client.post("/api/page", json={"label": "Honey", "kind": "fact"})
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"] == 2

    def test_surprise_neither_reads_nor_writes(self, client, app, stub_page):
        r = client.post("/api/page", json={"surprise": True})
        assert r.status_code == 200
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"] == 0

    def test_failed_generation_caches_nothing(self, client, app, monkeypatch):
        monkeypatch.setattr(llm, "_post", lambda *a, **k: "not json at all")
        r = client.post("/api/page", json={"label": "x", "kind": "fact"})
        assert r.status_code == 502
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"] == 0

    def test_hits_are_counted(self, client, app, stub_page):
        client.post("/api/page", json={"label": "Honey", "kind": "topic"})
        client.post("/api/page", json={"label": "Honey", "kind": "topic"})
        client.post("/api/page", json={"label": "Honey", "kind": "topic"})
        with app.app_context():
            assert query("SELECT hits FROM page_cache", (), one=True)["hits"] == 2


class TestPrune:
    def test_prune_removes_only_the_old(self, app):
        with app.app_context():
            pagecache.store_page("old", "topic", "t", "b", [])
            pagecache.store_page("new", "topic", "t", "b", [])
            execute(
                "UPDATE page_cache SET created_at = datetime('now', '-9 days') "
                "WHERE label = 'old'"
            )
            assert pagecache.prune(days=7) == 1
            assert pagecache.has_page("new", "topic")
            assert not pagecache.has_page("old", "topic")
