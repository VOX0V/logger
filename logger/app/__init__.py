import os
from pathlib import Path
from flask import Flask
from .models import init_db

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"), ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"), ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "change-me"))
    app.config["APP_VERSION"] = (Path(app.root_path).parent / "VERSION").read_text().strip()
    os.makedirs(app.instance_path, exist_ok=True)
    init_db(app)
    from .auth import auth_bp
    from .main import main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    return app
