from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template, g

auth_bp = Blueprint("auth", __name__)


def load_logged_in_user():
    """Runs before every request: populate g.user/g.username/g.role from the session."""
    account_id = session.get("user_id")
    g.user = None
    g.username = None
    g.role = None
    if account_id:
        from .accounts import get_account_by_id  # lazy import: avoids a circular import with accounts.py
        account = get_account_by_id(account_id)
        if account:
            g.user = account
            g.username = account["username"]
            g.role = account["role"]
        else:
            session.clear()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        from .accounts import get_account_by_username, verify_password
        from .models import init_user_db
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        account = get_account_by_username(username)
        if verify_password(account, password):
            session.clear()
            session["user_id"] = account["id"]
            init_user_db(account["username"])  # defensive: recreate data folder/dbs if missing
            return redirect(url_for("main.index"))
        error = "Identifiants invalides"
    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login"))
        if g.get("role") != "admin":
            return redirect(url_for("main.index"))
        return view(*args, **kwargs)
    return wrapped
