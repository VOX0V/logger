"""Journal de sécurité (audit) et limitation des tentatives de connexion.

Tables dans appdata/db/users.db :
  security_events  : journal structuré (UTC, événement, résultat, compte, IP, id de requête, cible, raison)
  login_failures   : échecs de connexion récents pour la limitation (purgés après 24 h)

Jamais de mot de passe, cookie, jeton CSRF ou secret dans ces tables ni dans les logs.
"""
import ipaddress
import json
import re
import time
from datetime import datetime, timezone

from flask import current_app, g, has_request_context, request

from .db import accounts_connect

WINDOW_SECONDS = 15 * 60
DEFAULT_LIMITS = {"pair": 5, "ip": 20, "account": 40}      # échecs par fenêtre : (compte+IP), IP seule, compte seul
FLOOD_THRESHOLD = 100                                      # échecs en 5 minutes (toutes sources) -> alerte
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
_last_purge = 0.0
_last_flood_alert = 0.0


def now():
    """Horloge unique (remplaçable dans les tests)."""
    return time.time()


def clean(value, limit=200):
    """Neutralise les caractères de contrôle (injection de lignes CR/LF) et borne la taille."""
    return _CONTROL.sub(" ", str(value if value is not None else ""))[:limit]


def utc_iso(ts=None):
    return datetime.fromtimestamp(now() if ts is None else ts, timezone.utc).isoformat(timespec="seconds")


def client_ip():
    """Adresse du pair TCP (ou celle réécrite par ProxyFix si TRUSTED_PROXIES > 0). Jamais un en-tête brut."""
    if not has_request_context():
        return "local"
    try:
        return str(ipaddress.ip_address(request.remote_addr or ""))
    except ValueError:
        return "inconnue"


def normalize_username(username):
    return clean(username, 64).strip().lower()


def init_security_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event TEXT NOT NULL, outcome TEXT NOT NULL,
        account_id INTEGER, username TEXT, ip TEXT, request_id TEXT, target TEXT, reason TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_security_events_ts ON security_events(ts)")
    conn.execute("""CREATE TABLE IF NOT EXISTS login_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, username TEXT NOT NULL, ip TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_failures_ts ON login_failures(ts)")


def log_event(event, outcome="ok", *, account_id=None, username=None, target=None, reason=None):
    """Enregistre un événement de sécurité. Ne lève jamais d'exception vers l'appelant."""
    try:
        if account_id is None and has_request_context() and g.get("user") is not None:
            account_id = g.user["id"]
        record = {
            "ts": utc_iso(), "event": clean(event, 64), "outcome": clean(outcome, 16),
            "account_id": account_id, "username": clean(username, 64) if username else None,
            "ip": client_ip(), "request_id": clean(g.get("request_id", "-"), 32) if has_request_context() else "-",
            "target": clean(target, 120) if target else None, "reason": clean(reason, 200) if reason else None,
        }
        conn = accounts_connect()
        try:
            conn.execute("INSERT INTO security_events (ts,event,outcome,account_id,username,ip,request_id,target,reason)"
                         " VALUES (:ts,:event,:outcome,:account_id,:username,:ip,:request_id,:target,:reason)", record)
            conn.commit()
        finally:
            conn.close()
        current_app.logger.info("security %s", json.dumps(record, ensure_ascii=False))
        maybe_purge()
    except Exception:                                   # le journal ne doit jamais casser une requête
        current_app.logger.exception("Security log write impossible")


def maybe_purge(force=False):
    """Rétention : événements > SECURITY_LOG_RETENTION_DAYS jours, échecs de connexion > 24 h (au plus 1×/heure)."""
    global _last_purge
    t = now()
    if not force and t - _last_purge < 3600:
        return
    _last_purge = t
    days = int(current_app.config.get("SECURITY_LOG_RETENTION_DAYS", 180))
    conn = accounts_connect()
    try:
        conn.execute("DELETE FROM security_events WHERE ts < ?", (utc_iso(t - days * 86400),))
        conn.execute("DELETE FROM login_failures WHERE ts < ?", (t - 86400,))
        conn.commit()
    finally:
        conn.close()


def list_events(limit=300, event=None):
    conn = accounts_connect()
    try:
        if event:
            rows = conn.execute("SELECT * FROM security_events WHERE event=? ORDER BY id DESC LIMIT ?", (event, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return rows
    finally:
        conn.close()


# ---------------- limitation des tentatives (fenêtre glissante) ----------------

def _limits():
    return {**DEFAULT_LIMITS, **current_app.config.get("LOGIN_LIMITS", {})}


def is_blocked(username, ip):
    """Vrai si l'une des trois limites est atteinte. Réponse identique pour compte inexistant ou existant."""
    limits, since = _limits(), now() - WINDOW_SECONDS
    conn = accounts_connect()
    try:
        pair = conn.execute("SELECT COUNT(*) FROM login_failures WHERE ts>? AND username=? AND ip=?", (since, username, ip)).fetchone()[0]
        by_ip = conn.execute("SELECT COUNT(*) FROM login_failures WHERE ts>? AND ip=?", (since, ip)).fetchone()[0]
        by_account = conn.execute("SELECT COUNT(*) FROM login_failures WHERE ts>? AND username=?", (since, username)).fetchone()[0]
    finally:
        conn.close()
    return pair >= limits["pair"] or by_ip >= limits["ip"] or by_account >= limits["account"]


def record_failure(username, ip):
    """Compte un échec réel de vérification (les tentatives bloquées ne prolongent pas le blocage)."""
    global _last_flood_alert
    t = now()
    conn = accounts_connect()
    try:
        conn.execute("INSERT INTO login_failures (ts, username, ip) VALUES (?,?,?)", (t, username, ip))
        conn.commit()
        recent = conn.execute("SELECT COUNT(*) FROM login_failures WHERE ts>?", (t - 300,)).fetchone()[0]
    finally:
        conn.close()
    if recent >= FLOOD_THRESHOLD and t - _last_flood_alert > 300:
        _last_flood_alert = t
        log_event("login_flood_alert", "alert", reason=f"{recent} failures in 5 minutes")


def clear_pair(username, ip):
    """Remise à zéro du couple (compte, IP) après une connexion réussie."""
    conn = accounts_connect()
    try:
        conn.execute("DELETE FROM login_failures WHERE username=? AND ip=?", (username, ip))
        conn.commit()
    finally:
        conn.close()
