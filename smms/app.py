import os
from flask import Flask, jsonify, send_from_directory
from .config import Config
from .db import close_db, init_db

def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.from_object(Config)
    if config: app.config.update(config)
    if not os.path.exists(app.config["DATABASE"]) or app.config["DATABASE"] == ":memory:":
        init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)
    from .services import iam, collection, ticketing, recommend, ar, analytics, audit
    for m in (iam, collection, ticketing, recommend, ar, analytics, audit):
        app.register_blueprint(m.bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/verify")
    @app.get("/reset")
    def email_links():                      # targets of the e-mail links (FR-01, FR-05); the client reads ?token=
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(404)
    def nf(e): return jsonify(error="not found"), 404
    @app.errorhandler(405)
    def na(e): return jsonify(error="method not allowed"), 405
    @app.errorhandler(Exception)
    def boom(e):
        if hasattr(e, "code") and isinstance(e.code, int): return jsonify(error=str(e)), e.code
        app.logger.exception(e); return jsonify(error="internal error"), 500
    return app
