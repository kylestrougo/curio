"""`flask warm-cache` — overnight pre-generation of the starter doors.

Runs unattended from cron, so restraint is the property to pin: it only
generates what isn't cached, it stops early when the chain looks dead, and a
second run does nothing when the first covered everything.
"""
import json

import pytest

from curio import cli as cli_mod
from curio import llm, pagecache
from curio.db import query

PAGE = {
    "title": "A title",
    "blurb": "A blurb worth caching.",
    "buttons": [{"label": f"door {i}", "type": "fact"} for i in range(5)],
}


@pytest.fixture()
def pool(monkeypatch, tmp_path):
    """Point warm-cache at a small temp pool instead of shared/seed-pool.json.

    The command resolves BASE_DIR.parent / "shared" / "seed-pool.json" at call
    time (the import is inside the function), so patching config.BASE_DIR is
    enough to redirect it.
    """
    def install(seeds):
        import curio.config as config_mod

        class FakeBase:
            parent = tmp_path

        monkeypatch.setattr(config_mod, "BASE_DIR", FakeBase)
        (tmp_path / "shared").mkdir(exist_ok=True)
        (tmp_path / "shared" / "seed-pool.json").write_text(json.dumps(seeds))

    return install


def run(app, *args):
    return app.test_cli_runner().invoke(cli_mod.warm_cache_command, list(args))


class TestWarmCache:
    def test_warms_uncached_doors(self, app, pool, monkeypatch):
        pool([{"label": "A", "type": "fact"}, {"label": "B", "type": "topic"}])
        monkeypatch.setattr(llm, "_post", lambda *a, **k: json.dumps(PAGE))

        res = run(app)
        assert "warmed=2" in res.output
        with app.app_context():
            assert pagecache.has_page("A", "fact")
            assert pagecache.has_page("B", "topic")

    def test_second_run_skips_everything(self, app, pool, monkeypatch):
        pool([{"label": "A", "type": "fact"}])
        monkeypatch.setattr(llm, "_post", lambda *a, **k: json.dumps(PAGE))
        run(app)

        # Any further model call would mean the skip check is broken.
        def explode(*a, **k):
            raise AssertionError("re-warmed a cached door")

        monkeypatch.setattr(llm, "_post", explode)
        res = run(app)
        assert "warmed=0" in res.output
        assert "already_cached=1" in res.output

    def test_limit_caps_the_run(self, app, pool, monkeypatch):
        pool([{"label": f"L{i}", "type": "topic"} for i in range(6)])
        monkeypatch.setattr(llm, "_post", lambda *a, **k: json.dumps(PAGE))
        res = run(app, "--limit", "2")
        assert "warmed=2" in res.output
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"] == 2

    def test_dead_chain_aborts_early(self, app, pool, monkeypatch):
        pool([{"label": f"L{i}", "type": "topic"} for i in range(10)])
        attempts = []

        def dead(*a, **k):
            attempts.append(1)
            raise llm.LLMError("HTTP 429")

        monkeypatch.setattr(llm, "_post", dead)
        res = run(app)
        assert "chain looks dead" in res.output
        # 3 doors × the configured chain, not all 10 doors.
        chain_len = 0
        with app.app_context():
            chain_len = len(llm.get_chain())
        assert len(attempts) <= 3 * chain_len

    def test_warm_calls_never_touch_user_quota(self, app, pool, monkeypatch):
        pool([{"label": "A", "type": "fact"}])
        monkeypatch.setattr(llm, "_post", lambda *a, **k: json.dumps(PAGE))
        run(app)
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM usage_counters", (), one=True)["n"] == 0


class TestSeedPoolContract:
    """shared/seed-pool.json is read by both the frontend bundle and this CLI —
    a malformed entry breaks one of them silently. Pin the shape."""

    def test_real_pool_is_valid(self):
        from curio.config import BASE_DIR
        pool = json.loads((BASE_DIR.parent / "shared" / "seed-pool.json").read_text())
        assert len(pool) >= 50
        labels = set()
        for s in pool:
            assert s["label"].strip(), s
            assert s["type"] in {"fact", "question", "topic"}, s
            assert s["domain"].strip(), s
            assert s["label"] not in labels, f"duplicate: {s['label']}"
            labels.add(s["label"])
