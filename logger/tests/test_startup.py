"""Démarrage : plus aucune valeur par défaut dangereuse, secrets générés et protégés."""
import os
import stat

import pytest

from app import SetupError, create_app
from conftest import ADMIN_PW, STRONG_SECRET


def conf(tmp_path, **kw):
    base = {"APPDATA_DIR": str(tmp_path / "a"), "USERS_DIR": str(tmp_path / "u"), "SECRET_KEY": STRONG_SECRET,
            "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": ADMIN_PW}
    base.update(kw)
    return base


@pytest.mark.parametrize("weak", ["dev-change-me", "change-me-to-a-long-random-value", "short", "x" * 31,
                                   "my-secret-key-my-secret-key-my-secret-key"])
def test_weak_or_short_secret_key_refused(tmp_path, weak):
    with pytest.raises(SetupError):
        create_app(conf(tmp_path, SECRET_KEY=weak))


@pytest.mark.parametrize("pw", ["change-me", "admin", "admin1234567890", "password1234567", "a" * 40, "x"])
def test_default_or_weak_admin_password_refused(tmp_path, pw):
    with pytest.raises(SetupError):
        create_app(conf(tmp_path, ADMIN_PASSWORD=pw))


def test_no_admin_password_refuses_to_start_with_instructions(tmp_path):
    with pytest.raises(SetupError, match="init-admin"):
        create_app(conf(tmp_path, ADMIN_PASSWORD=""))


def test_secret_key_generated_persisted_and_private(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    c = conf(tmp_path); c["SECRET_KEY"] = None
    first = create_app(c)
    key_file = tmp_path / "a" / ".secret_key"
    assert len(first.config["SECRET_KEY"]) >= 64 and key_file.exists()
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    c2 = conf(tmp_path); c2["SECRET_KEY"] = None
    assert create_app(c2).config["SECRET_KEY"] == first.config["SECRET_KEY"]          # persistée, pas régénérée


def test_admin_password_only_used_when_database_is_empty(tmp_path):
    first = create_app(conf(tmp_path))
    from app.accounts import get_account_by_username
    again = create_app(conf(tmp_path, ADMIN_PASSWORD="another sturdy passphrase 77"))
    with again.app_context():
        from app import passwords
        assert passwords.verify(get_account_by_username("admin")["password_hash"], ADMIN_PW)   # inchangé au redémarrage


def test_no_fallback_credentials_exist(app):
    from app.accounts import get_account_by_username
    with app.app_context():
        account = get_account_by_username("admin")
        from app import passwords
        assert not passwords.verify(account["password_hash"], "change-me")
        assert not passwords.verify(account["password_hash"], "admin")
        assert account["password_hash"].startswith("$argon2id$")


def test_forged_cookie_with_old_default_key_is_rejected(app):
    from flask.sessions import SecureCookieSessionInterface
    old = create_app.__globals__["Flask"](__name__); old.secret_key = "dev-change-me"
    cookie = SecureCookieSessionInterface().get_signing_serializer(old).dumps({"user_id": 1, "sv": 0})
    c = app.test_client(); c.set_cookie("logger_session", cookie)
    assert c.get("/accounts", headers={"Referer": "https://localhost/"}).status_code == 302     # redirigé vers /login


def test_dev_environment_can_disable_secure_cookie_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGER_ENV", "development")
    assert create_app(conf(tmp_path)).config["SESSION_COOKIE_SECURE"] is False
    monkeypatch.setenv("LOGGER_ENV", "production")
    assert create_app(conf(tmp_path / "p")).config["SESSION_COOKIE_SECURE"] is True
