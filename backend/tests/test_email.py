"""The daily email: scheduling rules and the anti-dark-pattern guarantees."""
import json
from datetime import datetime, timezone

import pytest

from curio import email_, llm
from curio.db import query


def _prefs(frequency="daily", send_hour=8, last_sent_on=None):
    return {"frequency": frequency, "send_hour": send_hour, "last_sent_on": last_sent_on}


# 2026-07-27 is a Monday, 2026-08-01 a Saturday.
MON = datetime(2026, 7, 27, 9, tzinfo=timezone.utc)
SAT = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)


class TestIsDue:
    def test_daily_after_send_hour(self):
        assert email_._is_due(_prefs(send_hour=8), MON) is True

    def test_not_before_send_hour(self):
        assert email_._is_due(_prefs(send_hour=10), MON) is False

    def test_never_twice_in_one_day(self):
        assert email_._is_due(_prefs(last_sent_on="2026-07-27"), MON) is False

    def test_weekdays_skips_saturday(self):
        assert email_._is_due(_prefs(frequency="weekdays"), SAT) is False
        assert email_._is_due(_prefs(frequency="weekdays"), MON) is True

    def test_weekly_is_monday_only(self):
        assert email_._is_due(_prefs(frequency="weekly"), MON) is True
        assert email_._is_due(_prefs(frequency="weekly"), SAT) is False


class TestSending:
    @pytest.fixture()
    def stub_doors(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_post",
            lambda *a, **k: json.dumps(
                {"seeds": [{"label": f"door {i}", "type": "topic"} for i in range(3)]}
            ),
        )

    def _enable(self, client):
        client.post("/api/auth/signup", json={"email": "w@example.com", "password": "longenoughpw"})
        client.put("/api/email-prefs", json={"enabled": True, "topics": ["astronomy"]})

    def test_configure_nothing_get_nothing(self, client, app, stub_doors):
        """The core guarantee: a user who never opted in is never emailed."""
        client.post("/api/auth/signup", json={"email": "w@example.com", "password": "longenoughpw"})
        with app.app_context():
            assert email_.send_due_emails() == {"sent": 0, "skipped": 0, "failed": 0}

    def test_forced_send_produces_doors_and_tokens(self, client, app, stub_doors):
        self._enable(client)
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            result = email_.send_due_emails(force_user_id=user_id)
            assert result["sent"] == 1
            tokens = query("SELECT * FROM door_tokens", ())
            assert len(tokens) == 3
            assert tokens[0]["label"].startswith("door")

    def test_deep_link_token_resolves_then_opens(self, client, app, stub_doors):
        self._enable(client)
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            email_.send_due_emails(force_user_id=user_id)
            token = query("SELECT token FROM door_tokens LIMIT 1", (), one=True)["token"]

        body = client.get(f"/api/door/{token}").get_json()
        assert body["label"].startswith("door")
        assert body["type"] == "topic"
        assert client.get(f"/d/{token}").status_code == 302

    def test_unknown_door_token_404s(self, client):
        assert client.get("/api/door/nope").status_code == 404

    def test_email_body_has_no_tracking_and_an_unsubscribe(self, app):
        """Anti-dark-pattern guardrails, asserted rather than merely intended."""
        with app.app_context():
            doors = [{"label": "A door", "kind": "topic", "token": "tok123"}]
            text, html_body = email_._render("w@example.com", doors, "unsub-token")

        for body in (text, html_body):
            assert "unsub/unsub-token" in body
        # No tracking pixel, no click-through redirector.
        assert "<img" not in html_body
        # No re-engagement / urgency language.
        lowered = html_body.lower()
        for banned in ("miss you", "streak", "don't miss", "last chance", "hurry", "expire"):
            assert banned not in lowered

    def test_send_marks_last_sent_so_it_cannot_repeat(self, client, app, stub_doors):
        self._enable(client)
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            email_.send_due_emails(force_user_id=user_id)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            row = query("SELECT last_sent_on FROM email_prefs WHERE user_id = ?", (user_id,), one=True)
            assert row["last_sent_on"] == today
            # A normal (non-forced) run now skips them.
            assert email_.send_due_emails()["sent"] == 0

    def test_generation_failure_counts_as_failed_not_sent(self, client, app, monkeypatch):
        self._enable(client)
        monkeypatch.setattr(llm, "_post", lambda *a, **k: "not json")
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            assert email_.send_due_emails(force_user_id=user_id)["failed"] == 1
