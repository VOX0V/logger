"""Sessions : expiration, révocation, fixation, réauthentification, changement de mot de passe obligatoire."""
import re

import pytest

from conftest import ADMIN_PW, USER_PW, Web, events

REF = {"Referer": "https://localhost/"}


def logged_out(w):
    return w.get("/accounts/me").status_code == 302


def test_logout_requires_post_and_csrf(admin):
    assert admin.get("/logout").status_code == 405
    assert admin.c.post("/logout", headers=REF).status_code == 400
    assert admin.post("/logout").status_code == 302 and logged_out(admin)


def test_old_pre_login_cookie_gives_no_access(app):
    w = Web(app)
    w.get("/login")
    pre = w.c.get_cookie("logger_session").value
    w.login()
    other = app.test_client(); other.set_cookie("logger_session", pre)
    assert other.get("/accounts/me", headers=REF).status_code == 302


def test_idle_timeout(app, admin, monkeypatch):
    import time
    base = time.time()
    monkeypatch.setattr("app.auth.time.time", lambda: base + 61 * 60)
    assert logged_out(admin)
    assert any("expirée" in (e["reason"] or "") for e in events(app, "session_invalid"))


def test_absolute_timeout_even_with_constant_activity(app, admin, monkeypatch):
    import time
    start = time.time(); clock = [start]
    monkeypatch.setattr("app.auth.time.time", lambda: clock[0])
    for _ in range(20):                                          # activité toutes les 50 min : jamais inactif
        clock[0] += 50 * 60
        if clock[0] - start > 12 * 3600:
            break
        assert admin.get("/accounts/me").status_code == 200
    assert logged_out(admin)


def test_password_change_revokes_other_sessions(app, make_user):
    a = make_user("alice"); b = Web(app); assert b.login("alice", USER_PW).status_code == 302
    r = a.post("/accounts/me", {"current_password": USER_PW, "new_password": "brand new long passphrase 9", "confirm_password": "brand new long passphrase 9"})
    assert r.status_code == 302
    assert a.get("/accounts/me").status_code == 200              # la session qui a changé le mot de passe continue
    assert logged_out(b)                                         # les autres sont révoquées immédiatement
    assert Web(app).login("alice", USER_PW).status_code == 401
    assert Web(app).login("alice", "brand new long passphrase 9").status_code == 302


def test_password_change_enforces_policy_and_current_password(make_user):
    a = make_user("alice")
    weak = a.post("/accounts/me", {"current_password": USER_PW, "new_password": "short", "confirm_password": "short"})
    assert weak.status_code == 302 and a.get("/accounts/me").status_code == 200
    assert Web(a.app).login("alice", USER_PW).status_code == 302             # inchangé
    a.post("/accounts/me", {"current_password": "not my password at all", "new_password": "brand new long passphrase 9", "confirm_password": "brand new long passphrase 9"})
    assert Web(a.app).login("alice", USER_PW).status_code == 302             # inchangé


def test_admin_deactivation_revokes_target_sessions_immediately(app, admin, make_user):
    alice = make_user("alice")
    from app.accounts import get_account_by_username
    with app.app_context():
        aid = get_account_by_username("alice")["id"]
    r = admin.post(f"/accounts/{aid}/edit", {"role": "user"})              # case « actif » absente = désactivé
    assert r.status_code == 302 and logged_out(alice)
    assert Web(app).login("alice", USER_PW).status_code == 401


def test_role_change_revokes_target_sessions(app, admin, make_user):
    alice = make_user("alice")
    from app.accounts import get_account_by_username
    with app.app_context():
        aid = get_account_by_username("alice")["id"]
    admin.post(f"/accounts/{aid}/edit", {"role": "admin", "active": "1"})
    assert logged_out(alice)


def test_revoke_my_sessions(app, make_user):
    a = make_user("alice"); b = Web(app); b.login("alice", USER_PW)
    assert a.post("/accounts/me/revoke-sessions").status_code == 302
    assert logged_out(a) and logged_out(b)


def test_admin_created_account_must_change_password_first(app, admin):
    r = admin.post("/accounts/new", {"username": "carol", "password": "temporary long passphrase 1", "role": "user"})
    assert r.status_code == 302
    carol = Web(app); carol.login("carol", "temporary long passphrase 1")
    r = carol.get("/logbook")
    assert r.status_code == 302 and "/accounts/me" in r.headers["Location"]     # tout est bloqué sauf le changement
    assert carol.get("/accounts/me").status_code == 200
    carol.post("/accounts/me", {"current_password": "temporary long passphrase 1", "new_password": "a freshly chosen passphrase 2026", "confirm_password": "a freshly chosen passphrase 2026"})
    assert carol.get("/logbook").status_code == 200


def test_sensitive_actions_require_recent_password(app, admin, make_user, monkeypatch):
    make_user("alice")
    from app.accounts import get_account_by_username
    with app.app_context():
        aid = get_account_by_username("alice")["id"]
    import time
    real = time.time; shift = [0]
    monkeypatch.setattr("app.auth.time.time", lambda: real() + shift[0])
    shift[0] = 11 * 60                                            # dernière saisie du mot de passe : il y a 11 min
    r = admin.get("/accounts/new")
    assert r.status_code == 302 and "/reauth" in r.headers["Location"]
    r = admin.post(f"/accounts/{aid}/delete")                      # destruction : refusée tant qu'on n'a pas confirmé
    assert r.status_code == 302 and "/reauth" in r.headers["Location"]
    with app.app_context():
        assert get_account_by_username("alice")
    assert admin.post("/reauth", {"password": "wrong wrong wrong wrong", "next": "/accounts/new"}).status_code == 401
    ok = admin.post("/reauth", {"password": ADMIN_PW, "next": "/accounts/new"})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/accounts/new")
    assert admin.get("/accounts/new").status_code == 200


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example", "javascript:alert(1)"])
def test_reauth_next_is_never_an_open_redirect(admin, target):
    r = admin.post("/reauth", {"password": ADMIN_PW, "next": target})
    assert r.status_code == 302 and "evil" not in r.headers["Location"] and "javascript" not in r.headers["Location"]


def test_fetch_requests_get_401_not_a_redirect(app):
    r = Web(app).get("/logbook/settings", headers={"Sec-Fetch-Mode": "cors"})
    assert r.status_code == 401
