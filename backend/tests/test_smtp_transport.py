"""Choosing the SMTP transport from the port.

Gmail accepts both 465 (implicit TLS) and 587 (STARTTLS), and getting them
crossed fails in two unpleasant ways: starttls() against 465 hangs until the
timeout, and a plain connection to 587 without the upgrade would put the app
password on the wire in clear text. The port decides, so a configuration that
works in another script works here unchanged.
"""
import smtplib

import pytest

from curio import email_


class FakeSMTP:
    """Records what was done to it; stands in for both smtplib classes."""

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent = msg


@pytest.fixture()
def transports(monkeypatch):
    made = {}

    def record(kind):
        def factory(host, port, timeout=None):
            made[kind] = FakeSMTP(host, port, timeout)
            return made[kind]

        return factory

    monkeypatch.setattr(smtplib, "SMTP", record("plain"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", record("ssl"))
    return made


def test_465_uses_implicit_tls_and_never_calls_starttls(transports):
    email_._deliver("smtp.gmail.com", 465, "me@gmail.com", "app-password", "MSG")

    assert "plain" not in transports, "465 must not open an unencrypted connection"
    ssl = transports["ssl"]
    assert (ssl.host, ssl.port) == ("smtp.gmail.com", 465)
    assert ssl.started_tls is False
    assert ssl.logged_in == ("me@gmail.com", "app-password")
    assert ssl.sent == "MSG"


def test_587_upgrades_before_authenticating(transports):
    email_._deliver("smtp.gmail.com", 587, "me@gmail.com", "app-password", "MSG")

    assert "ssl" not in transports
    plain = transports["plain"]
    assert plain.started_tls is True, "the password would otherwise go out in clear text"
    assert plain.logged_in == ("me@gmail.com", "app-password")


def test_other_ports_default_to_starttls(transports):
    email_._deliver("smtp.example.com", 2525, "me@example.com", "pw", "MSG")

    assert transports["plain"].started_tls is True
