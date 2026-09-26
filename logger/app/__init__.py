from flask import Flask
from pathlib import Path
from .models import init_db


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(SECRET_KEY="dev-change-me")
    app.config.from_prefixed_env()
    import os
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", app.config["SECRET_KEY"])
    version_file = Path(app.root_path).parent / "VERSION"
    app.config["APP_VERSION"] = version_file.read_text().strip() if version_file.exists() else "dev"
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)
    from .auth import auth_bp
    from .main import main_bp
    from .admin import admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    return app
