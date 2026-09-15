"""Auth, ownership isolation, rate limits, and the generation endpoints."""
import pytest

from curio import llm


@pytest.fixture()
def stub_llm(monkeypatch):
    """Deterministic generation so endpoint tests don't need a network."""
    payload = {
        "title": "A title",
        "blurb": "A blurb.",
        "buttons": [{"label": f"door {i}", "type": "fact"} for i in range(5)],
        "seeds": [{"label": f"seed {i}", "type": "question"} for i in range(4)],
        "more": "Deeper.",
        "answer": "An answer.",
        "synthesis": "A synthesis.",
        "thread": "A thread?",
    }
    monkeypatch.setattr(llm, "_post", lambda *a, **k: __import__("json").dumps(payload))
    return payload


class TestAuth:
    def test_signup_login_logout(self, client):
        r = client.post("/api/auth/signup", json={"email": "a@b.com", "password": "longenoughpw"})
        assert r.status_code == 201
        assert r.get_json()["user"]["role"] == "user"

        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").get_json()["user"] is None

        r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "longenoughpw"})
        assert r.status_code == 200

    def test_me_never_401s(self, client):
        assert client.get("/api/auth/me").status_code == 200

    def test_configured_admin_email_is_promoted(self, client):
        r = client.post(
            "/api/auth/signup", json={"email": "admin@example.com", "password": "longenoughpw"}
        )
        assert r.get_json()["user"]["role"] == "admin"

    def test_only_one_admin(self, client):
        client.post("/api/auth/signup", json={"email": "admin@example.com", "password": "longenoughpw"})
        client.post("/api/auth/logout")
        # Even the configured email can't mint a second admin.
        r = client.post("/api/auth/signup", json={"email": "other@example.com", "password": "longenoughpw"})
        assert r.get_json()["user"]["role"] == "user"

    def test_duplicate_email_rejected(self, client):
        client.post("/api/auth/signup", json={"email": "a@b.com", "password": "longenoughpw"})
        client.post("/api/auth/logout")
        r = client.post("/api/auth/signup", json={"email": "A@B.com", "password": "longenoughpw"})
        assert r.status_code == 409

    def test_short_password_rejected(self, client):
        r = client.post("/api/auth/signup", json={"email": "a@b.com", "password": "short"})
        assert r.status_code == 400

    def test_bad_login_is_indistinguishable(self, client):
        client.post("/api/auth/signup", json={"email": "a@b.com", "password": "longenoughpw"})
        client.post("/api/auth/logout")
        unknown = client.post("/api/auth/login", json={"email": "nope@b.com", "password": "longenoughpw"})
        wrong = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrongpassword"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.get_json() == wrong.get_json()

    def test_signup_rate_limited_per_ip(self, client):
        for i in range(3):
            client.post("/api/auth/signup", json={"email": f"u{i}@b.com", "password": "longenoughpw"})
            client.post("/api/auth/logout")
        r = client.post("/api/auth/signup", json={"email": "over@b.com", "password": "longenoughpw"})
        assert r.status_code == 429


class TestOwnershipIsolation:
    """One user must never reach another user's wanders, pages, or saves."""

    def _make_user(self, client, email):
        client.post("/api/auth/logout")
        client.post("/api/auth/signup", json={"email": email, "password": "longenoughpw"})

    def test_cannot_read_another_users_wander(self, client):
        self._make_user(client, "one@b.com")
        wander = client.post("/api/wanders").get_json()["id"]
        client.post(
            f"/api/wanders/{wander}/pages",
            json={"clientNodeId": 1, "title": "Secret", "blurb": "b"},
        )

        self._make_user(client, "two@b.com")
        assert client.get(f"/api/wanders/{wander}").status_code == 404

    def test_cannot_append_to_another_users_wander(self, client):
        self._make_user(client, "one@b.com")
        wander = client.post("/api/wanders").get_json()["id"]

        self._make_user(client, "two@b.com")
        r = client.post(f"/api/wanders/{wander}/pages", json={"clientNodeId": 1, "title": "x"})
        assert r.status_code == 404

    def test_cannot_patch_another_users_page(self, client):
        self._make_user(client, "one@b.com")
        wander = client.post("/api/wanders").get_json()["id"]
        page = client.post(
            f"/api/wanders/{wander}/pages", json={"clientNodeId": 1, "title": "x", "blurb": "b"}
        ).get_json()["id"]

        self._make_user(client, "two@b.com")
        assert client.patch(f"/api/pages/{page}", json={"more": ["hi"]}).status_code == 404

    def test_cannot_save_another_users_page(self, client):
        self._make_user(client, "one@b.com")
        wander = client.post("/api/wanders").get_json()["id"]
        page = client.post(
            f"/api/wanders/{wander}/pages", json={"clientNodeId": 1, "title": "x", "blurb": "b"}
        ).get_json()["id"]

        self._make_user(client, "two@b.com")
        assert client.post("/api/saves", json={"pageId": page}).status_code == 404

    def test_persistence_requires_auth(self, client):
        for call in (
            lambda: client.post("/api/wanders"),
            lambda: client.get("/api/wanders"),
            lambda: client.get("/api/saves"),
            lambda: client.get("/api/resume"),
            lambda: client.get("/api/email-prefs"),
        ):
            assert call().status_code == 401


class TestSavedRecaps:
    """'Save & close': the kept-recap flag and the recap it protects."""

    RECAP = {"path": ["a", "b", "c"], "synthesis": "The thread that ran through.", "thread": "What next?"}

    def _wander(self, client, email="w@b.com"):
        client.post("/api/auth/logout")
        client.post("/api/auth/signup", json={"email": email, "password": "longenoughpw"})
        return client.post("/api/wanders").get_json()["id"]

    def _listed(self, client, wander_id):
        rows = client.get("/api/wanders").get_json()["wanders"]
        return next(w for w in rows if w["id"] == wander_id)

    def test_requires_auth(self, client):
        assert client.post("/api/wanders/1/save-recap", json={}).status_code == 401
        assert client.delete("/api/wanders/1/save-recap").status_code == 401

    def test_cannot_touch_another_users_recap(self, client):
        wander = self._wander(client, "one@b.com")
        self._wander(client, "two@b.com")
        assert client.post(f"/api/wanders/{wander}/save-recap", json={}).status_code == 404
        assert client.delete(f"/api/wanders/{wander}/save-recap").status_code == 404

    def test_save_flags_the_recap_the_close_stored(self, client):
        wander = self._wander(client)
        client.post(f"/api/wanders/{wander}/close", json={"recap": self.RECAP})
        assert self._listed(client, wander)["recapSaved"] is False

        assert client.post(f"/api/wanders/{wander}/save-recap", json={}).status_code == 201
        row = self._listed(client, wander)
        assert row["recapSaved"] is True
        assert row["recap"] == self.RECAP
        # The single-wander read agrees.
        assert client.get(f"/api/wanders/{wander}").get_json()["recap"] == self.RECAP

    def test_unsave_clears_the_flag_but_keeps_the_recap(self, client):
        wander = self._wander(client)
        client.post(f"/api/wanders/{wander}/close", json={"recap": self.RECAP})
        client.post(f"/api/wanders/{wander}/save-recap", json={})

        assert client.delete(f"/api/wanders/{wander}/save-recap").status_code == 200
        row = self._listed(client, wander)
        assert row["recapSaved"] is False
        assert row["recap"] == self.RECAP  # /api/resume still needs it
        # Deleting again is a quiet no-op, like DELETE /api/saves.
        assert client.delete(f"/api/wanders/{wander}/save-recap").status_code == 200

    def test_save_body_fills_a_recap_the_close_never_stored(self, client):
        # The close persist is fire-and-forget on the client; if it failed,
        # the copy in the save request is all there is.
        wander = self._wander(client)
        client.post(f"/api/wanders/{wander}/save-recap", json={"recap": self.RECAP})
        row = self._listed(client, wander)
        assert row["recapSaved"] is True
        assert row["recap"] == self.RECAP

    def test_close_stored_recap_wins_over_the_save_body(self, client):
        wander = self._wander(client)
        client.post(f"/api/wanders/{wander}/close", json={"recap": self.RECAP})
        other = {"path": ["x"], "synthesis": "Something else entirely.", "thread": ""}
        client.post(f"/api/wanders/{wander}/save-recap", json={"recap": other})
        assert self._listed(client, wander)["recap"] == self.RECAP

    def test_garbage_body_sets_the_flag_and_nothing_else(self, client):
        wander = self._wander(client)
        r = client.post(f"/api/wanders/{wander}/save-recap", json={"recap": {"synthesis": ""}})
        assert r.status_code == 201
        row = self._listed(client, wander)
        assert row["recapSaved"] is True
        assert row["recap"] is None  # the client filters flag-without-recap out


class TestGeneration:
    def test_page(self, client, stub_llm):
        r = client.post("/api/page", json={"label": "Why do we dream?", "kind": "question"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["title"] == "A title"
        assert len(body["buttons"]) == 5

    def test_page_requires_a_label_unless_surprise(self, client, stub_llm):
        assert client.post("/api/page", json={}).status_code == 400
        assert client.post("/api/page", json={"surprise": True}).status_code == 200

    def test_page_terms_survive_only_if_the_blurb_says_them(self, client, monkeypatch):
        """Terms become tap-to-wander links, so each must be a verbatim
        (case-insensitive) substring of the blurb — anything else is either
        the model paraphrasing or inventing, and both get dropped. So do
        duplicates and the page's own title."""
        import json as _json
        payload = {
            "title": "Radium",
            "blurb": "The Radium Girls painted dials for the United States Radium Corporation.",
            "buttons": [{"label": f"d{i}", "type": "fact"} for i in range(5)],
            "terms": [
                "radium girls",                        # in blurb (case differs) — kept
                "United States Radium Corporation",    # in blurb — kept
                "Marie Curie",                         # never in the blurb — dropped
                "RADIUM GIRLS",                        # duplicate of the first — dropped
                "Radium",                              # equals the title — dropped
                {"label": "not a string"},             # wrong shape — dropped
            ],
        }
        monkeypatch.setattr(llm, "_post", lambda *a, **k: _json.dumps(payload))
        body = client.post("/api/page", json={"label": "x", "kind": "topic"}).get_json()
        assert body["terms"] == ["radium girls", "United States Radium Corporation"]

    def test_page_without_terms_still_works(self, client, stub_llm):
        # Free models will forget the key constantly; the page must not care.
        body = client.post("/api/page", json={"label": "y", "kind": "topic"}).get_json()
        assert body["terms"] == []

    def test_more_passes_term_markers_through_untouched(self, client, monkeypatch):
        """[[term]] markers in deeper prose are the client's contract — the
        server must never strip or mangle them."""
        import json as _json
        marked = "It was [[Fritz Haber]] who made air into bread."
        monkeypatch.setattr(llm, "_post", lambda *a, **k: _json.dumps({"more": marked}))
        body = client.post("/api/more", json={"title": "T", "said": "s"}).get_json()
        assert body["more"] == marked

    def test_seeds(self, client, stub_llm):
        r = client.post("/api/seeds", json={"count": 4})
        assert r.status_code == 200
        assert len(r.get_json()["seeds"]) == 4

    def test_topical_seeds_require_login(self, client, stub_llm):
        assert client.post("/api/seeds/topical", json={}).status_code == 401

    def test_topical_seeds_without_topics_is_empty_and_free(self, signed_in, stub_llm, app):
        r = signed_in.post("/api/seeds/topical", json={})
        assert r.status_code == 200
        assert r.get_json()["seeds"] == []
        # Nothing was generated, so nothing was counted against the generation
        # quota (signup itself writes a separate signup: counter row).
        with app.app_context():
            from curio.db import query
            n = query(
                "SELECT COUNT(*) AS n FROM usage_counters WHERE subject LIKE 'user:%'",
                (), one=True,
            )["n"]
            assert n == 0

    def test_topical_seeds_use_saved_topics_server_side(self, signed_in, app, monkeypatch):
        signed_in.put("/api/email-prefs", json={"topics": ["deep sea biology", "old maps"]})
        prompts_seen = []

        def fake_post(model, system, user, max_tokens, json_mode, temperature=None, timeout=None):
            prompts_seen.append((system, user))
            return __import__("json").dumps(
                {"seeds": [{"label": f"near {i}", "type": "topic"} for i in range(6)]}
            )

        monkeypatch.setattr(llm, "_post", fake_post)
        r = signed_in.post(
            "/api/seeds/topical", json={"count": 6, "exclude": ["already shown"]}
        )
        assert r.status_code == 200
        assert len(r.get_json()["seeds"]) == 6
        system, user = prompts_seen[0]
        # The topics reached the prompt without the client ever sending them…
        assert "deep sea biology" in user
        assert "already shown" in user
        # …and the brief demands adjacency, not restatement.
        assert "adjacent" in system

    def test_topical_seeds_never_restate_a_topic(self, signed_in, monkeypatch):
        """Even a disobedient model can't put a saved interest on screen as
        a door — the server drops verbatim restatements (case, a leading
        'the', and trailing punctuation don't disguise them)."""
        import json as _json

        signed_in.put("/api/email-prefs", json={"topics": ["astronomy"]})
        seeds = [
            {"label": "Astronomy", "type": "topic"},
            {"label": "The star that vanished without a supernova", "type": "fact"},
            {"label": "The Astronomy.", "type": "topic"},
            {"label": "astronomy!", "type": "topic"},
        ]
        monkeypatch.setattr(llm, "_post", lambda *a, **k: _json.dumps({"seeds": seeds}))
        r = signed_in.post("/api/seeds/topical", json={})
        assert r.status_code == 200
        labels = [s["label"] for s in r.get_json()["seeds"]]
        assert labels == ["The star that vanished without a supernova"]

    def test_topical_seeds_count_against_quota(self, signed_in, stub_llm, app):
        signed_in.put("/api/email-prefs", json={"topics": ["astronomy"]})
        assert signed_in.post("/api/seeds/topical", json={}).status_code == 200
        with app.app_context():
            from curio.db import query
            row = query(
                "SELECT count FROM usage_counters WHERE subject LIKE 'user:%'",
                (), one=True,
            )
            assert row["count"] == 1

    def test_empty_answer_walks_the_chain_not_a_502(self, client, app, monkeypatch):
        """Valid JSON with an empty answer used to 502 on the spot, the rest
        of the chain never consulted — the main culprit behind 'That one
        didn't come through — try asking again.'"""
        import json as _json

        replies = [
            _json.dumps({"answer": ""}),       # model a, attempt 1
            _json.dumps({"answer": ""}),       # model a, attempt 2
            _json.dumps({"answer": "Real."}),  # model b
        ]
        monkeypatch.setattr(llm, "_post", lambda *a, **k: replies.pop(0))
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
        r = client.post("/api/ask", json={"title": "t", "said": "s", "question": "why?"})
        assert r.status_code == 200
        assert r.get_json()["answer"] == "Real."

    def test_all_restatement_hand_retries_the_chain(self, signed_in, app, monkeypatch):
        # A hand that is nothing but restatements is as useless as no hand:
        # the chain keeps walking instead of 502ing on the first model's say.
        import json as _json

        replies = [
            _json.dumps({"seeds": [{"label": "Astronomy", "type": "topic"}]}),
            _json.dumps({"seeds": [{"label": "astronomy!", "type": "topic"}]}),
            _json.dumps(
                {"seeds": [{"label": "The star that vanished without a supernova", "type": "fact"}]}
            ),
        ]
        monkeypatch.setattr(llm, "_post", lambda *a, **k: replies.pop(0))
        with app.app_context():
            llm.set_config_json(llm.CONFIG_KEY_CHAIN, ["a", "b"])
        signed_in.put("/api/email-prefs", json={"topics": ["astronomy"]})
        r = signed_in.post("/api/seeds/topical", json={})
        assert r.status_code == 200
        labels = [s["label"] for s in r.get_json()["seeds"]]
        assert labels == ["The star that vanished without a supernova"]

    def test_more_and_ask_and_recap(self, client, stub_llm):
        assert client.post("/api/more", json={"title": "t", "said": "s"}).get_json()["more"]
        assert client.post(
            "/api/ask", json={"title": "t", "said": "s", "question": "why?"}
        ).get_json()["answer"]
        assert client.post("/api/recap", json={"path": ["a", "b"]}).get_json()["thread"]

    def test_recap_rejects_an_empty_synthesis(self, client, monkeypatch):
        # A model answering {"synthesis": ""} must walk the chain like any
        # other bad reply — recaps can be saved now, so an empty one would
        # be kept forever.
        import json as _json

        monkeypatch.setattr(
            llm, "_post", lambda *a, **k: _json.dumps({"synthesis": "", "thread": "x?"})
        )
        assert client.post("/api/recap", json={"path": ["a", "b"]}).status_code == 502

    def test_failed_generation_refunds_the_quota_unit(self, client, app, monkeypatch):
        """The gate charges before generating, but a walked-out chain delivers
        nothing — same refund as a failed stream. The client quietly retries
        502s now, and without the refund each quiet retry would eat quota."""
        def dead(*a, **k):
            raise llm.LLMError("dead")

        monkeypatch.setattr(llm, "_post", dead)
        r = client.post("/api/page", json={"label": "x", "kind": "topic"})
        assert r.status_code == 502
        assert r.get_json()["error"] == "generation_failed"
        with app.app_context():
            from curio.db import query
            row = query(
                "SELECT count FROM usage_counters WHERE subject LIKE 'ip:%'", (), one=True
            )
            assert row["count"] == 0

    def test_successful_generation_keeps_the_charge(self, client, app, stub_llm):
        assert client.post("/api/page", json={"label": "x", "kind": "topic"}).status_code == 200
        with app.app_context():
            from curio.db import query
            row = query(
                "SELECT count FROM usage_counters WHERE subject LIKE 'ip:%'", (), one=True
            )
            assert row["count"] == 1

    def test_ask_needs_a_question(self, client, stub_llm):
        assert client.post("/api/ask", json={"title": "t", "said": "s"}).status_code == 400

    def test_anonymous_generation_is_allowed(self, client, stub_llm):
        """The prototype's 'tap a door immediately' feel must survive signed-out."""
        assert client.post("/api/page", json={"label": "x", "kind": "fact"}).status_code == 200

    def test_anonymous_daily_cap(self, client, stub_llm):
        # Distinct labels: repeating one would hit the page cache, which is
        # deliberately quota-free (quota counts generations, not requests).
        for i in range(3):
            assert client.post("/api/page", json={"label": f"x{i}", "kind": "fact"}).status_code == 200
        r = client.post("/api/page", json={"label": "x99", "kind": "fact"})
        assert r.status_code == 429
        assert r.get_json()["error"] == "quota"

    def test_signed_in_users_get_the_higher_cap(self, client, stub_llm):
        client.post("/api/auth/signup", json={"email": "a@b.com", "password": "longenoughpw"})
        # Distinct labels so every request is a real (counted) generation.
        for i in range(4):  # past the anonymous cap of 3
            assert client.post("/api/page", json={"label": f"y{i}", "kind": "fact"}).status_code == 200

    def test_generation_failure_is_a_502_not_a_crash(self, client, monkeypatch):
        monkeypatch.setattr(llm, "_post", lambda *a, **k: "not json at all")
        r = client.post("/api/page", json={"label": "x", "kind": "fact"})
        assert r.status_code == 502
        assert r.get_json()["error"] == "generation_failed"

    def test_malformed_button_shapes_are_coerced(self, client, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_post",
            lambda *a, **k: '{"title":"t","blurb":"b","buttons":["a plain string",'
            '{"text":"alt key","kind":"question"},{"label":"ok","type":"nonsense"}]}',
        )
        buttons = client.post("/api/page", json={"label": "x", "kind": "fact"}).get_json()["buttons"]
        assert buttons[0] == {"label": "a plain string", "type": "topic"}
        assert buttons[1] == {"label": "alt key", "type": "question"}
        assert buttons[2]["type"] == "topic"  # unknown type falls back


class TestAdmin:
    def test_admin_endpoints_require_admin(self, client):
        client.post("/api/auth/signup", json={"email": "plain@b.com", "password": "longenoughpw"})
        assert client.get("/api/admin/config").status_code == 403
        assert client.put("/api/admin/config", json={"chain": ["x"]}).status_code == 403

    def test_admin_endpoints_401_when_signed_out(self, client):
        assert client.get("/api/admin/config").status_code == 401

    def test_admin_can_set_chain(self, admin):
        r = admin.put("/api/admin/config", json={"chain": ["m1:free", "m2:free"]})
        assert r.status_code == 200
        assert r.get_json()["chain"] == ["m1:free", "m2:free"]

    def test_chain_dedupes_and_rejects_empty(self, admin):
        assert admin.put("/api/admin/config", json={"chain": []}).status_code == 400
        r = admin.put("/api/admin/config", json={"chain": ["a", "a", "b"]})
        assert r.get_json()["chain"] == ["a", "b"]

    def test_overrides_limited_to_known_intents(self, admin):
        r = admin.put("/api/admin/config", json={"overrides": {"seeds": "cheap:free", "bogus": "x"}})
        assert r.get_json()["overrides"] == {"seeds": "cheap:free"}

    def test_email_override_round_trips(self, admin):
        # Was silently dropped: 'email' wasn't in TEST_INTENTS, which doubles
        # as the override allow-list, so the UI showed a save that reverted.
        r = admin.put("/api/admin/config", json={"overrides": {"email": "strong:free"}})
        assert r.get_json()["overrides"] == {"email": "strong:free"}

    def test_admin_test_exercises_the_email_prompt(self, admin, stub_llm):
        r = admin.post("/api/admin/test", json={"model": "m:free", "intent": "email"})
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_usage_requires_admin(self, client):
        client.post("/api/auth/signup", json={"email": "pleb@example.com", "password": "longenoughpw"})
        assert client.get("/api/admin/usage").status_code == 403
        client.post("/api/auth/logout")
        assert client.get("/api/admin/usage").status_code == 401

    def test_usage_counts_doors_per_user(self, client):
        client.post("/api/auth/signup", json={"email": "one@b.com", "password": "longenoughpw"})
        wander = client.post("/api/wanders").get_json()["id"]
        for i in range(3):
            client.post(
                f"/api/wanders/{wander}/pages",
                json={"clientNodeId": i + 1, "title": f"Door {i}", "blurb": "b"},
            )
        client.post("/api/auth/logout")
        client.post("/api/auth/signup", json={"email": "admin@example.com", "password": "longenoughpw"})

        body = client.get("/api/admin/usage").get_json()
        assert [u["email"] for u in body["users"]] == ["one@b.com"]  # admin's 0 rows absent
        u = body["users"][0]
        assert (u["today"], u["week"], u["month"]) == (3, 3, 3)

    def test_usage_windows_split_by_age(self, client, app):
        client.post("/api/auth/signup", json={"email": "one@b.com", "password": "longenoughpw"})
        wander = client.post("/api/wanders").get_json()["id"]
        client.post(
            f"/api/wanders/{wander}/pages", json={"clientNodeId": 1, "title": "Now", "blurb": "b"}
        )
        with app.app_context():
            from curio.db import execute

            execute(
                "INSERT INTO pages (wander_id, kind, title, blurb, created_at) "
                "VALUES (?, 'topic', 'Older', 'b', datetime('now', '-10 days'))",
                (wander,),
            )
        client.post("/api/auth/logout")
        client.post("/api/auth/signup", json={"email": "admin@example.com", "password": "longenoughpw"})

        u = client.get("/api/admin/usage").get_json()["users"][0]
        assert (u["today"], u["week"], u["month"]) == (1, 1, 2)


class TestEmailPrefs:
    def test_default_is_on_at_8pm(self, signed_in):
        prefs = signed_in.get("/api/email-prefs").get_json()
        assert prefs["enabled"] is True
        assert prefs["sendHour"] == 20

    def test_round_trip(self, signed_in):
        r = signed_in.put(
            "/api/email-prefs",
            json={
                "enabled": True,
                "topics": ["astronomy", "medieval history"],
                "wildcard": False,
                "sendHour": 7,
                "frequency": "weekdays",
            },
        )
        body = r.get_json()
        assert body["enabled"] is True
        assert body["topics"] == ["astronomy", "medieval history"]
        assert body["frequency"] == "weekdays"
        assert body["sendHour"] == 7

    def test_invalid_values_fall_back(self, signed_in):
        body = signed_in.put(
            "/api/email-prefs", json={"enabled": True, "frequency": "hourly", "sendHour": 99}
        ).get_json()
        assert body["frequency"] == "daily"
        assert body["sendHour"] == 20

    def test_unsubscribe_is_one_click(self, signed_in, app):
        signed_in.put("/api/email-prefs", json={"enabled": True})
        with app.app_context():
            from curio.db import query

            token = query("SELECT unsub_token FROM email_prefs LIMIT 1", (), one=True)["unsub_token"]
        assert signed_in.get(f"/unsub/{token}").status_code == 200
        assert signed_in.get("/api/email-prefs").get_json()["enabled"] is False

    def test_bad_unsub_token_does_not_leak(self, client):
        # Same page as a valid token — never confirms whether an account exists.
        assert client.get("/unsub/definitely-not-a-real-token").status_code == 200
