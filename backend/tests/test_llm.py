"""The tolerant parser and the fallback chain.

This is the highest-risk logic in the app: free models emit malformed JSON
routinely, and the whole product breaks if we can't recover from it.
"""
import pytest

from curio import llm


class TestParseJsonLoose:
    def test_clean_json(self):
        assert llm.parse_json_loose('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert llm.parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}

    def test_bare_fence(self):
        assert llm.parse_json_loose('```\n{"a": 1}\n```') == {"a": 1}

    def test_chatty_preamble_and_suffix(self):
        raw = 'Sure! Here is the JSON you asked for:\n{"a": 1}\nHope that helps!'
        assert llm.parse_json_loose(raw) == {"a": 1}

    def test_trailing_comma(self):
        assert llm.parse_json_loose('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        assert llm.parse_json_loose('{"a": [1, 2,]}') == {"a": [1, 2]}

    def test_smart_quotes(self):
        assert llm.parse_json_loose('{“a”: “b”}') == {"a": "b"}

    def test_raw_newline_inside_string(self):
        # A very common small-model failure: a literal newline in a value.
        assert llm.parse_json_loose('{"blurb": "line one\nline two"}') == {
            "blurb": "line one\nline two"
        }

    def test_nested_object_keeps_outermost(self):
        raw = '{"title": "t", "buttons": [{"label": "x", "type": "fact"}]}'
        assert llm.parse_json_loose(raw)["buttons"][0]["label"] == "x"

    def test_escaped_quote_survives(self):
        assert llm.parse_json_loose(r'{"a": "she said \"hi\""}') == {"a": 'she said "hi"'}

    @pytest.mark.parametrize("bad", ["", "no json here", "[1,2,3]", "{{{", "}{"])
    def test_unparseable_raises(self, bad):
        with pytest.raises(ValueError):
            llm.parse_json_loose(bad)


class TestFallbackChain:
    """generate() must walk the chain and give each model its second chance."""

    def _patch(self, monkeypatch, responses):
        """responses: list of (raw_or_exception) consumed per _post call."""
        calls = []

        def fake_post(model, system, user, max_tokens, json_mode, temperature=None):
            calls.append(model)
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(llm, "_post", fake_post)
        return calls

    def test_first_model_succeeds(self, app, monkeypatch):
        with app.app_context():
            calls = self._patch(monkeypatch, ['{"ok": true}'])
            assert llm.generate("s", "u", models=["a", "b"]) == {"ok": True}
            assert calls == ["a"]

    def test_retries_same_model_once_on_bad_json(self, app, monkeypatch):
        with app.app_context():
            calls = self._patch(monkeypatch, ["garbage", '{"ok": true}'])
            assert llm.generate("s", "u", models=["a", "b"]) == {"ok": True}
            # Two attempts against 'a' before ever touching 'b'.
            assert calls == ["a", "a"]

    def test_falls_through_after_two_bad_parses(self, app, monkeypatch):
        with app.app_context():
            calls = self._patch(monkeypatch, ["garbage", "still garbage", '{"ok": true}'])
            assert llm.generate("s", "u", models=["a", "b"]) == {"ok": True}
            assert calls == ["a", "a", "b"]

    def test_transport_error_skips_rest_of_that_model(self, app, monkeypatch):
        """A rate limit or 500 shouldn't burn the model's second parse attempt."""
        with app.app_context():
            calls = self._patch(monkeypatch, [llm.LLMError("HTTP 429"), '{"ok": true}'])
            assert llm.generate("s", "u", models=["a", "b"]) == {"ok": True}
            assert calls == ["a", "b"]

    def test_all_models_fail_raises(self, app, monkeypatch):
        with app.app_context():
            self._patch(monkeypatch, ["x", "y", "x", "y"])
            with pytest.raises(llm.LLMError):
                llm.generate("s", "u", models=["a", "b"])

    def test_empty_chain_raises(self, app):
        with app.app_context():
            with pytest.raises(llm.LLMError):
                llm.generate("s", "u", models=[])

    def test_stats_are_recorded(self, app, monkeypatch):
        with app.app_context():
            self._patch(monkeypatch, ["garbage", '{"ok": true}'])
            llm.generate("s", "u", intent="page", models=["a"])
            rollup = llm.stats_rollup(days=1)
            stats = {m["model"]: m for m in rollup["models"]}
            assert stats["a"]["calls"] == 2
            assert stats["a"]["okRate"] == 0.5


class TestChainConfig:
    def test_default_chain_from_config(self, app):
        with app.app_context():
            assert llm.get_chain() == app.config["DEFAULT_MODEL_CHAIN"]

    def test_saved_chain_wins(self, app):
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["z:free"])
            assert llm.get_chain() == ["z:free"]

    def test_override_leads_but_chain_still_backs_it_up(self, app):
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
            llm.set_config_json(llm.CONFIG_KEY_OVERRIDES, {"seeds": "b"})
            assert llm.chain_for("seeds") == ["b", "a"]
            assert llm.chain_for("page") == ["a", "b"]


class TestTemperature:
    """The request must carry a temperature suited to the intent.

    Before this, no temperature was sent at all — every free model ran at its
    own default, and small models at ~1.0 are where invented events come from.
    """

    def _capture(self, app, monkeypatch):
        bodies = []

        class FakeRes:
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        def fake_request_post(url, headers=None, json=None, timeout=None):
            bodies.append(json)
            return FakeRes()

        monkeypatch.setattr(llm.requests, "post", fake_request_post)
        return bodies

    def test_factual_intents_run_cool(self, app, monkeypatch):
        bodies = self._capture(app, monkeypatch)
        with app.app_context():
            llm.generate("s", "u", intent="page", models=["a"])
            llm.generate("s", "u", intent="ask", models=["a"])
        assert bodies[0]["temperature"] == 0.4
        assert bodies[1]["temperature"] == 0.3

    def test_variety_intents_run_hot(self, app, monkeypatch):
        bodies = self._capture(app, monkeypatch)
        with app.app_context():
            llm.generate("s", "u", intent="seeds", models=["a"])
        assert bodies[0]["temperature"] == 0.9

    def test_unknown_intent_sends_no_temperature(self, app, monkeypatch):
        bodies = self._capture(app, monkeypatch)
        with app.app_context():
            llm.generate("s", "u", intent="generic", models=["a"])
        assert "temperature" not in bodies[0]

    def test_benchmarks_measure_what_production_runs(self, app, monkeypatch):
        # bench and admin_test mirror the page temperature; a benchmark run at
        # a different temperature vets a model Curio never actually runs.
        assert llm._temperature_for("bench") == llm._temperature_for("page")
        assert llm._temperature_for("admin_test") == llm._temperature_for("page")
        bodies = self._capture(app, monkeypatch)
        with app.app_context():
            llm.generate_raw("a", "s", "u", intent="bench")
        assert bodies[0]["temperature"] == llm.INTENT_TEMPERATURE["page"]
