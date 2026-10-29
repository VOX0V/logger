"""CSRF sur toutes les mutations, protection explicite de chaque route, droits administrateur, isolation des données."""
import re
from pathlib import Path

import pytest

from conftest import ADMIN_PW, USER_PW, Web, events

REF = {"Referer": "https://localhost/"}
PUBLIC = {"auth.login", "auth.logout", "static", "healthz"}
TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def sample_url(rule):
    args = {a: (1 if "int" in type(rule._converters[a]).__name__.lower() else "x") for a in rule.arguments}
    from flask import url_for
    return url_for(rule.endpoint, **args, _external=False)


def rules(app, method):
    return [r for r in app.url_map.iter_rules() if method in r.methods and r.endpoint != "static"]


def test_every_post_route_rejects_a_missing_csrf_token(app, admin):
    checked = 0
    with app.test_request_context():
        urls = [(r.endpoint, sample_url(r)) for r in rules(app, "POST")]
    for endpoint, url in urls:
        r = admin.c.post(url, data={}, headers=REF)
        assert r.status_code == 400, f"{endpoint} ({url}) accepte une mutation sans jeton CSRF : {r.status_code}"
        checked += 1
    assert checked >= 25
    assert len(events(app, "csrf_failure")) == checked


def test_csrf_token_from_another_session_is_rejected(app, admin):
    stranger = Web(app).token()
    r = admin.c.post("/accounts/me", data={"action": "email", "email": "a@b.co", "csrf_token": stranger}, headers=REF)
    assert r.status_code == 400


def test_valid_token_is_accepted(admin):
    assert admin.post("/accounts/me", {"action": "email", "email": "a@b.co"}).status_code == 302


def test_login_form_is_csrf_protected(app):
    assert Web(app).post("/login", {"username": "admin", "password": ADMIN_PW}, csrf=False).status_code == 400


def test_cross_origin_referer_is_rejected_over_https(admin):
    r = admin.post("/accounts/me", {"action": "email", "email": "a@b.co"}, headers={"Referer": "https://evil.example/"})
    assert r.status_code == 400


def test_get_requests_never_mutate(admin):
    assert admin.get("/logout").status_code == 405
    for route in ("/data/clear", "/logbook/refresh", "/accounts/1/delete"):
        assert admin.get(route).status_code == 405


def test_templates_have_csrf_everywhere():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text()
        for m in re.finditer(r'<form\b[^>]*\bmethod=["\']?post["\']?[^>]*>(.{0,80})', text, re.I | re.S):
            assert "csrf_token" in m.group(1), f"{path.name} : formulaire POST sans jeton CSRF"
    assert text and "X-CSRFToken" in (TEMPLATES / "logbook.html").read_text() and "X-CSRFToken" in (TEMPLATES / "logbook_db.html").read_text()


# ------------------------- autorisations -------------------------

def test_every_route_is_explicitly_protected(app):
    unprotected = [r.endpoint for r in app.url_map.iter_rules()
                   if r.endpoint not in PUBLIC and not getattr(app.view_functions[r.endpoint], "requires_login", False)]
    assert unprotected == [], f"routes sans login_required/admin_required : {unprotected}"


def test_anonymous_gets_redirected_everywhere(app):
    w = Web(app)
    with app.test_request_context():
        urls = [(r.endpoint, sample_url(r)) for r in rules(app, "GET") if r.endpoint not in PUBLIC]
    for endpoint, url in urls:
        r = w.get(url)
        assert r.status_code == 302 and "/login" in r.headers["Location"], f"{endpoint} accessible sans connexion"


def test_admin_routes_return_403_for_normal_users(app, make_user):
    alice = make_user("alice")
    admin_endpoints = [r for r in app.url_map.iter_rules() if getattr(app.view_functions[r.endpoint], "requires_admin", False)]
    assert len(admin_endpoints) >= 10
    with app.test_request_context():
        targets = [(r, sample_url(r)) for r in admin_endpoints]
    for rule, url in targets:
        for method in sorted(rule.methods & {"GET", "POST"}):
            r = alice.get(url) if method == "GET" else alice.post(url, {})
            assert r.status_code == 403, f"{rule.endpoint} {method} accessible à un utilisateur normal ({r.status_code})"
    assert events(app, "access_denied")


def test_normal_user_cannot_create_accounts_or_read_security_log(make_user):
    alice = make_user("alice")
    assert alice.post("/accounts/new", {"username": "mallory", "password": "mallory sneaky passphrase 1", "role": "admin"}).status_code == 403
    assert alice.get("/security").status_code == 403


def test_last_active_admin_is_protected(app):
    from app.accounts import create_account, delete_account, get_account_by_username, set_active, set_role
    with app.app_context():
        root = get_account_by_username("admin")
        for action in (lambda: set_role(root["id"], "user"), lambda: set_active(root["id"], False), lambda: delete_account(root["id"])):
            with pytest.raises(ValueError):
                action()
        second = create_account("second", "the next admin passphrase 123", "admin")
        set_active(second["id"], False)                          # un admin inactif ne compte pas
        with pytest.raises(ValueError):
            delete_account(root["id"])
        set_active(second["id"], True)
        set_role(second["id"], "user")                           # il reste un admin actif : autorisé
        assert get_account_by_username("admin")["role"] == "admin"


def test_admin_cannot_demote_disable_or_delete_self(app, admin):
    from app.accounts import get_account_by_username
    with app.app_context():
        me = get_account_by_username("admin")["id"]
    admin.post(f"/accounts/{me}/edit", {"role": "user", "active": "1"})
    admin.post(f"/accounts/{me}/edit", {"role": "admin"})                     # tentative de s'auto-désactiver
    admin.post(f"/accounts/{me}/delete")
    with app.app_context():
        a = get_account_by_username("admin")
        assert a["role"] == "admin" and a["active"] == 1


def test_account_creation_over_http_enforces_policy(app, admin):
    admin.post("/accounts/new", {"username": "weak", "password": "short", "role": "user"})
    admin.post("/accounts/new", {"username": "bad name!", "password": "a perfectly fine passphrase 1", "role": "user"})
    admin.post("/accounts/new", {"username": "odd", "password": "a perfectly fine passphrase 1", "role": "superuser"})
    from app.accounts import get_account_by_username
    with app.app_context():
        assert not any(get_account_by_username(n) for n in ("weak", "bad name!", "odd"))


def test_yaml_editor_is_limited_to_its_fixed_file_list(admin):
    for key in ("../../appdata/.secret_key", "/etc/passwd", "..%2f..%2fetc%2fpasswd", "users.db"):
        r = admin.get("/config", query_string={"file": key})
        assert b"SECRET" not in r.data and b"root:" not in r.data


def test_export_download_token_cannot_escape_the_user_folder(admin):
    for token in ("..%2f..%2fappdata%2fdb%2fusers", "../../etc/passwd", "x/../../y"):
        r = admin.get(f"/export/download/{token}")
        assert r.status_code in (302, 404) and b"root:" not in r.data


def test_users_only_see_their_own_data(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    from app.db import users_root
    with app.app_context():
        marker = users_root() / "alice" / "private-note.txt"
        marker.write_text("alice-only")
    zipped = bob.get("/export")                                           # sauvegarde de bob : uniquement SON dossier
    assert zipped.status_code == 200 and b"alice-only" not in zipped.data and b"private-note" not in zipped.data


def test_deleted_account_data_is_archived_not_inherited(app, admin, make_user):
    make_user("dave")
    from app.accounts import get_account_by_username, create_account
    from app.db import users_root
    with app.app_context():
        (users_root() / "dave" / "secret.txt").write_text("dave-private")
        did = get_account_by_username("dave")["id"]
    assert admin.post(f"/accounts/{did}/delete").status_code == 302
    with app.app_context():
        archived = list((users_root() / ".deleted").glob("dave_*/secret.txt"))
        assert archived and archived[0].read_text() == "dave-private"        # conservé, pas effacé
        create_account("dave", "a brand new person passphrase 1")
        assert not (users_root() / "dave" / "secret.txt").exists()           # le nouveau “dave” n'hérite de rien


def test_orphan_folder_from_older_version_is_not_inherited(app):
    from app.accounts import create_account
    from app.db import users_root
    with app.app_context():
        (users_root() / "erin").mkdir(); (users_root() / "erin" / "old.txt").write_text("old")
        create_account("erin", "another new person passphrase 12")
        assert not (users_root() / "erin" / "old.txt").exists() and list((users_root() / ".deleted").glob("erin_*"))
