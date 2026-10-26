import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, g, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

csrf = CSRFProtect()
_WEAK_SECRET_MARKERS = ("change-me", "changeme", "dev-change", "secret", "password", "example", "default")

SETUP_HELP = """\
Initialisation incomplète : aucun compte n'existe et ADMIN_PASSWORD n'est pas défini.
Deux façons sûres de créer le premier administrateur :
  1) définir ADMIN_USERNAME et ADMIN_PASSWORD (15 caractères minimum, pas de valeur courante) dans .env, puis redémarrer ;
  2) lancer :  docker compose run --rm logger python manage.py init-admin
     (un mot de passe aléatoire est affiché une seule fois dans le terminal et devra être changé à la première connexion)."""


class SetupError(RuntimeError):
    """Configuration de démarrage dangereuse ou incomplète : l'application refuse de démarrer."""


def _env_bool(name, default):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        raise SetupError(f"{name} doit être un nombre entier.")


def _check_secret_key(value):
    if len(value or "") < 32:
        raise SetupError("SECRET_KEY trop courte (32 caractères minimum). Laisse la variable vide : une clé aléatoire sera générée et "
                         "conservée dans appdata/.secret_key, ou génère-en une avec  python -c \"import secrets; print(secrets.token_hex(32))\"")
    if any(marker in value.lower() for marker in _WEAK_SECRET_MARKERS):
        raise SetupError("SECRET_KEY de démonstration ou prévisible refusée. Laisse la variable vide pour une clé aléatoire persistée.")


def _load_or_create_secret_key():
    from .db import appdata_root
    path = appdata_root() / ".secret_key"
    if path.exists():
        value = path.read_text().strip()
        _check_secret_key(value)
    else:
        value = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
    os.chmod(path, 0o600)
    return value


def create_app(test_config=None, *, require_admin=True):
    os.umask(0o077)                                   # fichiers créés en 0600, dossiers en 0700
    app = Flask(__name__)
    base = Path(app.root_path).parent
    production = os.environ.get("LOGGER_ENV", "production").strip().lower() != "development"
    absolute_hours = _env_int("SESSION_ABSOLUTE_HOURS", 12)
    app.config.from_mapping(
        PRODUCTION=production,
        SECRET_KEY=os.environ.get("SECRET_KEY") or None,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        APPDATA_DIR=os.environ.get("APPDATA_DIR", str(base / "appdata")),
        USERS_DIR=os.environ.get("USERS_DIR", str(base / "users")),
        # cookies de session
        SESSION_COOKIE_NAME="logger_session", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_bool("COOKIE_SECURE", production), SESSION_COOKIE_PATH="/",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=absolute_hours),
        SESSION_ABSOLUTE_SECONDS=absolute_hours * 3600,
        SESSION_IDLE_SECONDS=_env_int("SESSION_IDLE_MINUTES", 60) * 60,
        REAUTH_SECONDS=_env_int("REAUTH_MINUTES", 10) * 60,
        # requêtes
        MAX_CONTENT_LENGTH=_env_int("MAX_UPLOAD_MB", 50) * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=None,                     # le jeton est lié à la session, qui a sa propre expiration
        # réseau / en-têtes / journal
        TRUSTED_PROXIES=_env_int("TRUSTED_PROXIES", 0),
        HSTS_ENABLED=_env_bool("HSTS_ENABLED", False),
        CSP_REPORT_ONLY=_env_bool("CSP_REPORT_ONLY", False),
        SECURITY_LOG_RETENTION_DAYS=_env_int("SECURITY_LOG_RETENTION_DAYS", 180),
    )
    if test_config:
        app.config.update(test_config)
    app.config["APP_VERSION"] = (base / "VERSION").read_text().strip()

    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    n_proxies = app.config["TRUSTED_PROXIES"]
    if n_proxies > 0:                                 # en-têtes de proxy lus seulement si leur nombre est déclaré explicitement
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n_proxies, x_proto=n_proxies, x_host=n_proxies)
    if production and not app.config["SESSION_COOKIE_SECURE"]:
        app.logger.warning("COOKIE_SECURE=0 : le cookie de session circulera en clair (HTTP). À réserver à un réseau local de confiance.")

    from .auth import auth_bp, load_logged_in_user
    from .accounts import accounts_bp, init_accounts_db, count_accounts, create_account
    from .converter.views import converter_bp
    from .yamledit import yaml_bp
    from .converter.catalog import ensure_defaults
    from .refdata import init_airport_db, init_aircrafts_db
    from .db import startup_lock
    from .main import main_bp
    from .audit import audit_bp
    from .reports import reports_bp
    from .breakdown import breakdown_bp
    from .hubs import hubs_bp
    from .manual import manual_bp
    from .export import export_bp
    from .securityview import security_bp
    from .seclog import log_event

    Path(app.config["USERS_DIR"]).mkdir(parents=True, exist_ok=True)

    app.before_request(load_logged_in_user)           # avant CSRFProtect : g.user/g.csp_nonce existent pour les pages d'erreur
    csrf.init_app(app)

    with app.app_context(), startup_lock():
        if app.config["SECRET_KEY"]:
            _check_secret_key(app.config["SECRET_KEY"])
        else:
            app.config["SECRET_KEY"] = _load_or_create_secret_key()
        init_accounts_db()
        init_airport_db()
        init_aircrafts_db()
        ensure_defaults()
        if require_admin and count_accounts() == 0:
            password = app.config.get("ADMIN_PASSWORD", "")
            if not password:
                raise SetupError(SETUP_HELP)
            try:
                create_account(app.config["ADMIN_USERNAME"], password, role="admin")
            except ValueError as exc:
                raise SetupError(f"ADMIN_PASSWORD / ADMIN_USERNAME refusés : {exc}")
            log_event("admin_bootstrap", username=app.config["ADMIN_USERNAME"], reason="créé depuis la configuration d'environnement")
    app.config["ADMIN_PASSWORD"] = ""                 # ne reste pas en mémoire de configuration une fois l'initialisation faite

    for blueprint in (auth_bp, accounts_bp, converter_bp, yaml_bp, main_bp, audit_bp, reports_bp, breakdown_bp, hubs_bp, manual_bp, export_bp, security_bp):
        app.register_blueprint(blueprint)

    @app.route("/healthz")
    def healthz():
        return Response("ok", mimetype="text/plain")

    @app.context_processor
    def inject_nonce():
        return {"csp_nonce": g.get("csp_nonce", "")}

    @app.after_request
    def security_headers(response):
        headers, nonce = response.headers, g.get("csp_nonce", "")
        policy = "; ".join([
            "default-src 'self'", f"script-src 'self' 'nonce-{nonce}'", "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:", "font-src 'self'", "connect-src 'self'", "object-src 'none'",
            "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'"])
        headers.setdefault("Content-Security-Policy-Report-Only" if app.config["CSP_REPORT_ONLY"] else "Content-Security-Policy", policy)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.endpoint != "static":
            headers.setdefault("Cache-Control", "no-store")
        if app.config["HSTS_ENABLED"] and request.is_secure:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    messages = {400: "Requête invalide ou jeton de sécurité expiré : recharge la page et recommence.", 401: "Authentification requise.",
                403: "Accès refusé.", 404: "Page introuvable.", 405: "Méthode non autorisée.",
                413: "Fichier ou requête trop volumineux.", 429: "Trop de requêtes."}

    def error_response(code, message):
        if request.headers.get("Sec-Fetch-Mode", "navigate") != "navigate":      # fetch()/XHR : texte brut
            return Response(message, status=code, mimetype="text/plain")
        return render_template("error.html", code=code, message=message, request_id=g.get("request_id", "-")), code

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        log_event("csrf_failure", "denied", target=request.endpoint, reason=error.description)
        return error_response(400, messages[400])

    @app.errorhandler(HTTPException)
    def http_error(error):
        return error_response(error.code or 500, messages.get(error.code, "Erreur."))

    @app.errorhandler(Exception)
    def unhandled_error(error):
        app.logger.exception("Erreur non gérée (requête %s)", g.get("request_id", "-"))
        return error_response(500, "Erreur interne. Communique la référence ci-dessous à l'administrateur.")

    return app
