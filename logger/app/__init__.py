import os
from pathlib import Path
from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "change-me"),
        STORAGE_DIR=os.environ.get("STORAGE_DIR", str(Path(app.root_path).parent / "storage")),
    )
    app.config["APP_VERSION"] = (Path(app.root_path).parent / "VERSION").read_text().strip()

    Path(app.config["STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    (Path(app.config["STORAGE_DIR"]) / "users").mkdir(parents=True, exist_ok=True)

    from .auth import auth_bp, load_logged_in_user
    from .accounts import accounts_bp, init_accounts_db, count_accounts, create_account
    from .main import main_bp

    app.before_request(load_logged_in_user)

    with app.app_context():
        init_accounts_db()
        if count_accounts() == 0:
            create_account(app.config["ADMIN_USERNAME"], app.config["ADMIN_PASSWORD"], role="admin")

    app.register_blueprint(auth_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(main_bp)
    return app
