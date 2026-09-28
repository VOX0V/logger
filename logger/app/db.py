"""Low-level storage helpers: paths, SQLite connections, identifier safety.

Layout on disk:
    appdata/db/users.db, airport.db, aircrafts.db   (shared by every account)
    appdata/converter/                              (shared converter rules + settings)
    users/<username>/                               (each account's own data)

This module has no dependency on config.py or models.py so both can import
from it without circular imports.
"""
import contextlib
import re
import sqlite3
from pathlib import Path
from flask import current_app, g

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development machines
    fcntl = None


def safe_identifier(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Nom de colonne technique invalide: {value}")
    return value


def sqlite_type(dt):
    return {"integer": "INTEGER", "decimal": "REAL", "boolean": "INTEGER",
            "date": "TEXT", "datetime": "TEXT", "text": "TEXT"}.get(dt, "TEXT")


# --- shared application data (appdata/) ---

def appdata_root():
    return Path(current_app.config["APPDATA_DIR"])


@contextlib.contextmanager
def startup_lock():
    """Serialise first-run initialisation across gunicorn workers, which boot
    at the same time and would otherwise race to create the same files/rows."""
    appdata_root().mkdir(parents=True, exist_ok=True)
    with open(appdata_root() / ".startup.lock", "w") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def db_dir():
    path = appdata_root() / "db"
    path.mkdir(parents=True, exist_ok=True)
    return path


def converter_dir():
    path = appdata_root() / "converter"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def accounts_db_path(): return db_dir() / "users.db"
def airport_db_path(): return db_dir() / "airport.db"
def aircrafts_db_path(): return db_dir() / "aircrafts.db"


def accounts_connect(): return _open(accounts_db_path())
def airport_connect(): return _open(airport_db_path())
def aircrafts_connect(): return _open(aircrafts_db_path())


# --- per-user data (users/<username>/) ---

def users_root():
    return Path(current_app.config["USERS_DIR"])


def current_username():
    return getattr(g, "username", None)


def valid_username(username):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{3,32}", str(username or "")))


def user_root(username=None):
    username = username or current_username()
    if not username:
        raise RuntimeError("Aucun utilisateur courant.")
    if not valid_username(username):
        raise ValueError(f"Nom d'utilisateur invalide: {username}")
    return users_root() / username


def user_file(name, username=None):
    path = user_root(username)
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def db_path(username=None):
    username = username or current_username()
    return user_file(f"{username}_data.db", username)


def logbook_db_path(username=None):
    username = username or current_username()
    return user_file(f"{username}_logbook.db", username)


def connect(username=None): return _open(db_path(username))
def logbook_connect(username=None): return _open(logbook_db_path(username))
