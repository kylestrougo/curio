"""The door-speed diagnostics: diagnose-doors and bench-experiments.

These run unattended interpretation on the user's behalf, so what's pinned is
the *judgement*: a regression is called a regression, fallthrough is caught,
an empty cache is flagged, experiment rounds interleave fairly, and a
fast-but-broken arm can never win.
"""
import json

import pytest

from curio import cli as cli_mod
from curio import llm
from curio.db import execute

GOOD_PAGE = json.dumps(
    {
        "title": "Why do we dream?",
        "blurb": "Dreams weave memory into narrative. They may consolidate learning overnight.",
        "buttons": [{"label": f"door {i}", "type": "fact"} for i in range(5)],
    }
)


def _seed_stat(app, model, ok, latency, created_at, intent="page"):
    with app.app_context():
        execute(
            "INSERT INTO model_stats (model, intent, ok, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (model, intent, 1 if ok else 0, latency, created_at),
        )


def run_diagnose(app, *args):
    return app.test_cli_runner().invoke(cli_mod.diagnose_doors_command, list(args))


def run_bench(app, *args):
    return app.test_cli_runner().invoke(cli_mod.bench_experiments_command, list(args))


BOUNDARY = "2026-08-10 00:00:00"


class TestDiagnoseDoors:
    def test_regression_is_called_out(self, app):
        for i in range(4):
            _seed_stat(app, "m:free", True, 3000, "2026-08-09 10:0%d:00" % i)
            _seed_stat(app, "m:free", True, 9000, "2026-08-10 10:0%d:00" % i)
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "REGRESSION" in res.output
        assert "3000ms → 9000ms" in res.output

    def test_steady_model_is_cleared(self, app):
        for i in range(4):
            _seed_stat(app, "m:free", True, 3000, "2026-08-09 10:0%d:00" % i)
            _seed_stat(app, "m:free", True, 3100, "2026-08-10 10:0%d:00" % i)
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "no regression" in res.output
        assert "REGRESSION" not in res.output

    def test_fallthrough_on_first_chain_model(self, app):
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["dead:free", "backup:free"])
        for i in range(5):
            _seed_stat(app, "dead:free", False, 45000, "2026-08-10 10:0%d:00" % i)
            _seed_stat(app, "backup:free", True, 4000, "2026-08-10 10:0%d:30" % i)
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "FALLTHROUGH" in res.output
        assert "dead:free" in res.output

    def test_empty_cache_is_flagged(self, app):
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "cache is EMPTY" in res.output

    def test_populated_cache_is_reported(self, app):
        with app.app_context():
            from curio import pagecache
            pagecache.store_page("a door", "topic", "T", "B", [])
            execute("UPDATE page_cache SET hits = 7")
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "1 pages, 7 hits" in res.output

    def test_only_page_intent_is_read(self, app):
        # bench and email traffic must not contaminate the door diagnosis.
        for i in range(4):
            _seed_stat(app, "m:free", True, 100, "2026-08-09 10:0%d:00" % i, intent="bench")
            _seed_stat(app, "m:free", True, 9000, "2026-08-10 10:0%d:00" % i, intent="bench")
        res = run_diagnose(app, "--since", BOUNDARY)
        assert "REGRESSION" not in res.output


class TestBenchExperiments:
    def _stub(self, monkeypatch, latencies_by_arm=None, fail_arms=()):
        """Stub _post; record call order via json_mode/temperature fingerprints."""
        calls = []

        def fake_post(model, system, user, max_tokens, json_mode, temperature=None, timeout=None):
            calls.append({"json_mode": json_mode, "temperature": temperature,
                          "max_tokens": max_tokens, "system": system})
            key = self._arm_of(system, json_mode, temperature, max_tokens)
            if key in fail_arms:
                raise llm.LLMError("HTTP 429")
            return GOOD_PAGE

        monkeypatch.setattr(llm, "_post", fake_post)
        return calls

    @staticmethod
    def _arm_of(system, json_mode, temperature, max_tokens):
        if not json_mode:
            return "no-json-mode"
        if temperature is None:
            return "no-temp"
        if max_tokens == 600:
            return "max-600"
        if "Never invent" not in system and "micro-articles" not in system:
            return "old-persona"
        if "micro-articles" in system:
            return "slim-prompt"
        return "baseline"

    def test_all_arms_run_and_interleave(self, app, monkeypatch):
        calls = self._stub(monkeypatch)
        res = run_bench(app, "--model", "m:free", "--repeat", "2")
        assert res.exit_code == 0
        assert len(calls) == 12  # 6 arms × 2 rounds
        # Interleaved: the first 6 calls cover all 6 arms, not one arm repeated.
        first_round = {self._arm_of(c["system"], c["json_mode"], c["temperature"], c["max_tokens"])
                       for c in calls[:6]}
        assert len(first_round) == 6

    def test_report_contains_every_arm(self, app, monkeypatch):
        self._stub(monkeypatch)
        res = run_bench(app, "--model", "m:free", "--repeat", "1")
        for key in ("baseline", "no-temp", "no-json-mode", "old-persona", "slim-prompt", "max-600"):
            assert key in res.output

    def test_failing_arm_cannot_win(self, app, monkeypatch):
        self._stub(monkeypatch, fail_arms={"no-json-mode"})
        res = run_bench(app, "--model", "m:free", "--repeat", "2")
        assert "no-json-mode wins" not in res.output

    def test_broken_reply_counts_as_failure(self, app, monkeypatch):
        def fake_post(model, system, user, max_tokens, json_mode, temperature=None, timeout=None):
            return json.dumps({"title": "T", "blurb": "B", "buttons": []})  # off-contract

        monkeypatch.setattr(llm, "_post", fake_post)
        res = run_bench(app, "--model", "m:free", "--repeat", "1")
        assert "off-contract" in res.output
        assert "wins" not in res.output

    def test_nothing_recorded_to_model_stats(self, app, monkeypatch):
        self._stub(monkeypatch)
        run_bench(app, "--model", "m:free", "--repeat", "1")
        with app.app_context():
            from curio.db import query
            assert query("SELECT COUNT(*) AS n FROM model_stats", (), one=True)["n"] == 0

    def test_total_outage_aborts_with_advice(self, app, monkeypatch):
        def dead(*a, **k):
            raise llm.LLMError("HTTP 503")

        monkeypatch.setattr(llm, "_post", dead)
        res = run_bench(app, "--model", "m:free", "--repeat", "3")
        assert "down, not slow" in res.output
        assert res.exit_code == 1
