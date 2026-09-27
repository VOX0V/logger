import io
import tempfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from app import create_app


@pytest.fixture()
def app():
    storage = tempfile.mkdtemp()
    import os
    os.environ["STORAGE_DIR"] = storage
    os.environ["SECRET_KEY"] = "test"
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = "admin"
    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(app): return app.test_client()


def login(client, username="admin", password="admin"):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def excel(headers, values):
    wb = Workbook(); ws = wb.active; ws.title = 'raw'; ws.append(headers); ws.append(values)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b


def test_bootstrap_admin_can_login(client):
    r = login(client)
    assert r.status_code == 200
    assert 'Logout' in r.get_data(as_text=True)


def test_three_yaml_files_exist(client, app):
    login(client)
    user_dir = Path(app.config["STORAGE_DIR"]) / "users" / "admin"
    for name in ('userdb.yml', 'logbookdb.yml', 'logbook.yml'):
        assert (user_dir / name).exists()


def test_user_db_and_logbook_db_pages(client):
    login(client)
    assert client.get('/').status_code == 200
    assert client.get('/logbook').status_code == 200
    assert 'user.db' in client.get('/').get_data(as_text=True)
    assert 'Logbook' in client.get('/logbook').get_data(as_text=True)


def test_import_and_refresh_logbook(client, app):
    login(client)
    r = client.post('/import', data={'files': [(excel(['year', 'month', 'day', 'reg', 'dep', 'arr'], [2026, 9, 27, 'C-AAA', 'YUL', 'YYZ']), 'flight.xlsx')]}, content_type='multipart/form-data')
    assert r.status_code == 302
    r = client.post('/logbook/refresh', follow_redirects=True); assert r.status_code == 200
    with app.app_context():
        from app.converter import list_logbook_rows
        rows = list_logbook_rows(username="admin")
    row = rows[0]
    assert row['date'] == '2026-09-27'; assert row['registration'] == 'C-AAA'; assert row['departure'] == 'YUL'; assert row['arrival'] == 'YYZ'


def test_logbook_cell_edit(client, app):
    login(client)
    with app.app_context():
        from app.db import logbook_connect
        c = logbook_connect(username="admin")
        c.execute("INSERT INTO logbook (date,registration) VALUES ('2026-09-27','OLD')"); c.commit(); c.close()
    r = client.post('/logbook/cell', data={'row_id': 1, 'column': 'registration', 'value': 'NEW', 'page': 1}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.db import logbook_connect
        c = logbook_connect(username="admin")
        row = c.execute('SELECT registration FROM logbook WHERE id=1').fetchone(); c.close()
    assert row['registration'] == 'NEW'


def test_logbook_settings_are_separate(client, app):
    login(client)
    assert client.get('/logbook/settings').status_code == 200
    r = client.post('/logbook/settings/save', data={'rows_per_page': '30', 'row_height': '20', 'font_family': 'Arial', 'font_size': '10', 'header_font_size': '9', 'width_date': '7'}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.config import load_logbook_layout, load_logbook_db_config, load_config
        layout = load_logbook_layout(username="admin")
        db = load_logbook_db_config(username="admin")
        user = load_config(username="admin")
    assert layout['rows_per_page'] == 30 and layout['row_height'] == 20
    assert db['database']['name'] == 'logbook'
    assert user['database']['name'] in {'user', 'users'}


def test_non_admin_cannot_manage_accounts(client, app):
    with app.app_context():
        from app.accounts import create_account
        create_account("pilot1", "pilot1pass", role="user")
    login(client, "pilot1", "pilot1pass")
    r = client.get('/accounts', follow_redirects=True)
    assert 'Nouveau compte' not in r.get_data(as_text=True)


def test_admin_can_create_account_and_data_is_isolated(client, app):
    login(client)
    r = client.post('/accounts/new', data={'username': 'pilot2', 'password': 'pilot2pass', 'role': 'user'}, follow_redirects=True)
    assert r.status_code == 200
    client.get('/logout')
    login(client, 'pilot2', 'pilot2pass')
    r = client.get('/', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        user_dir = Path(app.config["STORAGE_DIR"]) / "users" / "pilot2"
        assert (user_dir / "user_data.db").exists()
