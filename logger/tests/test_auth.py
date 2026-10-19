"""Connexion : réponses uniformes, politique de mot de passe, limitation, migration des anciens hachages."""
import logging
import sqlite3
from pathlib import Path

import pytest

from app import create_app, passwords
from conftest import ADMIN_PW, USER_PW, Web, error_text, events


def test_login_ok_and_cookie_flags(web):
    r = web.login()
    assert r.status_code == 302
    cookie = r.headers["Set-Cookie"]
    assert cookie.startswith("logger_session=") and "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_all_failures_look_identical(app, web, make_user):
    make_user("alice")
    from app.accounts import set_active
    with app.app_context():
        from app.accounts import get_account_by_username
        set_active(get_account_by_username("alice")["id"], False)
    cases = [web.login("nobody", "wrong wrong wrong wrong"), web.login("admin", "wrong wrong wrong wrong"),
             web.login("alice", USER_PW),                       # bon mot de passe mais compte désactivé
             web.login("bad name!", "x"), web.login("", "")]
    assert {r.status_code for r in cases} == {401}
    assert len({error_text(r) for r in cases}) == 1 and error_text(cases[0])


def test_unknown_account_still_costs_a_hash_verification(app, web, monkeypatch):
    calls = []
    real = passwords.burn
    monkeypatch.setattr(passwords, "burn", lambda pw="": (calls.append(1), real(pw))[1])
    web.login("ghost", "whatever whatever whatever")
    assert calls, "un compte inexistant doit dépenser le même temps qu'un compte réel"


@pytest.mark.parametrize("pw,why", [
    ("short", "trop court"), ("a" * 14, "14 caractères"), ("password12345678", "courant"), ("aaaaaaaaaaaaaaaaaaaa", "répétitif"),
    ("alice-alice-alice-xx", "contient le nom"), ("x" * 300, "trop long"), ("", "vide")])
def test_password_policy_rejects(app, pw, why):
    from app.accounts import create_account
    with app.app_context(), pytest.raises(ValueError):
        create_account("alice", pw)


def test_passphrase_with_spaces_is_kept_verbatim(app):
    from app.accounts import create_account, get_account_by_username, verify_password
    exact = "  spaced out passphrase here  "
    with app.app_context():
        create_account("spacey", exact)
        account = get_account_by_username("spacey")
        assert verify_password(account, exact) and not verify_password(account, exact.strip())


def test_pair_lockout_then_recovery_after_window(app, web, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr("app.seclog.now", lambda: clock[0])
    for _ in range(5):
        assert web.login("admin", "wrong wrong wrong wrong").status_code == 401
    blocked = web.login("admin", ADMIN_PW)                    # même le BON mot de passe est refusé pendant le blocage
    assert blocked.status_code == 401 and error_text(blocked)
    assert events(app, "login_blocked")
    clock[0] += 16 * 60                                       # la fenêtre glissante expire
    assert web.login("admin", ADMIN_PW).status_code == 302


def test_blocked_attempts_do_not_extend_the_block(app, web, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr("app.seclog.now", lambda: clock[0])
    for _ in range(5):
        web.login("admin", "wrong wrong wrong wrong")
    for _ in range(10):
        clock[0] += 60
        web.login("admin", "wrong wrong wrong wrong")         # tentatives bloquées : ne comptent pas
    clock[0] += 6 * 60
    assert web.login("admin", ADMIN_PW).status_code == 302


def test_lockout_is_per_source_not_global(app, monkeypatch):
    a, b = Web(app), Web(app)
    for _ in range(5):
        a.login("admin", "wrong wrong wrong wrong", environ_overrides={"REMOTE_ADDR": "203.0.113.5"})
    assert a.login("admin", ADMIN_PW, environ_overrides={"REMOTE_ADDR": "203.0.113.5"}).status_code == 401
    assert b.login("admin", ADMIN_PW, environ_overrides={"REMOTE_ADDR": "198.51.100.9"}).status_code == 302


def test_ip_limit_across_many_usernames(app):
    w = Web(app)
    for i in range(20):
        w.login(f"user{i}", "wrong wrong wrong wrong", environ_overrides={"REMOTE_ADDR": "203.0.113.7"})
    assert w.login("admin", ADMIN_PW, environ_overrides={"REMOTE_ADDR": "203.0.113.7"}).status_code == 401


def test_spoofed_forwarded_for_is_ignored_without_trusted_proxy(app):
    w = Web(app)
    for i in range(5):
        w.login("admin", "wrong wrong wrong wrong", headers={"X-Forwarded-For": f"10.0.0.{i}", "CF-Connecting-IP": f"10.1.0.{i}"})
    r = w.login("admin", ADMIN_PW, headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 401                               # changer l'en-tête ne contourne pas la limite
    assert {e["ip"] for e in events(app, "login_failure")} == {"127.0.0.1"}


def test_trusted_proxy_uses_only_the_hop_it_appended(make_app):
    app = make_app(TRUSTED_PROXIES=1)
    w = Web(app)
    w.login("admin", "wrong wrong wrong wrong", headers={"X-Forwarded-For": "6.6.6.6, 9.9.9.9"})   # 6.6.6.6 est forgé par le client
    assert [e["ip"] for e in events(app, "login_failure")] == ["9.9.9.9"]


def test_secrets_never_reach_logs_or_journal(app, web, caplog):
    caplog.set_level(logging.DEBUG)
    web.login("admin", "very secret wrong passphrase 1234")
    web.login("admin", ADMIN_PW)
    blob = caplog.text + str([dict(e) for e in events(app)])
    assert "very secret wrong passphrase" not in blob and ADMIN_PW not in blob and "csrf" not in blob.lower()


def test_legacy_database_is_migrated_backed_up_and_rehashed(tmp_path):
    from werkzeug.security import generate_password_hash
    appdata = tmp_path / "appdata"; (appdata / "db").mkdir(parents=True)
    legacy = sqlite3.connect(appdata / "db" / "users.db")
    legacy.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
                   "password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    legacy.execute("INSERT INTO accounts (username, password_hash, role) VALUES ('olduser', ?, 'admin')",
                   (generate_password_hash("an old but long enough passphrase"),))
    legacy.commit(); legacy.close()
    app = create_app({"APPDATA_DIR": str(appdata), "USERS_DIR": str(tmp_path / "users"), "SECRET_KEY": "k" * 5 + "0f9c1e7b52d84a36b8e1c07d93a45f6e1b2c3d4e5f6071829",
                      "PREFERRED_URL_SCHEME": "https"})
    assert list((appdata / "db").glob("users.db.pre-migration-*.bak")), "sauvegarde avant migration"
    w = Web(app)
    assert w.login("olduser", "an old but long enough passphrase").status_code == 302       # ancien hachage toujours valide
    with app.app_context():
        from app.accounts import get_account_by_username
        account = get_account_by_username("olduser")
        assert account["password_hash"].startswith("$argon2id$") and account["active"] == 1     # remplacé par Argon2id
