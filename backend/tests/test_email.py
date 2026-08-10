"""The daily email: scheduling rules and the anti-dark-pattern guarantees."""
import json
from datetime import datetime, timezone

import pytest

from curio import email_, llm
from curio.db import query


def _prefs(frequency="daily", send_hour=8, last_sent_on=None, tz=""):
    return {
        "frequency": frequency,
        "send_hour": send_hour,
        "last_sent_on": last_sent_on,
        "timezone": tz,
    }


def _due(prefs, utc_now, app):
    """Compose exactly what production composes: localize once, then gate.

    Tests go through this shim rather than calling _is_due directly so the
    localization step — where the bug lived — is always part of what's tested.
    """
    with app.app_context():
        return email_._is_due(prefs, email_._local_now(prefs, utc_now))


# 2026-07-27 is a Monday, 2026-08-01 a Saturday.
MON = datetime(2026, 7, 27, 9, tzinfo=timezone.utc)
SAT = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)


class TestIsDue:
    def test_daily_after_send_hour(self, app):
        assert _due(_prefs(send_hour=8), MON, app) is True

    def test_not_before_send_hour(self, app):
        assert _due(_prefs(send_hour=10), MON, app) is False

    def test_never_twice_in_one_day(self, app):
        assert _due(_prefs(last_sent_on="2026-07-27"), MON, app) is False

    def test_weekdays_skips_saturday(self, app):
        assert _due(_prefs(frequency="weekdays"), SAT, app) is False
        assert _due(_prefs(frequency="weekdays"), MON, app) is True

    def test_weekly_is_monday_only(self, app):
        assert _due(_prefs(frequency="weekly"), MON, app) is True
        assert _due(_prefs(frequency="weekly"), SAT, app) is False


class TestTimezones:
    """The 11pm-arrives-at-7pm bug: send_hour must be the user's hour."""

    def test_evening_hour_is_not_due_at_utc_hour(self, app):
        # 23:00 UTC on Monday = 19:00 in New York. A New Yorker who asked for
        # 11pm is NOT due yet — this exact comparison used to pass.
        utc_11pm = datetime(2026, 7, 27, 23, tzinfo=timezone.utc)
        assert _due(_prefs(send_hour=23, tz="America/New_York"), utc_11pm, app) is False

    def test_evening_hour_is_due_after_utc_midnight(self, app):
        # 03:00 UTC Tuesday = 23:00 Monday in New York → due.
        utc_3am_tue = datetime(2026, 7, 28, 3, tzinfo=timezone.utc)
        assert _due(_prefs(send_hour=23, tz="America/New_York"), utc_3am_tue, app) is True

    def test_local_date_guards_the_send_not_the_utc_date(self, app):
        # Same instant as above, but already sent on the LOCAL Monday: the UTC
        # date is Tuesday, and a UTC-dated guard would wrongly resend.
        utc_3am_tue = datetime(2026, 7, 28, 3, tzinfo=timezone.utc)
        prefs = _prefs(send_hour=23, tz="America/New_York", last_sent_on="2026-07-27")
        assert _due(prefs, utc_3am_tue, app) is False

    def test_weekly_uses_local_monday(self, app):
        # 12:30 UTC Sunday = Monday 00:30 in Auckland → weekly is due there,
        # and not for a UTC user at the same instant.
        utc_sun = datetime(2026, 7, 26, 12, 30, tzinfo=timezone.utc)
        assert _due(_prefs(frequency="weekly", send_hour=0, tz="Pacific/Auckland"), utc_sun, app) is True
        assert _due(_prefs(frequency="weekly", send_hour=0, tz="UTC"), utc_sun, app) is False

    def test_invalid_timezone_falls_back_to_default(self, app):
        app.config["DEFAULT_TZ"] = "America/New_York"
        utc_11pm = datetime(2026, 7, 27, 23, tzinfo=timezone.utc)
        # Garbage zone → behaves as the configured default (Eastern), not UTC.
        assert _due(_prefs(send_hour=23, tz="Mars/Olympus"), utc_11pm, app) is False

    def test_bad_default_tz_degrades_to_utc_not_a_crash(self, app):
        app.config["DEFAULT_TZ"] = "Not/AZone"
        utc_11pm = datetime(2026, 7, 27, 23, tzinfo=timezone.utc)
        assert _due(_prefs(send_hour=23, tz=""), utc_11pm, app) is True

    def test_valid_tz_helper(self):
        assert email_._valid_tz("America/New_York") == "America/New_York"
        assert email_._valid_tz("Mars/Olympus") == ""
        assert email_._valid_tz(None) == ""
        assert email_._valid_tz("x" * 65) == ""

    def test_put_prefs_stores_browser_timezone(self, client):
        client.post("/api/auth/signup", json={"email": "z@example.com", "password": "longenoughpw"})
        r = client.put("/api/email-prefs", json={"timezone": "America/New_York"})
        assert r.get_json()["timezone"] == "America/New_York"
        # Garbage clamps to '', the same shape as the other fields.
        r = client.put("/api/email-prefs", json={"timezone": "Definitely/Fake"})
        assert r.get_json()["timezone"] == ""


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

    def test_send_writes_the_local_date_not_utc(self, client, app, stub_doors, monkeypatch):
        """23:00 Monday in New York is 03:00 Tuesday UTC. The guard must say
        Monday, or the same evening becomes eligible again an hour later."""
        self._enable(client)
        client.put(
            "/api/email-prefs",
            json={"enabled": True, "topics": ["astronomy"], "sendHour": 23,
                  "timezone": "America/New_York"},
        )

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 28, 3, tzinfo=timezone.utc)

        monkeypatch.setattr(email_, "datetime", FrozenDatetime)
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            # Not forced: the schedule itself must fire at this instant…
            assert email_.send_due_emails()["sent"] == 1
            row = query("SELECT last_sent_on FROM email_prefs WHERE user_id = ?", (user_id,), one=True)
            # …and record the LOCAL Monday, not the UTC Tuesday.
            assert row["last_sent_on"] == "2026-07-27"
            # Still the same New York evening → nothing more goes out.
            assert email_.send_due_emails() == {"sent": 0, "skipped": 1, "failed": 0}

    def test_generation_failure_counts_as_failed_not_sent(self, client, app, monkeypatch):
        self._enable(client)
        monkeypatch.setattr(llm, "_post", lambda *a, **k: "not json")
        with app.app_context():
            user_id = query("SELECT id FROM users LIMIT 1", (), one=True)["id"]
            assert email_.send_due_emails(force_user_id=user_id)["failed"] == 1
