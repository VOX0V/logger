"""Gestion des comptes : base globale appdata/db/users.db, indépendante des données de chaque utilisateur.

Sécurité : hachage Argon2id (anciens hachages migrés à la connexion), politique de mot de passe, comptes
désactivables, version de session (révocation immédiate), dernier administrateur protégé, réauthentification
récente pour toute opération sensible, journal d'audit.
"""
import re
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session

from . import passwords
from .auth import admin_required, login_required, fresh_login_required, start_session, verify_with_throttle
from .db import accounts_connect, accounts_db_path, archive_user_dir, valid_username
from .models import init_user_db
from .seclog import init_security_tables, log_event

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")
ROLES = ("admin", "user")

# colonnes ajoutées après la version 0.1.x (migration automatique, avec sauvegarde préalable)
_NEW_COLUMNS = {
    "email": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 1",
    "session_version": "INTEGER NOT NULL DEFAULT 0",
    "must_change": "INTEGER NOT NULL DEFAULT 0",
    "password_changed_at": "TEXT",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backup_accounts_db():
    """Copie cohérente de users.db avant toute migration de schéma (plan de retour arrière)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = accounts_db_path().with_name(f"users.db.pre-migration-{stamp}.bak")
    source, dest = accounts_connect(), sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close(); source.close()
    return target


def init_accounts_db():
    conn = accounts_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        email TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        session_version INTEGER NOT NULL DEFAULT 0,
        must_change INTEGER NOT NULL DEFAULT 0,
        password_changed_at TEXT
    )""")
    existing = {r[1] for r in conn.execute("PRAGMA table_info(accounts)")}
    missing = {k: v for k, v in _NEW_COLUMNS.items() if k not in existing}
    if missing:
        conn.commit(); conn.close()
        _backup_accounts_db()
        conn = accounts_connect()
        for name, decl in missing.items():
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {name} {decl}")
    try:                                                    # unicité insensible à la casse (si aucun doublon existant)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_username_nocase ON accounts(username COLLATE NOCASE)")
    except sqlite3.IntegrityError:
        pass
    init_security_tables(conn)
    conn.commit(); conn.close()


def count_accounts():
    conn = accounts_connect(); n = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]; conn.close(); return n


def count_admins(exclude_id=None):
    """Nombre d'administrateurs ACTIFS (hors `exclude_id`)."""
    conn = accounts_connect()
    if exclude_id:
        n = conn.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND active=1 AND id!=?", (exclude_id,)).fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND active=1").fetchone()[0]
    conn.close(); return n


def list_accounts():
    conn = accounts_connect()
    rows = conn.execute("SELECT id, username, role, active, must_change, created_at FROM accounts ORDER BY username").fetchall()
    conn.close(); return rows


def get_account_by_id(account_id):
    conn = accounts_connect()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close(); return row


def get_account_by_username(username):
    conn = accounts_connect()
    row = conn.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    conn.close(); return row


def create_account(username, password, role="user", *, must_change=False):
    username = (username or "").strip()
    if not valid_username(username):
        raise ValueError("Nom d'utilisateur invalide (3-32 caractères, lettres/chiffres/_/-).")
    if role not in ROLES:
        raise ValueError("Rôle invalide.")
    passwords.check_policy(password, username)
    if get_account_by_username(username):
        raise ValueError("Ce nom d'utilisateur existe déjà.")
    conn = accounts_connect()
    try:
        conn.execute("INSERT INTO accounts (username, password_hash, role, must_change, password_changed_at) VALUES (?,?,?,?,?)",
                     (username, passwords.hash_password(password), role, 1 if must_change else 0, _now_iso()))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("Ce nom d'utilisateur existe déjà.")
    finally:
        conn.close()
    archive_user_dir(username)      # dossier orphelin d'un ancien compte du même nom : mis de côté, jamais hérité
    init_user_db(username)
    return get_account_by_username(username)


def _bump_sessions(conn, account_id):
    conn.execute("UPDATE accounts SET session_version = session_version + 1 WHERE id=?", (account_id,))


def set_password(account_id, new_password, *, must_change=False):
    """Change le mot de passe et révoque TOUTES les sessions du compte."""
    account = get_account_by_id(account_id)
    if not account:
        raise ValueError("Compte introuvable.")
    passwords.check_policy(new_password, account["username"])
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET password_hash=?, must_change=?, password_changed_at=? WHERE id=?",
                 (passwords.hash_password(new_password), 1 if must_change else 0, _now_iso(), account_id))
    _bump_sessions(conn, account_id)
    conn.commit(); conn.close()


def revoke_sessions(account_id):
    conn = accounts_connect(); _bump_sessions(conn, account_id); conn.commit(); conn.close()


def set_email(account_id, email):
    """Adresse e-mail du propriétaire du logbook (imprimée en bas des pages). Vide = effacer."""
    email = (email or "").strip()
    if email and (len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
        raise ValueError("Adresse e-mail invalide.")
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET email=? WHERE id=?", (email or None, account_id))
    conn.commit(); conn.close()


def _is_last_active_admin(account):
    return account["role"] == "admin" and account["active"] and count_admins(exclude_id=account["id"]) == 0


def set_role(account_id, role):
    if role not in ROLES:
        raise ValueError("Rôle invalide.")
    account = get_account_by_id(account_id)
    if not account:
        raise ValueError("Compte introuvable.")
    if role == account["role"]:
        return
    if role != "admin" and _is_last_active_admin(account):
        raise ValueError("Impossible de retirer le dernier administrateur.")
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET role=? WHERE id=?", (role, account_id))
    _bump_sessions(conn, account_id)                      # changement de privilège : les sessions existantes sont révoquées
    conn.commit(); conn.close()


def set_active(account_id, active):
    account = get_account_by_id(account_id)
    if not account:
        raise ValueError("Compte introuvable.")
    if bool(account["active"]) == bool(active):
        return
    if not active and _is_last_active_admin(account):
        raise ValueError("Impossible de désactiver le dernier administrateur.")
    conn = accounts_connect()
    conn.execute("UPDATE accounts SET active=? WHERE id=?", (1 if active else 0, account_id))
    if not active:
        _bump_sessions(conn, account_id)
    conn.commit(); conn.close()


def delete_account(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return None
    if _is_last_active_admin(account):
        raise ValueError("Impossible de supprimer le dernier administrateur.")
    conn = accounts_connect()
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit(); conn.close()
    archive_user_dir(account["username"])                 # données conservées à part (users/.deleted/), pas effacées
    return account


def verify_password(account, password, *, upgrade=True):
    """Vérifie un mot de passe ; sur compte inexistant, dépense le même temps (pas de fuite par le temps de réponse).
    Un ancien hachage valide est remplacé par un hachage Argon2id aux paramètres actuels."""
    if not account:
        passwords.burn(password if isinstance(password, str) else "")
        return False
    ok = passwords.verify(account["password_hash"], password)
    if ok and upgrade and passwords.needs_rehash(account["password_hash"]):
        conn = accounts_connect()
        conn.execute("UPDATE accounts SET password_hash=? WHERE id=?", (passwords.hash_password(password), account["id"]))
        conn.commit(); conn.close()
    return ok


# --- Routes ---

@accounts_bp.route("/me", methods=["GET", "POST"])
@login_required
def me():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "email":
            try:
                set_email(g.user["id"], request.form.get("email", ""))
                flash("Adresse e-mail enregistrée.")
            except ValueError as exc:
                flash(str(exc))
            return redirect(url_for("accounts.me"))
        if action == "pilot":
            from .converter import catalog
            catalog.save_profile(request.form.get("pilot_name", ""), request.form.get("first_name", ""),
                                 request.form.get("employee_number", ""), g.username)
            flash("Identité enregistrée. Clique sur Actualiser dans logbook.db pour appliquer le nom de famille.")
            return redirect(url_for("accounts.me"))
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not verify_with_throttle(g.user, current, event="password_change"):
            flash("Mot de passe actuel incorrect (ou trop de tentatives, réessaie plus tard).")
        elif new != confirm:
            flash("La confirmation ne correspond pas au nouveau mot de passe.")
        else:
            try:
                set_password(g.user["id"], new)
            except ValueError as exc:
                flash(str(exc))
            else:
                start_session(get_account_by_id(g.user["id"]))      # session fraîche ; les autres sessions sont révoquées
                log_event("password_change", account_id=g.user["id"], username=g.username, reason="autres sessions révoquées")
                flash("Mot de passe modifié. Les autres sessions ont été déconnectées.")
        return redirect(url_for("accounts.me"))
    from .converter import catalog
    return render_template("account_me.html", profile=catalog.load_profile(g.username))


@accounts_bp.route("/me/revoke-sessions", methods=["POST"])
@login_required
def revoke_my_sessions():
    account_id = g.user["id"]
    revoke_sessions(account_id)
    log_event("sessions_revoked", account_id=account_id, username=g.username, target="self")
    session.clear()
    flash("Toutes tes sessions ont été déconnectées. Reconnecte-toi.")
    return redirect(url_for("auth.login"))


@accounts_bp.route("")
@admin_required
def list_view():
    return render_template("accounts_list.html", accounts=list_accounts())


@accounts_bp.route("/new", methods=["GET", "POST"])
@admin_required
@fresh_login_required
def new_account():
    if request.method == "POST":
        try:
            role = request.form.get("role", "user")
            account = create_account(request.form.get("username", ""), request.form.get("password", ""), role, must_change=True)
            log_event("account_create", target=f"{account['username']} role={role}")
            flash("Compte créé. L'utilisateur devra choisir un nouveau mot de passe à sa première connexion.")
            return redirect(url_for("accounts.list_view"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("account_form.html", account=None)


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@admin_required
@fresh_login_required
def edit_account(account_id):
    account = get_account_by_id(account_id)
    if not account:
        flash("Compte introuvable."); return redirect(url_for("accounts.list_view"))
    is_self = account_id == g.user["id"]
    if request.method == "POST":
        try:
            new_password = request.form.get("password", "")
            role = request.form.get("role", account["role"])
            active = request.form.get("active") == "1"
            if is_self and (role != account["role"] or not active):
                raise ValueError("Tu ne peux pas modifier ton propre rôle ni désactiver ton propre compte.")
            if new_password:
                if is_self:
                    raise ValueError("Pour changer ton propre mot de passe, utilise « Mon compte ».")
                set_password(account_id, new_password, must_change=True)
                log_event("password_reset_by_admin", target=account["username"])
            if role != account["role"]:
                set_role(account_id, role)
                log_event("account_role_change", target=account["username"], reason=f"{account['role']} -> {role}")
            if bool(account["active"]) != active:
                set_active(account_id, active)
                log_event("account_enable" if active else "account_disable", target=account["username"])
            flash("Compte modifié.")
            return redirect(url_for("accounts.list_view"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("account_form.html", account=account)


@accounts_bp.route("/<int:account_id>/revoke-sessions", methods=["POST"])
@admin_required
@fresh_login_required
def revoke_account_sessions(account_id):
    account = get_account_by_id(account_id)
    if not account:
        flash("Compte introuvable."); return redirect(url_for("accounts.list_view"))
    revoke_sessions(account_id)
    log_event("sessions_revoked", target=account["username"])
    flash("Sessions révoquées." if account_id != g.user["id"] else "Sessions révoquées (la tienne sera invalidée).")
    return redirect(url_for("accounts.list_view"))


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@admin_required
@fresh_login_required
def delete_account_route(account_id):
    if account_id == g.user["id"]:
        flash("Tu ne peux pas supprimer ton propre compte.")
        return redirect(url_for("accounts.list_view"))
    try:
        account = delete_account(account_id)
        if account:
            log_event("account_delete", target=account["username"], reason="données archivées dans users/.deleted/")
        flash("Compte supprimé. Ses données ont été mises de côté dans users/.deleted/ (non effacées).")
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for("accounts.list_view"))
