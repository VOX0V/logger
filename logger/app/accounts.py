"""Account management: a single global accounts.db shared by every user,
independent from each user's own data (users/<username>/*.db)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .db import accounts_connect, valid_username
from .auth import admin_required
from .models import init_user_db

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")


def init_accounts_db():
    conn = accounts_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()


def count_accounts():
    conn = accounts_connect(); n = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]; conn.close(); return n


def count_admins(exclude_id=None):
    conn = accounts_connect()
    if exclude_id:
        n = conn.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND id!=?", (exclude_id,)).fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM accounts WHERE role='admin'").fetchone()[0]
    conn.close(); return n


def list_accounts():
    conn = accounts_connect()
    rows = conn.execute("SELECT id, username, role, created_at FROM accounts ORDER BY username").fetchall()
    conn.close(); return rows


def get_account_by_id(account_id):
    conn = accounts_connect()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close(); return row


def get_account_by_username(username):
    conn = accounts_connect()
    row = conn.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    conn.close(); return row


def create_account(username, password, role="user"):
    username = (username or "").strip()
    if not valid_username(username):
        raise ValueError("Nom d'utilisateur invalide (3-32 caractères, lettres/chiffres/_/-).")
    if not password:
        raise ValueError("Mot de passe obligatoire.")
    if get_account_by_username(username):
        raise ValueError("Ce nom d'utilisateur existe déjà.")
    if role not in ("admin", "user"):
        role = "user"
    conn = accounts_connect()
    conn.execute("INSERT INTO accounts (username, password_hash, role) VALUES (?,?,?)",
                 (username, generate_password_hash(password), role))
    conn.commit(); conn.close()
    init_user_db(username)
    return get_account_by_username(username)


def set_password(account_id, new_password):
    if not new_password:
        raise ValueError("Mot de passe obligatoire.")
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET password_hash=? WHERE id=?", (generate_password_hash(new_password), account_id))
    conn.commit(); conn.close()


def set_role(account_id, role):
    if role not in ("admin", "user"):
        raise ValueError("Rôle invalide.")
    if role != "admin" and count_admins(exclude_id=account_id) == 0:
        raise ValueError("Impossible de retirer le dernier administrateur.")
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET role=? WHERE id=?", (role, account_id))
    conn.commit(); conn.close()


def delete_account(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return
    if account["role"] == "admin" and count_admins(exclude_id=account_id) == 0:
        raise ValueError("Impossible de supprimer le dernier administrateur.")
    conn = accounts_connect()
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit(); conn.close()
    # Le dossier de données de l'utilisateur (users/<username>/) n'est PAS supprimé automatiquement.


def verify_password(account, password):
    return bool(account) and check_password_hash(account["password_hash"], password or "")


# --- Routes (admin only) ---

@accounts_bp.route("")
@admin_required
def list_view():
    return render_template("accounts_list.html", accounts=list_accounts())


@accounts_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_account():
    if request.method == "POST":
        try:
            create_account(request.form.get("username", ""), request.form.get("password", ""), request.form.get("role", "user"))
            flash("Compte créé.")
            return redirect(url_for("accounts.list_view"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("account_form.html", account=None)


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_account(account_id):
    account = get_account_by_id(account_id)
    if not account:
        flash("Compte introuvable."); return redirect(url_for("accounts.list_view"))
    if request.method == "POST":
        try:
            new_password = request.form.get("password", "").strip()
            if new_password:
                set_password(account_id, new_password)
            set_role(account_id, request.form.get("role", account["role"]))
            flash("Compte modifié.")
            return redirect(url_for("accounts.list_view"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("account_form.html", account=account)


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@admin_required
def delete_account_route(account_id):
    try:
        delete_account(account_id)
        flash("Compte supprimé.")
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for("accounts.list_view"))
