import os
from pathlib import Path
from flask import Flask


def create_app():
    app = Flask(__name__)
    base = Path(app.root_path).parent
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "change-me"),
        APPDATA_DIR=os.environ.get("APPDATA_DIR", str(base / "appdata")),
        USERS_DIR=os.environ.get("USERS_DIR", str(base / "users")),
    )
    app.config["APP_VERSION"] = (base / "VERSION").read_text().strip()

    Path(app.config["USERS_DIR"]).mkdir(parents=True, exist_ok=True)

    from .auth import auth_bp, load_logged_in_user
    from .accounts import accounts_bp, init_accounts_db, count_accounts, create_account
    from .converter.views import converter_bp
    from .converter.catalog import ensure_defaults
    from .refdata import init_airport_db, init_aircrafts_db
    from .db import startup_lock
    from .main import main_bp

    app.before_request(load_logged_in_user)

    with app.app_context(), startup_lock():
        init_accounts_db()
        init_airport_db()
        init_aircrafts_db()
        ensure_defaults()
        if count_accounts() == 0:
            create_account(app.config["ADMIN_USERNAME"], app.config["ADMIN_PASSWORD"], role="admin")

    app.register_blueprint(auth_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(converter_bp)
    app.register_blueprint(main_bp)
    return app
