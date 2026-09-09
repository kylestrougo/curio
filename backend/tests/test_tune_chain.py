"""The daily self-tuning chain.

tune-chain rewrites live configuration from cron, unattended, so what matters
is that it trusts the right evidence: production stats first, a fresh run of
failures over any amount of past glory, and a strict live-call budget so it
can never rate-limit itself into a wrong answer. The September incident is
pinned as a regression test: a retired chain head kept its slot for days while
the stats table already knew a 95%-ok model was sitting right there.
"""
import pytest
import requests

from curio import cli as cli_mod
from curio.db import execute
from curio.llm import CONFIG_KEY_CHAIN, get_chain, set_config_json

# A parsed page that honours the contract, for successful probe stubs.
GOOD_PAGE = {
    "title": "Why do we dream?",
    "blurb": "Nobody fully knows, and the leading theories disagree wildly.",
    "buttons": [{"label": f"door {i}", "type": "fact"} for i in range(5)],
}


def seed(model, ok=0, fails=0, latency=1000, hours_ago=2, error="HTTP 404: gone"):
    """Insert model_stats rows a given distance into the past."""
    for _ in range(ok):
        execute(
            "INSERT INTO model_stats (model, intent, ok, latency_ms, created_at) "
            "VALUES (?, 'page', 1, ?, datetime('now', ?))",
            (model, latency, f"-{hours_ago} hours"),
        )
    for _ in range(fails):
        execute(
            "INSERT INTO model_stats (model, intent, ok, latency_ms, error, created_at) "
            "VALUES (?, 'page', 0, NULL, ?, datetime('now', ?))",
            (model, error, f"-{hours_ago} hours"),
        )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture()
def catalogue(monkeypatch):
    def install(ids):
        monkeypatch.setattr(
            "curio.llm.list_free_models", lambda: [{"id": i} for i in ids]
        )

    return install


@pytest.fixture()
def probes(monkeypatch):
    """Stub live probes: model id → latency ms (success) or error string."""
    calls = []

    def install(table):
        def fake(mid, system, user, intent="bench", **kw):
            calls.append(mid)
            spec = table.get(mid, "HTTP 404: model gone")
            if isinstance(spec, str):
                return {"ok": False, "raw": "", "parsed": None,
                        "latencyMs": 50, "error": spec}
            return {"ok": True, "raw": "", "parsed": GOOD_PAGE,
                    "latencyMs": spec, "error": None}

        monkeypatch.setattr("curio.llm.generate_raw", fake)

    install.calls = calls
    return install


def run(app, *args):
    return app.test_cli_runner().invoke(cli_mod.tune_chain_command, list(args))


class TestTheSeptemberIncident:
    def test_freshly_dead_head_is_evicted_despite_a_glowing_history(
        self, app, catalogue, probes
    ):
        # 'dead' has three days of excellent stats — and failed every call
        # today, because the provider retired it. Its history would rank it
        # first; the eviction rule must throw it out anyway, and the model
        # the stats table always favoured must take the head.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["dead:free", "slowbackup:free"])
            seed("dead:free", ok=30, latency=500, hours_ago=40)
            seed("dead:free", fails=4, hours_ago=2)
            seed("laguna:free", ok=40, fails=2, latency=1200, hours_ago=40)
            seed("gemma:free", ok=8, fails=2, latency=6400, hours_ago=40)
            seed("slowbackup:free", ok=4, latency=52000, hours_ago=2)
        catalogue([])
        probes({})

        res = run(app)

        assert res.exit_code == 0
        assert probes.calls == []  # everyone had enough evidence already
        with app.app_context():
            assert get_chain() == ["laguna:free", "gemma:free", "slowbackup:free"]


class TestTheWideWindow:
    def test_good_models_older_than_the_window_are_still_found(
        self, app, catalogue, probes
    ):
        # The day-after-the-incident case: the good model left the chain days
        # ago so its stats aged out of the normal window, and the probe that
        # would re-prove it is rate-limited. Last week still knows the answer.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["dead:free"])
            seed("dead:free", fails=4, hours_ago=2)
            seed("laguna:free", ok=40, fails=2, latency=1200, hours_ago=100)
            seed("gemma:free", ok=8, fails=2, latency=6400, hours_ago=100)
        catalogue([])
        probes({"dead:free": "HTTP 429: slow down"})

        res = run(app)

        assert res.exit_code == 0
        assert "widening the window" in res.output
        with app.app_context():
            assert get_chain() == ["laguna:free", "gemma:free"]

    def test_widening_cannot_resurrect_a_model_that_died_today(
        self, app, catalogue, probes
    ):
        # The wide window is a memory, not an amnesty: the 24h eviction rule
        # still applies to whatever it remembers.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["dead:free"])
            seed("dead:free", ok=40, latency=500, hours_ago=100)
            seed("dead:free", fails=4, hours_ago=2)
            seed("laguna:free", ok=40, latency=1200, hours_ago=100)
            seed("gemma:free", ok=8, latency=6400, hours_ago=100)
        catalogue([])
        probes({})

        run(app)

        with app.app_context():
            assert get_chain() == ["laguna:free", "gemma:free"]

    def test_month_old_evidence_is_the_last_resort(self, app, catalogue, probes):
        # The full Pi state of 2026-09-09 18:30Z, as a regression test: the
        # good models' record is older than even the 168h window, the chain
        # head is truly dead, and the favourite carries fresh 429 scars from
        # a benchmark storm. The 429s must count for nothing and the 720h
        # window must find the answer — with zero successful live calls.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["dead:free"])
            seed("dead:free", fails=4, hours_ago=2)
            seed("laguna:free", ok=40, fails=2, latency=1200, hours_ago=200)
            seed("laguna:free", fails=3, hours_ago=2, error="HTTP 429: Provider returned error")
            seed("gemma:free", ok=8, fails=2, latency=6400, hours_ago=200)
        catalogue([])
        probes({"dead:free": "HTTP 429: slow down"})

        res = run(app)

        assert res.exit_code == 0
        assert "widening the window to 720h" in res.output
        with app.app_context():
            assert get_chain() == ["laguna:free", "gemma:free"]

    def test_widening_stops_at_the_first_window_that_answers(
        self, app, catalogue, probes
    ):
        # 168h data must be ranked as 168h data, not fall through to 720h
        # where a month-old relic could outrank it.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["dead:free"])
            seed("dead:free", fails=4, hours_ago=2)
            seed("a:free", ok=5, latency=2000, hours_ago=100)
            seed("b:free", ok=5, latency=3000, hours_ago=100)
            seed("relic:free", ok=20, latency=100, hours_ago=500)
        catalogue([])
        probes({})

        res = run(app)

        assert "widening the window to 168h" in res.output
        assert "720h" not in res.output
        with app.app_context():
            assert get_chain() == ["a:free", "b:free"]


class TestRateLimitsAreNotEvidence:
    def test_429_rows_neither_downrate_nor_evict(self, app, catalogue, probes):
        # Three fresh 429s used to trip the eviction rule (>=3 calls, 0 ok)
        # against the very model the account was rate-limited while probing.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=10, latency=1000, hours_ago=2)
            seed("b:free", ok=10, latency=500, hours_ago=30)
            seed("b:free", fails=3, hours_ago=2, error="HTTP 429: Provider returned error")
        catalogue([])
        probes({})

        run(app)

        with app.app_context():
            assert get_chain() == ["b:free", "a:free"]

    def test_429_rows_alone_cannot_make_a_model_eligible(
        self, app, catalogue, probes
    ):
        # They are nothing, not something: skipped entirely, not counted as
        # calls that could satisfy the minimum-evidence bar.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=10, latency=1000, hours_ago=2)
            seed("x:free", fails=10, hours_ago=2, error="HTTP 429: slow down")
        catalogue([])
        probes({})

        res = run(app)

        assert res.exit_code == 1  # a alone is not a chain
        with app.app_context():
            assert get_chain() == ["a:free"]

    def test_a_rate_limited_probe_is_not_merged_as_evidence(
        self, app, catalogue, probes
    ):
        # A newcomer one call short of eligibility gets probed; the probe
        # 429s. That must leave it one call short — merging the 429 as a
        # plain failure would hand it its third call and a seat in the chain.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=5, latency=1000, hours_ago=2)
            seed("b:free", ok=2, latency=3000, hours_ago=30)
        catalogue(["b:free"])
        probes({"b:free": "HTTP 429: slow down"})

        res = run(app)

        assert probes.calls == ["b:free"]
        assert res.exit_code == 1  # b stayed two calls short of a verdict
        with app.app_context():
            assert get_chain() == ["a:free"]


class TestHysteresis:
    def test_a_near_tie_keeps_the_incumbent_first(self, app, catalogue, probes):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=10, latency=1000, hours_ago=2)
            seed("b:free", ok=10, latency=900, hours_ago=2)
        catalogue([])
        probes({})

        run(app)

        with app.app_context():
            assert get_chain() == ["a:free", "b:free"]

    def test_a_clearly_faster_outsider_takes_the_head(self, app, catalogue, probes):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=10, latency=1000, hours_ago=2)
            seed("b:free", ok=10, latency=400, hours_ago=2)
        catalogue([])
        probes({})

        run(app)

        with app.app_context():
            assert get_chain() == ["b:free", "a:free"]


class TestRestraint:
    def test_thin_evidence_leaves_the_chain_alone(self, app, catalogue, probes):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=2, latency=1000, hours_ago=2)
        catalogue([])
        probes({"a:free": "HTTP 500: bad day"})

        res = run(app)

        assert res.exit_code == 1
        assert "leaving the chain alone" in res.output
        with app.app_context():
            assert get_chain() == ["a:free"]

    def test_dry_run_reports_without_writing(self, app, catalogue, probes):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["slow:free"])
            seed("slow:free", ok=5, latency=9000, hours_ago=2)
            seed("fast:free", ok=5, latency=100, hours_ago=2)
        catalogue([])
        probes({})

        res = run(app, "--dry-run")

        assert "would set" in res.output
        with app.app_context():
            assert get_chain() == ["slow:free"]

    def test_a_rate_limit_storm_judges_nothing(self, app, catalogue, probes):
        # Every probe 429ing means the account is rate-limited, not that
        # every model is broken. The run must say so and rank on stats only.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free", "b:free"])
            seed("a:free", ok=5, latency=1000, hours_ago=2)
            seed("b:free", ok=5, latency=2000, hours_ago=2)
        catalogue(["x:free", "y:free"])
        probes({"x:free": "HTTP 429: slow down", "y:free": "HTTP 429: slow down"})

        res = run(app)

        assert res.exit_code == 0
        assert "count for nothing" in res.output
        assert "no change" in res.output
        with app.app_context():
            assert get_chain() == ["a:free", "b:free"]

    def test_catalogue_down_still_ranks_from_stats(self, app, monkeypatch, probes):
        # The DNS blip that used to dump a traceback into chain.log: the
        # catalogue is only for discovery, so losing it must not stop the
        # stats-based retune (or crash).
        def boom():
            raise requests.ConnectionError("resolve openrouter.ai: no such host")

        monkeypatch.setattr("curio.llm.list_free_models", boom)
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["slow:free"])
            seed("slow:free", ok=5, latency=9000, hours_ago=2)
            seed("fast:free", ok=5, latency=100, hours_ago=2)
        probes({})

        res = run(app)

        assert res.exit_code == 0
        assert "catalogue unreachable" in res.output
        assert "Traceback" not in res.output
        with app.app_context():
            assert get_chain() == ["fast:free", "slow:free"]


class TestProbes:
    def test_budget_caps_the_live_calls(self, app, catalogue, probes):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free"])
            seed("a:free", ok=5, latency=1000, hours_ago=2)
        catalogue([f"x{i}:free" for i in range(10)])
        probes({f"x{i}:free": 800 for i in range(10)})

        run(app)

        assert len(probes.calls) == cli_mod.TUNE_PROBE_BUDGET

    def test_targets_are_starving_incumbents_then_the_daily_rotation(self):
        # Pure function: incumbents lacking evidence come first, the
        # catalogue rotates deterministically by day, chain members are
        # never in the rotation.
        stats = {"a": {"calls": 5, "ok": 5, "lat": [1000]}}
        assert cli_mod._probe_targets(["a", "b"], stats, ["x", "y", "z"], day=0) == \
            ["b", "x", "y", "z"]
        assert cli_mod._probe_targets(["a", "b"], stats, ["x", "y", "z"], day=1) == \
            ["b", "y", "z", "x"]
        assert cli_mod._probe_targets(["a"], stats, ["a", "x"], day=0) == ["x"]

    def test_probe_results_feed_the_ranking(self, app, catalogue, probes):
        # A quiet backup one call short of eligibility gets probed, and the
        # probe's success is what tips it into keeping its place.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["a:free", "b:free"])
            seed("a:free", ok=5, latency=1000, hours_ago=2)
            seed("b:free", ok=2, latency=3000, hours_ago=30)
        catalogue([])
        probes({"b:free": 3000})

        res = run(app)

        assert probes.calls == ["b:free"]
        assert res.exit_code == 0
        with app.app_context():
            assert get_chain() == ["a:free", "b:free"]
