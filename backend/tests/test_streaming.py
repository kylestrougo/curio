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


PAGE_JSON_CHUNKS = [
    '{"title": "Meanders"',
    ', "blurb": "Riv',
    'ers wander because stra',
    'ight lines are unstable.", "buttons": [',
    '{"label": "d1", "type": "fact"}, {"label": "d2", "type": "topic"},',
    '{"label": "d3", "type": "question"}, {"label": "d4", "type": "fact"},',
    '{"label": "d5", "type": "topic"}],',
    # One real term and one the model made up but never wrote in the blurb —
    # the fabricated one must not survive to the done event.
    ' "terms": ["straight lines", "the Coriolis effect"]}',
]


class TestBlurbExtractor:
    def _run(self, chunks):
        from curio.api import BlurbExtractor
        ex = BlurbExtractor()
        return "".join(ex.feed(c) for c in chunks)

    def test_extracts_across_chunk_boundaries(self):
        text = self._run(PAGE_JSON_CHUNKS)
        assert text == "Rivers wander because straight lines are unstable."

    def test_stops_at_closing_quote(self):
        # Nothing after the blurb — button labels never leak to the reader.
        text = self._run(PAGE_JSON_CHUNKS)
        assert "d1" not in text and "buttons" not in text

    def test_escaped_quote_and_newline(self):
        text = self._run(['{"blurb": "She said \\"hi\\".\\nThen left."}'])
        assert text == 'She said "hi".\nThen left.'

    def test_escape_split_across_chunks(self):
        text = self._run(['{"blurb": "a\\', '"b"}'])
        assert text == 'a"b'

    def test_smart_quote_delimiters(self):
        text = self._run(['{“blurb”: “curly text”}'])
        assert text == "curly text"

    def test_mangled_json_emits_nothing(self):
        assert self._run(["no json here at all", "still nothing"]) == ""

    def test_key_split_across_chunks(self):
        text = self._run(['{"blu', 'rb": "found it"}'])
        assert text == "found it"


class TestPageStream:
    def _chain_one(self, app, model="m"):
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, [model])

    def test_blurb_streams_then_done_carries_full_page(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": PAGE_JSON_CHUNKS})
        self._chain_one(app)
        r = client.post("/api/page/stream", json={"label": "Why do rivers meander?", "kind": "question"})
        frames = _frames(r)
        streamed = "".join(json.loads(d) for e, d in frames if e == "message")
        assert streamed.startswith("Rivers wander")
        done = json.loads([d for e, d in frames if e == "done"][0])
        assert done["title"] == "Meanders"
        assert len(done["buttons"]) == 5
        # Only the term the blurb actually contains becomes a link.
        assert done["terms"] == ["straight lines"]

    def test_stream_populates_the_cache(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": PAGE_JSON_CHUNKS})
        self._chain_one(app)
        # get_data drains the SSE generator — the cache write happens at its
        # end, so an unconsumed response stores nothing (as in production,
        # where the WSGI server always drains).
        client.post("/api/page/stream", json={"label": "meander", "kind": "topic"}).get_data()
        with app.app_context():
            from curio import pagecache
            assert pagecache.has_page("meander", "topic")

    def test_cache_hit_is_a_single_instant_done(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": PAGE_JSON_CHUNKS})
        self._chain_one(app)
        client.post("/api/page/stream", json={"label": "meander", "kind": "topic"}).get_data()

        def explode(*a, **k):
            raise AssertionError("cache hit reached the model")

        monkeypatch.setattr(llm, "_post_stream", explode)
        r = client.post("/api/page/stream", json={"label": "MEANDER ", "kind": "topic"})
        frames = _frames(r)
        assert [e for e, _ in frames] == ["done"]
        assert json.loads(frames[0][1])["title"] == "Meanders"

    def test_surprise_streams_but_never_caches(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": PAGE_JSON_CHUNKS})
        self._chain_one(app)
        client.post("/api/page/stream", json={"surprise": True})
        with app.app_context():
            assert query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"] == 0

    def test_counts_one_generation_against_quota(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": PAGE_JSON_CHUNKS})
        self._chain_one(app)
        client.post("/api/page/stream", json={"label": "x", "kind": "fact"})
        with app.app_context():
            row = query("SELECT count FROM usage_counters WHERE subject LIKE 'ip:%'", (), one=True)
            assert row["count"] == 1

    def test_unparseable_total_is_an_error_event(self, client, app, monkeypatch):
        _stub_stream(monkeypatch, {"m": ["complete", " garbage"]})
        self._chain_one(app)
        r = client.post("/api/page/stream", json={"label": "x", "kind": "fact"})
        assert "error" in [e for e, _ in _frames(r)]

    def test_needs_a_label_unless_surprise(self, client):
        assert client.post("/api/page/stream", json={}).status_code == 400


class TestStreamEncoding:
    def test_utf8_survives_the_wire(self, app, monkeypatch):
        """Regression pin for the â€™ mojibake: SSE bodies without a charset
        default to Latin-1 in requests, shattering every UTF-8 curly quote.
        This drives the REAL _post_stream over real bytes."""
        import io

        import requests as req_lib

        body = (
            b'data: {"choices":[{"delta":{"content":"it\xe2\x80\x99s alive"}}]}\n\n'
            b"data: [DONE]\n\n"
        )

        def fake_post(url, headers=None, json=None, stream=False, timeout=None):
            res = req_lib.Response()
            res.status_code = 200
            res.headers["Content-Type"] = "text/event-stream"  # note: no charset
            res.raw = io.BytesIO(body)
            return res

        monkeypatch.setattr(llm.requests, "post", fake_post)
        with app.app_context():
            chunks = list(llm._post_stream("m", "s", "u", 1000, None))
        assert chunks == ["it’s alive"]
