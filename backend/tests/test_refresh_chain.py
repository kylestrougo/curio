"""The self-healing model chain.

This command rewrites live configuration from cron, unattended, so its
restraint matters more than its cleverness. Two properties are worth pinning:
it repairs a chain that has stopped working, and it declines to rewrite one
that still works just because something else measured faster. Speed is the
only thing a benchmark can judge, and it says nothing about whether the pages
are worth reading.
"""
import pytest

from curio import cli as cli_mod
from curio.llm import CONFIG_KEY_CHAIN, get_chain, set_config_json


@pytest.fixture()
def bench(monkeypatch):
    """Stub the benchmark: map model id → latency, or None for 'failed'."""
    calls = []

    def install(table):
        def fake(ids, repeat, echo=None):
            calls.append(list(ids))
            return [
                (table.get(i), i, None if table.get(i) else "stubbed failure")
                for i in ids
            ]

        monkeypatch.setattr(cli_mod, "_bench", fake)

    install.calls = calls
    return install


@pytest.fixture()
def catalogue(monkeypatch):
    def install(ids):
        monkeypatch.setattr(
            "curio.llm.list_free_models", lambda: [{"id": i} for i in ids]
        )

    return install


def run(app, *args):
    return app.test_cli_runner().invoke(cli_mod.refresh_chain_command, list(args))


class TestLeavesWorkingChainsAlone:
    def test_healthy_chain_is_not_touched(self, app, bench, catalogue):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["slow:free"])
        bench({"slow:free": 9000})
        catalogue(["fast:free"])  # faster, and deliberately ignored

        res = run(app, "--repeat", "1")

        assert "healthy" in res.output
        with app.app_context():
            assert get_chain() == ["slow:free"]

    def test_force_re_ranks_a_healthy_chain(self, app, bench, catalogue):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["slow:free"])
        bench({"slow:free": 9000, "fast:free": 100})
        catalogue(["fast:free", "slow:free"])

        run(app, "--force", "--repeat", "1", "--top", "2")

        with app.app_context():
            assert get_chain() == ["fast:free", "slow:free"]


class TestRepairsBrokenChains:
    def test_dead_chain_is_rebuilt_fastest_first(self, app, bench, catalogue):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["retired:free"])
        bench({"mid:free": 500, "quick:free": 100, "slow:free": 900})
        catalogue(["mid:free", "quick:free", "slow:free"])

        res = run(app, "--repeat", "1", "--top", "2")

        assert "chain updated" in res.output
        with app.app_context():
            assert get_chain() == ["quick:free", "mid:free"]

    def test_dry_run_reports_without_writing(self, app, bench, catalogue):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["retired:free"])
        bench({"quick:free": 100})
        catalogue(["quick:free"])

        res = run(app, "--dry-run", "--repeat", "1")

        assert "would set" in res.output
        with app.app_context():
            assert get_chain() == ["retired:free"]


class TestRefusesToMakeThingsWorse:
    def test_keeps_a_dead_chain_when_nothing_else_works(self, app, bench, catalogue):
        # An empty chain makes every tap fail. A stale one at least recovers
        # by itself if the provider comes back.
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["retired:free"])
        bench({})
        catalogue(["also-broken:free"])

        res = run(app, "--repeat", "1")

        assert res.exit_code == 1
        with app.app_context():
            assert get_chain() == ["retired:free"]

    def test_keeps_the_chain_when_the_catalogue_is_empty(self, app, bench, catalogue):
        with app.app_context():
            set_config_json(CONFIG_KEY_CHAIN, ["retired:free"])
        bench({})
        catalogue([])

        res = run(app, "--repeat", "1")

        assert res.exit_code == 1
        with app.app_context():
            assert get_chain() == ["retired:free"]
