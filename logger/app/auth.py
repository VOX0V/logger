"""Authentification : sessions (expiration inactive + absolue, révocation par version), connexion limitée,
déconnexion protégée CSRF, réauthentification récente pour les opérations sensibles."""
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from . import passwords
from .seclog import clear_pair, client_ip, is_blocked, log_event, normalize_username, record_failure

auth_bp = Blueprint("auth", __name__)

GENERIC_LOGIN_ERROR = "Invalid credentials or too many attempts. Try again later."
EXEMPT_ENDPOINTS = {"static", "healthz"}
FORCED_CHANGE_ALLOWED = {"accounts.me", "accounts.revoke_my_sessions", "auth.logout", "static", "healthz"}


def _navigation():
    """Vrai pour une navigation du navigateur ; faux pour un fetch()/XHR (qui doit recevoir un code HTTP, pas une redirection)."""
    return request.headers.get("Sec-Fetch-Mode", "navigate") == "navigate"


def _unauthenticated():
    if _navigation():
        return redirect(url_for("auth.login"))
    return Response("Authentification requise.", status=401, mimetype="text/plain")


def start_session(account):
    """Session fraîche (jamais de réutilisation de l'ancienne) liée à la version de session du compte."""
    session.clear()
    now = time.time()
    session.permanent = True
    session["user_id"] = account["id"]
    session["sv"] = account["session_version"]
    session["login_at"] = now
    session["last_seen"] = now
    session["auth_at"] = now


def load_logged_in_user():
    """Avant chaque requête : identifiant de requête, nonce CSP, puis utilisateur depuis une session valide."""
    g.request_id = secrets.token_hex(6)
    g.csp_nonce = secrets.token_urlsafe(16)
    g.user = g.username = g.role = None
    if request.endpoint in EXEMPT_ENDPOINTS:
        return None
    account_id = session.get("user_id")
    if account_id is None:
        return None
    cfg, now = current_app.config, time.time()
    try:
        login_at, last_seen = float(session["login_at"]), float(session["last_seen"])
    except (KeyError, TypeError, ValueError):
        login_at = last_seen = 0.0
    expired = now - login_at > cfg["SESSION_ABSOLUTE_SECONDS"] or now - last_seen > cfg["SESSION_IDLE_SECONDS"]
    from .accounts import get_account_by_id            # import tardif : accounts.py importe ce module
    account = None if expired else get_account_by_id(account_id)
    if account is None or not account["active"] or session.get("sv") != account["session_version"]:
        session.clear()
        log_event("session_invalid", "denied", account_id=account_id if isinstance(account_id, int) else None,
                  reason="expired" if expired else "revoked, inactive or deleted account")
        return None
    g.user, g.username, g.role = account, account["username"], account["role"]
    session["last_seen"] = now
    session.permanent = True
    if account["must_change"] and request.endpoint not in FORCED_CHANGE_ALLOWED:
        if not _navigation():
            return Response("Password change required.", status=403, mimetype="text/plain")
        flash("Choose a new password to continue.")
        return redirect(url_for("accounts.me"))
    return None


def safe_next(candidate):
    """Redirection interne uniquement (jamais d'URL absolue ou protocole-relative)."""
    if candidate and candidate.startswith("/") and not candidate.startswith("//") and "\\" not in candidate:
        parsed = urlparse(candidate)
        if not parsed.scheme and not parsed.netloc:
            return candidate
    return url_for("main.home")


def verify_with_throttle(account, password, *, event):
    """Vérifie le mot de passe d'un compte connecté avec les mêmes limites que la connexion."""
    from .accounts import verify_password
    ip, name = client_ip(), normalize_username(account["username"])
    if is_blocked(name, ip):
        passwords.burn(password)
        log_event(f"{event}_blocked", "denied")
        return False
    if verify_password(account, password):
        clear_pair(name, ip)
        return True
    record_failure(name, ip)
    log_event(f"{event}_failure", "denied")
    return False


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if g.get("user") is not None:
            return redirect(url_for("main.home"))
        return render_template("login.html", error=None)
    from .accounts import get_account_by_username, verify_password
    from .db import valid_username
    from .models import init_user_db
    raw_username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip, name = client_ip(), normalize_username(raw_username)
    if is_blocked(name, ip):
        passwords.burn(password)
        log_event("login_blocked", "denied", username=name)
        return render_template("login.html", error=GENERIC_LOGIN_ERROR), 401
    account = get_account_by_username(name) if valid_username(name) else None
    ok = verify_password(account, password)           # une vérification complète, même si le compte n'existe pas
    if ok and account["active"]:
        start_session(account)
        clear_pair(name, ip)
        init_user_db(account["username"])             # defensive: recrée le dossier/les bases si absents
        log_event("login_success", account_id=account["id"], username=account["username"])
        return redirect(url_for("main.home"))
    record_failure(name, ip)
    log_event("login_failure", "denied", username=name, reason="account disabled" if ok else None)
    return render_template("login.html", error=GENERIC_LOGIN_ERROR), 401   # même réponse dans tous les cas d'échec


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if g.get("user") is not None:
        log_event("logout")
    session.clear()
    return redirect(url_for("auth.login"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return _unauthenticated()
        return view(*args, **kwargs)
    wrapped.requires_login = True          # marqueur lu par les tests : aucune route ne doit être oubliée
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return _unauthenticated()
        if g.get("role") != "admin":
            log_event("access_denied", "denied", target=request.endpoint)
            abort(403)
        return view(*args, **kwargs)
    wrapped.requires_admin = True
    wrapped.requires_login = True
    return wrapped


def _referrer_path():
    ref = urlparse(request.referrer or "")
    if ref.netloc == request.host and ref.path:
        return ref.path + (f"?{ref.query}" if ref.query else "")
    return None


def fresh_login_required(view):
    """Opération sensible : exige une saisie du mot de passe datant de moins de REAUTH_SECONDS."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return _unauthenticated()
        if time.time() - float(session.get("auth_at", 0)) > current_app.config["REAUTH_SECONDS"]:
            if not _navigation():
                return Response("Re-authentication required.", status=401, mimetype="text/plain")
            target = request.full_path.rstrip("?") if request.method == "GET" else _referrer_path()
            flash("For this sensitive action, first confirm your password, then try again.")
            return redirect(url_for("auth.reauth", next=safe_next(target)))
        return view(*args, **kwargs)
    return wrapped


@auth_bp.route("/reauth", methods=["GET", "POST"])
@login_required
def reauth():
    target = safe_next(request.values.get("next"))
    error = None
    if request.method == "POST":
        if verify_with_throttle(g.user, request.form.get("password", ""), event="reauth"):
            session["auth_at"] = time.time()
            log_event("reauth")
            return redirect(target)
        error = "Incorrect password or too many attempts. Try again later."
    return render_template("reauth.html", error=error, next=target), (401 if error else 200)
