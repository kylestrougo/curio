"""The SPA handler serves a build directory to the public internet.

These assert it can only ever hand out files from inside that directory —
never the .env sitting one level up.
"""
import pytest


@pytest.fixture()
def built_app(app, tmp_path):
    """A fake build directory, with a secret file as its sibling."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Curio</title>")
    (dist / "assets" / "app.js").write_text("console.log('curio')")
    (tmp_path / "secret.env").write_text("OPENROUTER_API_KEY=sk-or-v1-supersecret")

    app.config["STATIC_DIR"] = str(dist)
    return app


def test_serves_index(built_app):
    r = built_app.test_client().get("/")
    assert r.status_code == 200
    assert b"Curio" in r.data


def test_serves_a_real_asset(built_app):
    r = built_app.test_client().get("/assets/app.js")
    assert r.status_code == 200
    assert b"curio" in r.data


def test_unknown_route_falls_back_to_the_spa(built_app):
    """Client-side views like /admin must render, not 404."""
    r = built_app.test_client().get("/admin")
    assert r.status_code == 200
    assert b"<title>Curio</title>" in r.data


@pytest.mark.parametrize(
    "path",
    [
        "../secret.env",
        "../../secret.env",
        "assets/../../secret.env",
        "%2e%2e/secret.env",
        "..%2fsecret.env",
        "/etc/passwd",
        "....//secret.env",
    ],
)
def test_never_serves_anything_outside_the_build_dir(built_app, path):
    r = built_app.test_client().get(f"/{path}")
    # Either a refusal or the SPA fallback — but never the secret.
    assert b"supersecret" not in r.data
    assert b"OPENROUTER_API_KEY" not in r.data


def test_api_paths_do_not_fall_through_to_the_spa(built_app):
    """An unknown /api/* must be a JSON 404, not an HTML page."""
    r = built_app.test_client().get("/api/definitely-not-real")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_missing_build_dir_explains_itself(app):
    app.config["STATIC_DIR"] = "/nonexistent/dist"
    r = app.test_client().get("/")
    assert r.status_code == 200
    assert b"npm run build" in r.data
