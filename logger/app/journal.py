"""Journal des imports et des conversions.

Chaque import validé et chaque conversion validée laisse une entrée dans users/<nom>/<nom>_journal.db :
- import : la liste des identifiants des lignes AJOUTÉES à la base brute (annuler = retirer ces lignes seulement) ;
- conversion : une copie de la base de travail d'avant la conversion (annuler = revenir à cet état).
Le nombre d'entrées conservées par type est réglé dans appdata/journal.yml (copie de defaults/journal.yml) :
les plus anciennes sont supprimées (et leurs copies avec elles).
"""
import json
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import current_app

from .db import appdata_root, connect, current_username, logbook_db_path, user_file, user_root

DEFAULT_LIMITS = {"max_imports": 10, "max_conversions": 10}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def limits():
    """{'max_imports': n, 'max_conversions': n} : appdata/journal.yml (copié depuis defaults/ la première fois)."""
    path = appdata_root() / "journal.yml"
    if not path.exists():
        try:
            appdata_root().mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(current_app.root_path).parent / "defaults" / "journal.yml", path)
        except OSError:
            pass
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, yaml.YAMLError):
        data = {}
    out = {}
    for key, default in DEFAULT_LIMITS.items():
        try:
            out[key] = max(1, int(data.get(key, default)))
        except (TypeError, ValueError):
            out[key] = default
    return out


def _conn():
    conn = sqlite3.connect(user_file(f"{current_username()}_journal.db"), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, created_at TEXT NOT NULL,"
                 " label TEXT, summary TEXT, payload TEXT, snapshot TEXT)")
    return conn


def _snapshot_dir():
    path = user_root() / "journal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_snapshot(name):
    if name:
        try:
            (_snapshot_dir() / Path(name).name).unlink()
        except OSError:
            pass


def _prune(conn, kind):
    keep = limits()["max_imports" if kind == "import" else "max_conversions"]
    old = conn.execute("SELECT id, snapshot FROM journal WHERE kind=? ORDER BY id DESC LIMIT -1 OFFSET ?", (kind, keep)).fetchall()
    for row in old:
        _remove_snapshot(row["snapshot"])
        conn.execute("DELETE FROM journal WHERE id=?", (row["id"],))


def snapshot_work_db():
    """Copie cohérente de la base de travail actuelle ; renvoie le nom du fichier de copie."""
    name = f"convert_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.db"
    target = _snapshot_dir() / name
    src = sqlite3.connect(logbook_db_path(), timeout=15)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    return name


def record_import(label, summary, inserted_ids):
    conn = _conn()
    try:
        conn.execute("INSERT INTO journal (kind, created_at, label, summary, payload) VALUES ('import', ?, ?, ?, ?)",
                     (now(), label, json.dumps(summary), json.dumps({"ids": list(inserted_ids)})))
        _prune(conn, "import")
        conn.commit()
    finally:
        conn.close()


def record_conversion(summary, snapshot):
    conn = _conn()
    try:
        conn.execute("INSERT INTO journal (kind, created_at, label, summary, snapshot) VALUES ('convert', ?, ?, ?, ?)",
                     (now(), "Conversion", json.dumps(summary), snapshot))
        _prune(conn, "convert")
        conn.commit()
    finally:
        conn.close()


def list_entries(kind):
    conn = _conn()
    try:
        out = []
        for row in conn.execute("SELECT * FROM journal WHERE kind=? ORDER BY id DESC", (kind,)):
            try:
                summary = json.loads(row["summary"] or "{}")
            except ValueError:
                summary = {}
            entry = {"id": row["id"], "created_at": row["created_at"], "label": row["label"], "summary": summary}
            if kind == "import":
                try:
                    entry["rows"] = len(json.loads(row["payload"] or "{}").get("ids", []))
                except ValueError:
                    entry["rows"] = 0
            else:
                entry["available"] = bool(row["snapshot"]) and (_snapshot_dir() / Path(row["snapshot"]).name).exists()
            out.append(entry)
        return out
    finally:
        conn.close()


def undo_import(entry_id):
    """Retire de la base brute les lignes ajoutées par cet import (rien d'autre). Renvoie le nombre de lignes retirées."""
    conn = _conn()
    try:
        row = conn.execute("SELECT payload FROM journal WHERE id=? AND kind='import'", (entry_id,)).fetchone()
        if row is None:
            raise ValueError("This import is no longer in the journal.")
        ids = [int(i) for i in json.loads(row["payload"] or "{}").get("ids", [])]
        removed = 0
        raw = connect()
        try:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                removed += raw.execute(f"DELETE FROM users WHERE technical_raw_id IN ({','.join('?' * len(chunk))})", chunk).rowcount
            raw.commit()
        finally:
            raw.close()
        conn.execute("DELETE FROM journal WHERE id=?", (entry_id,))
        conn.commit()
        return removed
    finally:
        conn.close()


def undo_conversion(entry_id):
    """Remet la base de travail dans l'état d'avant cette conversion."""
    conn = _conn()
    try:
        row = conn.execute("SELECT snapshot FROM journal WHERE id=? AND kind='convert'", (entry_id,)).fetchone()
        if row is None:
            raise ValueError("This conversion is no longer in the journal.")
        source = _snapshot_dir() / Path(row["snapshot"] or "").name
        if not row["snapshot"] or not source.exists():
            raise ValueError("The saved state of this conversion is missing.")
        src = sqlite3.connect(source)
        dst = sqlite3.connect(logbook_db_path(), timeout=15)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
        _remove_snapshot(row["snapshot"])
        conn.execute("DELETE FROM journal WHERE id=?", (entry_id,))
        conn.commit()
    finally:
        conn.close()


def clear(kind):
    """Empties the journal of one kind ('import' or 'convert') and deletes the saved states of the conversions."""
    conn = _conn()
    try:
        for row in conn.execute("SELECT snapshot FROM journal WHERE kind=?", (kind,)).fetchall():
            _remove_snapshot(row["snapshot"])
        conn.execute("DELETE FROM journal WHERE kind=?", (kind,))
        conn.commit()
    finally:
        conn.close()
