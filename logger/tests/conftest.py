import re
import sys
from pathlib import Path

import pytest
from flask.testing import FlaskClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402

STRONG_SECRET = "0f9c1e7b52d84a36b8e1c07d93a45f6e1b2c3d4e5f60718293a4b5c6d7e8f901"
ADMIN_PW = "correct horse battery staple 42"
USER_PW = "another sturdy passphrase 77"
REFERER = {"Referer": "https://localhost/"}


class Web:
    """Client de test qui gère le jeton CSRF et le Referer exigé par Flask-WTF en HTTPS."""

    def __init__(self, app):
        self.app, self.c = app, app.test_client()

    def get(self, url, **kw):
        kw.setdefault("headers", {}).update(REFERER)
        return self.c.get(url, **kw)

    def token(self):
        r = self.c.get("/login", headers=REFERER)
        if r.status_code in (301, 302):
            r = self.c.get("/accounts/me", headers=REFERER)
        found = re.search(r'name="csrf-token" content="([^"]+)"', r.get_data(as_text=True))
        assert found, f"pas de jeton CSRF dans la réponse ({r.status_code})"
        return found.group(1)

    def post(self, url, data=None, csrf=True, headers=None, **kw):
        data = dict(data or {})
        if csrf:
            data["csrf_token"] = self.token()
        merged = {**REFERER, **(headers or {})}
        return self.c.post(url, data=data, headers=merged, **kw)

    def login(self, username="admin", password=ADMIN_PW, **kw):
        return self.post("/login", {"username": username, "password": password}, **kw)


@pytest.fixture
def make_app(tmp_path):
    count = [0]

    def _make(**overrides):
        count[0] += 1
        base = tmp_path / f"inst{count[0]}"
        conf = dict(APPDATA_DIR=str(base / "appdata"), USERS_DIR=str(base / "users"), SECRET_KEY=STRONG_SECRET,
                    ADMIN_USERNAME="admin", ADMIN_PASSWORD=ADMIN_PW, PREFERRED_URL_SCHEME="https")
        conf.update(overrides)
        return create_app(conf)
    return _make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def web(app):
    return Web(app)


@pytest.fixture
def admin(app):
    w = Web(app)
    assert w.login().status_code == 302
    return w


@pytest.fixture
def make_user(app, admin):
    """Crée un compte (par l'API interne) et renvoie un client connecté avec ce compte."""
    def _make(username="alice", password=USER_PW, role="user", must_change=False):
        from app.accounts import create_account
        with app.app_context():
            create_account(username, password, role, must_change=must_change)
        w = Web(app)
        assert w.login(username, password).status_code == 302
        return w
    return _make


def error_text(response):
    found = re.search(r"<p>(Invalid credentials[^<]*)</p>", response.get_data(as_text=True))
    return found.group(1) if found else None


def events(app, event=None):
    from app.seclog import list_events
    with app.app_context():
        return [dict(r) for r in list_events(1000, event)]


class CsrfClient(FlaskClient):
    """Client de test Flask qui ajoute le jeton CSRF et le Referer à chaque mutation, comme le ferait un navigateur.

    Sert aux tests fonctionnels écrits avant le durcissement (test_app.py) : ils décrivent le comportement de
    l'application, pas le CSRF, qui est testé à part (test_csrf_authz.py). Passer ``no_csrf=True`` pour l'omettre."""

    def _token(self):
        response = super().open("/login", method="GET", headers=REFERER)
        if response.status_code in (301, 302):
            response = super().open("/accounts/me", method="GET", headers=REFERER)
        found = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        return found.group(1) if found else None

    def open(self, *args, **kwargs):
        skip = kwargs.pop("no_csrf", False)
        if not skip and str(kwargs.get("method", "GET")).upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.get("headers") or {})
            token = self._token()
            if token:
                headers.setdefault("X-CSRFToken", token)
            headers.setdefault("Referer", REFERER["Referer"])
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


@pytest.fixture(autouse=True)
def _restore_profile_rules():
    """Tests may replace the conversion rules of a profile (see use_rules in test_app.py): restore them afterwards."""
    from app.converter import engine
    original = engine.profile_rules
    yield
    engine.profile_rules = original
