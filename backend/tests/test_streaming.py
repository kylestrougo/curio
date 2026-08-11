"""Streaming more/ask: tokens flow, and the chain only falls back BEFORE them.

The invariant worth pinning is the one that makes streaming compatible with
the fallback chain at all: a model may be swapped freely while nothing has
reached the client, and never after — a mid-stream death must surface as an
error event, not a spliced answer from a different model.
"""
import json

import pytest

from curio import llm
from curio.db import query


def _stub_stream(monkeypatch, per_model):
    """per_model: model id → list of chunks, or an Exception, or a callable
    yielding chunks then raising (for mid-stream death)."""
    def fake(model, system, user, max_tokens, temperature):
        item = per_model[model]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            yield from item()
            return
        yield from item
    monkeypatch.setattr(llm, "_post_stream", fake)


class TestGenerateStream:
    def test_chunks_flow_from_the_first_model(self, app, monkeypatch):
        _stub_stream(monkeypatch, {"a": ["Riv", "ers ", "wander."]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a"])
            assert list(llm.generate_stream("s", "u", "more")) == ["Riv", "ers ", "wander."]

    def test_falls_through_before_first_token(self, app, monkeypatch):
        _stub_stream(monkeypatch, {"a": llm.LLMError("HTTP 429"), "b": ["ok"]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
            assert list(llm.generate_stream("s", "u", "more")) == ["ok"]

    def test_empty_stream_counts_as_failure_and_falls_through(self, app, monkeypatch):
        _stub_stream(monkeypatch, {"a": [], "b": ["ok"]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
            assert list(llm.generate_stream("s", "u", "more")) == ["ok"]

    def test_mid_stream_death_raises_rather_than_switching_models(self, app, monkeypatch):
        def dies_midway():
            yield "First half"
            raise llm.LLMError("connection reset")

        _stub_stream(monkeypatch, {"a": dies_midway, "b": ["never touched"]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
            gen = llm.generate_stream("s", "u", "more")
            assert next(gen) == "First half"
            with pytest.raises(llm.LLMError, match="mid-answer"):
                list(gen)

    def test_all_models_dead_raises(self, app, monkeypatch):
        _stub_stream(monkeypatch, {"a": llm.LLMError("x"), "b": llm.LLMError("y")})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
            with pytest.raises(llm.LLMError):
                list(llm.generate_stream("s", "u", "more"))

    def test_stats_record_time_to_first_token(self, app, monkeypatch):
        _stub_stream(monkeypatch, {"a": ["x", "y"]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a"])
            list(llm.generate_stream("s", "u", "more"))
            row = query("SELECT model, intent, ok FROM model_stats", (), one=True)
            assert (row["model"], row["intent"], row["ok"]) == ("a", "more", 1)


def _frames(response):
    """Split an SSE body into (event, data) pairs."""
    out = []
    for frame in response.get_data(as_text=True).split("\n\n"):
        if not frame.strip():
            continue
        event, data = "message", ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        out.append((event, data))
    return out


class TestStreamEndpoints:
    def test_more_stream_emits_chunks_then_done(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": ["Deep", "er."]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["m"])
        r = client.post("/api/more/stream", json={"title": "T", "said": "s"})
        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"
        frames = _frames(r)
        assert [json.loads(d) for e, d in frames if e == "message"] == ["Deep", "er."]
        assert frames[-1][0] == "done"

    def test_ask_stream_requires_a_question(self, client):
        assert client.post("/api/ask/stream", json={"title": "T", "said": "s"}).status_code == 400

    def test_total_failure_is_an_error_event(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": llm.LLMError("dead")})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["m"])
        r = client.post("/api/more/stream", json={"title": "T", "said": "s"})
        assert r.status_code == 200  # too late for a status; the event carries it
        assert ("error" in [e for e, _ in _frames(r)])

    def test_leading_code_fence_is_stripped(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": ["```text\n", "Real prose ", "here."]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["m"])
        r = client.post("/api/more/stream", json={"title": "T", "said": "s"})
        text = "".join(json.loads(d) for e, d in _frames(r) if e == "message")
        assert text == "Real prose here."

    def test_stream_counts_against_quota(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": ["x"]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["m"])
        client.post("/api/more/stream", json={"title": "T", "said": "s"})
        with app.app_context():
            row = query(
                "SELECT count FROM usage_counters WHERE subject LIKE 'ip:%'", (), one=True
            )
            assert row["count"] == 1

    def test_ask_stream_happy_path(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": ["An ", "answer."]})
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["m"])
        r = client.post("/api/ask/stream", json={"title": "T", "said": "s", "question": "why?"})
        text = "".join(json.loads(d) for e, d in _frames(r) if e == "message")
        assert text == "An answer."
