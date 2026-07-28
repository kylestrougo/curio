import os
import tempfile

import pytest

os.environ.setdefault("CURIO_COOKIE_SECURE", "0")

from curio import create_app  # noqa: E402
from curio.config import Config  # noqa: E402


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        DATABASE = path
        SECRET_KEY = "test-secret"
        TESTING = True
        SESSION_COOKIE_SECURE = False
        OPENROUTER_API_KEY = "test-key"
        ADMIN_EMAIL = "admin@example.com"
        DAILY_CAP_USER = 10
        DAILY_CAP_ANON_IP = 3
        SIGNUP_CAP_IP = 3
        MAIL_DRY_RUN = True

    application = create_app(TestConfig)
    yield application

    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def signed_in(client):
    client.post("/api/auth/signup", json={"email": "wanderer@example.com", "password": "longenoughpw"})
    return client


@pytest.fixture()
def admin(client):
    client.post("/api/auth/signup", json={"email": "admin@example.com", "password": "longenoughpw"})
    return client
