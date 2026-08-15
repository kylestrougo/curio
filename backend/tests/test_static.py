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


def test_serves_the_favicon_from_the_dist_root(built_app, app):
    """Vite copies public/favicon.svg to the dist root; the catch-all must
    hand it out with an SVG content type, not fall back to the SPA."""
    import pathlib

    dist = pathlib.Path(app.config["STATIC_DIR"])
    (dist / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    r = built_app.test_client().get("/favicon.svg")
    assert r.status_code == 200
    assert "svg" in r.mimetype
    assert b"<svg" in r.data


def test_the_real_favicon_is_in_the_committed_build():
    """The Pi serves the committed dist verbatim — a favicon that only exists
    in public/ but not in dist/ ships a 404 (well, an SPA fallback)."""
    import pathlib

    dist = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
    icon = dist / "favicon.svg"
    assert icon.exists(), "run `npm run build` and commit dist/"
    body = icon.read_text()
    assert "#A9781F" in body  # the brass knob survived the copy
    assert 'href="/favicon.svg"' in (dist / "index.html").read_text()


def test_the_app_icons_are_in_the_committed_build():
    """Home-screen and PWA icons: the manifest, every PNG it promises, and
    the iOS touch icon must all be in dist, and index.html must point at
    them — else 'Add to Home Screen' quietly falls back to a screenshot."""
    import json as _json
    import pathlib
    import struct

    dist = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index = (dist / "index.html").read_text()
    assert 'rel="manifest"' in index and "manifest.webmanifest" in index
    assert 'rel="apple-touch-icon"' in index

    manifest = _json.loads((dist / "manifest.webmanifest").read_text())
    assert manifest["name"] == "Curio"
    for entry in manifest["icons"]:
        png = dist / entry["src"].lstrip("/")
        assert png.exists(), f"{entry['src']} promised by manifest, missing from dist"
        w, h = struct.unpack(">II", png.read_bytes()[16:24])
        assert f"{w}x{h}" == entry["sizes"], f"{entry['src']} is {w}x{h}"

    touch = dist / "apple-touch-icon.png"
    assert touch.exists()
    w, h = struct.unpack(">II", touch.read_bytes()[16:24])
    assert (w, h) == (180, 180)
    # The master the PNGs are rendered from ships too.
    assert (dist / "icon.svg").exists()


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
