"""WSGI entrypoint. `waitress-serve --call wsgi:build` or `python wsgi.py` locally."""
from curio import create_app

app = create_app()


def build():
    return app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
