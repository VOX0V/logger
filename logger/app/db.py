"""Low-level storage helpers: per-user paths, SQLite connections, identifier safety.

This module has no dependency on config.py or models.py so both can import
from it without circular imports.
"""
import re
import sqlite3
from pathlib import Path
from flask import current_app, g


def safe_identifier(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Nom de colonne technique invalide: {value}")
    return value


def sqlite_type(dt):
    return {"integer": "INTEGER", "decimal": "REAL", "boolean": "INTEGER",
            "date": "TEXT", "datetime": "TEXT", "text": "TEXT"}.get(dt, "TEXT")


def storage_root():
    return Path(current_app.config["STORAGE_DIR"])


def accounts_db_path():
    return storage_root() / "accounts.db"


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
    return storage_root() / "users" / username


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


def connect(username=None):
    conn = sqlite3.connect(db_path(username))
    conn.row_factory = sqlite3.Row
    return conn


def logbook_connect(username=None):
    conn = sqlite3.connect(logbook_db_path(username))
    conn.row_factory = sqlite3.Row
    return conn


def accounts_connect():
    path = accounts_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
