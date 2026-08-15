"""Share links: a page frozen behind a token, viewable by anyone.

Creating a share requires a signed-in sharer; opening one requires nothing —
no account, no LLM call, no quota. The /s/<token> landing page carries the
og: tags that make a texted link preview properly in iMessage.
"""
from curio.db import query


def _page():
    return {
        "title": "The Radium Girls",
        "blurb": (
            "In the 1920s, workers at the United States Radium Corporation "
            "painted watch dials with glowing radium paint."
        ),
        "kind": "topic",
        "more": ["They licked their brushes to a point — [[radium jaw]] followed."],
        "qa": [{"q": "Who sued?", "a": "Five workers took [[U.S. Radium]] to court."}],
        "buttons": [{"label": "Radium jaw", "type": "topic"}],
        "terms": ["United States Radium Corporation"],
    }


def _create(signed_in, body=None):
    r = signed_in.post("/api/share", json=body or _page())
    assert r.status_code == 201
    return r.get_json()


def test_share_requires_login(client):
    r = client.post("/api/share", json=_page())
    assert r.status_code == 401


def test_round_trip_preserves_the_snapshot(signed_in):
    token = _create(signed_in)["token"]
    r = signed_in.get(f"/api/share/{token}")
    assert r.status_code == 200
    got = r.get_json()
    sent = _page()
    for key in ("title", "blurb", "kind", "more", "qa", "buttons"):
        assert got[key] == sent[key]  # [[markers]] in more/qa arrive untouched
    assert got["terms"] == ["United States Radium Corporation"]


def test_caps_are_enforced(signed_in):
    body = _page()
    body["more"] = ["x" * 9000] * 30
    body["qa"] = [{"q": "q" * 900, "a": "a" * 9000}] * 30
    token = _create(signed_in, body)["token"]
    got = signed_in.get(f"/api/share/{token}").get_json()
    assert len(got["more"]) == 20 and all(len(m) == 4000 for m in got["more"])
    assert len(got["qa"]) == 20
    assert all(len(x["q"]) == 500 and len(x["a"]) == 4000 for x in got["qa"])


def test_terms_not_in_the_blurb_are_dropped(signed_in):
    body = _page()
    body["terms"] = ["United States Radium Corporation", "Marie Curie"]
    token = _create(signed_in, body)["token"]
    got = signed_in.get(f"/api/share/{token}").get_json()
    assert got["terms"] == ["United States Radium Corporation"]


def test_nothing_to_share_is_a_400(signed_in):
    r = signed_in.post("/api/share", json={"blurb": "no title"})
    assert r.status_code == 400


def test_unknown_token_404s_kindly(client):
    r = client.get("/api/share/no-such-token")
    assert r.status_code == 404
    assert "message" in r.get_json()


def test_get_is_public_and_costs_no_quota(app, signed_in):
    token = _create(signed_in)["token"]
    fresh = app.test_client()  # nobody signed in
    r = fresh.get(f"/api/share/{token}")
    assert r.status_code == 200
    assert r.get_json()["title"] == "The Radium Girls"
    with app.app_context():
        n = query("SELECT COUNT(*) AS n FROM usage_counters", (), one=True)["n"]
        # signup wrote its own signup: counter; nothing else may appear
        assert (
            query(
                "SELECT COUNT(*) AS n FROM usage_counters WHERE subject NOT LIKE 'signup:%'",
                (), one=True,
            )["n"]
            == 0
        ), f"share endpoints touched the generation quota ({n} rows)"


def test_landing_page_carries_og_tags(signed_in):
    token = _create(signed_in)["token"]
    r = signed_in.get(f"/s/{token}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'property="og:title" content="The Radium Girls"' in body
    assert "painted watch dials" in body  # the blurb excerpt
    assert f"0;url=/?share={token}" in body


def test_landing_page_escapes_html(signed_in):
    body = _page()
    body["title"] = '<script>alert("x")</script>'
    token = _create(signed_in, body)["token"]
    page = signed_in.get(f"/s/{token}").get_data(as_text=True)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_unknown_landing_token_redirects_home(client):
    r = client.get("/s/no-such-token")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")


def test_landing_wins_over_the_spa_catch_all(app, signed_in, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Curio SPA</title>")
    app.config["STATIC_DIR"] = str(dist)
    token = _create(signed_in)["token"]
    r = signed_in.get(f"/s/{token}")
    assert "og:title" in r.get_data(as_text=True)
    assert "Curio SPA" not in r.get_data(as_text=True)
