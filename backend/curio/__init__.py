"""Curio — application factory.

Flask serves both the JSON API and the built frontend, so the Pi doesn't need
a second web server sitting in front of it. Cloudflare Tunnel points straight
here.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .config import Config


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_object)

    _configure_secret_key(app)
    logging.basicConfig(
        level=os.environ.get("CURIO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from . import admin, api, auth, cli, db, email_

    db.init_app(app)
    cli.init_app(app)
    auth.init_app(app)
    app.register_blueprint(api.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(email_.bp)

    _register_frontend(app)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.errorhandler(404)
    def _not_found(_e):
        return jsonify({"error": "not_found", "message": "No such endpoint."}), 404

    @app.errorhandler(500)
    def _server_error(_e):
        app.logger.exception("unhandled error")
        return jsonify({"error": "server_error", "message": "Something broke on our end."}), 500

    # Create tables on boot so a fresh Pi deploy is one command.
    with app.app_context():
        db.init_db()

    return app


def _configure_secret_key(app: Flask) -> None:
    """A stable secret key, without ever committing one.

    If CURIO_SECRET_KEY isn't set we generate one and persist it next to the
    database — otherwise every restart would silently log everyone out.
    """
    if app.config.get("SECRET_KEY"):
        return
    key_path = Path(app.config["DATABASE"]).with_suffix(".secret")
    if key_path.exists():
        app.config["SECRET_KEY"] = key_path.read_text().strip()
        return
    key = secrets.token_urlsafe(48)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key)
    key_path.chmod(0o600)
    app.config["SECRET_KEY"] = key
    app.logger.warning("Generated a new SECRET_KEY at %s — set CURIO_SECRET_KEY to pin it.", key_path)


def _register_frontend(app: Flask) -> None:
    """Serve the Vite build, with SPA fallback for client-side views."""
    static_dir = Path(app.config["STATIC_DIR"])

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "not_found", "message": "No such endpoint."}), 404
        if not static_dir.exists():
            return (
                "<!doctype html><meta charset='utf-8'><title>Curio</title>"
                "<p style=\"font-family:Georgia,serif;padding:40px\">"
                "The frontend hasn't been built yet. Run <code>npm run build</code> in "
                "<code>frontend/</code>, or use <code>npm run dev</code> for local work.</p>",
                200,
            )
        candidate = static_dir / path
        if path and candidate.is_file():
            return send_from_directory(static_dir, path)
        return send_from_directory(static_dir, "index.html")
