"""
app/app.py
Flask application factory. run.py calls create_app() to get a
configured Flask app -- keeping this separate from run.py means the
app can also be imported for testing without starting a server.
"""
from flask import Flask

from .config import Config, TEMPLATES_DIR, STATIC_DIR
from .routes.routes import api_bp
from .utils.db import DatabaseUnavailableError, init_db


def create_app():
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )
    app.secret_key = Config.SECRET_KEY
    app.register_blueprint(api_bp)

    try:
        init_db()
    except DatabaseUnavailableError as e:
        # Don't crash the whole app on startup just because MySQL isn't
        # reachable yet -- log it clearly so it's obvious in the backend
        # console, and let individual requests surface a friendly error
        # (see users_store.py) instead of the process failing to boot.
        app.logger.error(str(e))

    return app
