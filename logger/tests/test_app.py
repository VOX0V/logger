import io
import json
import re
import tempfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from app import create_app


@pytest.fixture()
def app():
    import os
    os.environ["APPDATA_DIR"] = tempfile.mkdtemp()
    os.environ["USERS_DIR"] = tempfile.mkdtemp()
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
    user_dir = Path(app.config["USERS_DIR"]) / "admin"
    for name in ('admin_data.yml', 'admin_logbook.yml', 'admin_layout.yml', 'admin_converter.yml'):
        assert (user_dir / name).exists()


def test_user_db_and_logbook_db_pages(client):
    login(client)
    assert client.get('/').status_code == 200
    assert client.get('/logbook').status_code == 200
    assert 'Données brutes' in client.get('/').get_data(as_text=True)
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
    r = client.post('/logbook/cell', data={'row_id': 1, 'column': 'registration', 'value': 'NEW'})
    assert r.status_code == 204
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
    assert 'columns' in db['database']
    assert 'columns' in user['database']


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
        user_dir = Path(app.config["USERS_DIR"]) / "pilot2"
        assert (user_dir / "pilot2_data.db").exists()


# ---------------- convertisseur ----------------

def _import_flight(client, **cols):
    headers = list(cols.keys()); values = list(cols.values())
    r = client.post('/import', data={'files': [(excel(headers, values), 'f.xlsx')]}, content_type='multipart/form-data')
    assert r.status_code == 302


def test_appdata_structure_and_reference_data(client, app):
    from app.refdata import find_airport
    root = Path(app.config["APPDATA_DIR"])
    for name in ("db/users.db", "db/airport.db", "db/aircrafts.db", "converter/rules.yml", "converter/settings.yml"):
        assert (root / name).exists(), name
    with app.app_context():
        assert find_airport("YUL")["icao_code"] == "CYUL"
        assert find_airport("cyul")["iata_code"] == "YUL"      # ICAO et minuscules acceptés
        assert find_airport("CMH4")["icao_code"] == "KCMH"     # fichier importé tel quel
        assert find_airport("ZZZ") is None


def test_day_night_computation_at_yul():
    from app.converter.transforms import is_night, parse_utc
    lat, lon = 45.4706, -73.7408
    day = parse_utc("1728680385000")                      # 2024-10-11 16:59 heure locale
    assert day.isoformat() == "2024-10-11T20:59:45"
    assert is_night(day, lat, lon, 30, 30) is False
    assert is_night(parse_utc("2024-10-12 02:00:00"), lat, lon, 30, 30) is True   # 22h locale
    assert is_night(parse_utc("2024-10-12 12:00:00"), lat, lon, 30, 30) is False  # 8h locale


def test_night_margin_after_sunset():
    from app.converter.transforms import is_night, parse_utc
    import ephem
    obs = ephem.Observer(); obs.lat, obs.lon = "45.4706", "-73.7408"; obs.date = "2024-10-11 20:00"
    sunset = obs.next_setting(ephem.Sun()).datetime()
    from datetime import timedelta
    assert is_night(sunset + timedelta(minutes=10), 45.4706, -73.7408, 30, 30) is False   # dans la marge
    assert is_night(sunset + timedelta(minutes=40), 45.4706, -73.7408, 30, 30) is True
    assert is_night(sunset + timedelta(minutes=10), 45.4706, -73.7408, 0, 30) is True     # marge à 0


def test_tc_rounding():
    from app.converter.transforms import parse_block, block_to_decimal
    from app.converter.catalog import rounding_from_text, rounding_to_text
    import yaml
    rules = yaml.safe_load(open(Path(__file__).parent.parent / "defaults" / "converter_settings.yml"))["tc_rounding"]["rules"]
    assert block_to_decimal(parse_block("01:23:00"), "tc", rules) == 1.4
    assert block_to_decimal(parse_block("1:57"), "tc", rules) == 2.0     # 57 min → +1 h
    assert block_to_decimal(parse_block("00:02"), "tc", rules) == 0.0
    assert block_to_decimal(parse_block("00:00:00"), "tc", rules) is None
    assert block_to_decimal(parse_block("1900-01-01 02:30:00"), "none", rules) == 2.5
    assert rounding_from_text(rounding_to_text(rules)) == rules


def test_refresh_with_day_night_rule(client, app):
    login(client)
    with app.app_context():
        from app.refdata import save_aircraft
        save_aircraft(None, {"registration": "C-GABC", "type": "C172", "engine": "single"})
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC', arr='YUL', block='01:23:00', fcv_on_millis_utc=1728680385000)
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration', 'daynight_single_pic']})
    r = client.post('/logbook/refresh', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.converter import list_logbook_rows
        row = list_logbook_rows(username="admin")[0]
    assert row['date'] == '2024-10-11' and row['registration'] == 'C-GABC'
    assert row['single_engine_pic_day'] == '1.4' or row['single_engine_pic_day'] == 1.4
    assert row['single_engine_pic_night'] is None
    assert row['arrival'] is None                       # règle "copie arrivée" non cochée


def test_refresh_warns_on_unknown_airport_and_aircraft(client, app):
    login(client)
    _import_flight(client, year=2024, month=10, day=11, reg='C-XXXX', arr='ZZZ', block='01:00:00', fcv_on_millis_utc=1728680385000)
    client.post('/converter/select', data={'enabled': ['daynight_single_pic']})
    r = client.post('/logbook/refresh', follow_redirects=True)
    assert 'Avion inconnu : C-XXXX' in r.get_data(as_text=True)


def test_engine_filter_skips_other_engine(client, app):
    login(client)
    with app.app_context():
        from app.refdata import save_aircraft
        save_aircraft(None, {"registration": "C-FMUL", "engine": "multi"})
    _import_flight(client, year=2024, month=10, day=11, reg='C-FMUL', arr='YUL', block='02:00:00', fcv_on_millis_utc=1728680385000)
    client.post('/converter/select', data={'enabled': ['daynight_single_pic', 'daynight_multi_pic']})
    client.post('/logbook/refresh')
    with app.app_context():
        from app.converter import list_logbook_rows
        row = list_logbook_rows(username="admin")[0]
    assert row['single_engine_pic_day'] is None
    assert float(row['multi_engine_pic_day']) == 2.0


def test_first_rule_wins_for_same_column(client, app):
    login(client)
    _import_flight(client, year=2024, month=10, day=11, dep_datetime_local='2020-01-01 10:00:00')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'date_from_departure']})
    client.post('/logbook/refresh')
    with app.app_context():
        from app.converter import list_logbook_rows
        assert list_logbook_rows(username="admin")[0]['date'] == '2024-10-11'


def test_only_admin_edits_catalog_and_users_tick_their_own(client, app):
    with app.app_context():
        from app.accounts import create_account
        create_account("pilot3", "pilot3pass", role="user")
    login(client, "pilot3", "pilot3pass")
    assert client.get('/converter').status_code == 200
    r = client.get('/converter/rule/new', follow_redirects=True)
    assert 'Nouvelle règle' not in r.get_data(as_text=True) or 'Type de transformation' not in r.get_data(as_text=True)
    assert client.post('/converter/rule/copy_remarks/delete').status_code == 302
    from app.converter.catalog import load_rules
    with app.app_context():
        assert any(r['id'] == 'copy_remarks' for r in load_rules())   # rien supprimé
    client.post('/converter/select', data={'enabled': ['copy_remarks']})
    with app.app_context():
        from app.converter.catalog import load_selection
        assert load_selection(username="pilot3") == ['copy_remarks']
        assert 'copy_remarks' in load_selection(username="admin")       # sélection de l'admin inchangée


def test_admin_creates_edits_deletes_rule(client, app):
    login(client)
    r = client.post('/converter/rule/new', data={'save': '1', 'transform': 'tc_round', 'name': 'Bloc décimal', 'group': 'Temps',
                    'in_time': 'block_time', 'out_target': 'remarks', 'param_rounding': 'tc'}, follow_redirects=True)
    assert 'Règle ajoutée' in r.get_data(as_text=True)
    r = client.post('/converter/rule/bloc_decimal/edit', data={'name': 'Bloc décimal 2', 'group': 'Temps', 'in_time': 'block_time',
                    'out_target': 'remarks', 'param_rounding': 'none'}, follow_redirects=True)
    assert 'Règle modifiée' in r.get_data(as_text=True)
    r = client.post('/converter/rule/new', data={'save': '1', 'transform': 'copy', 'name': 'Sans sortie', 'in_source': 'year'}, follow_redirects=True)
    assert 'obligatoire' in r.get_data(as_text=True)
    client.post('/converter/rule/bloc_decimal/delete')
    from app.converter.catalog import get_rule
    with app.app_context():
        assert get_rule('bloc_decimal') is None


def test_admin_settings_and_reference_pages(client, app):
    login(client)
    r = client.post('/converter/settings', data={'after_sunset_minutes': '15', 'before_sunrise_minutes': '20', 'tc_rounding': '0-29=0.0\n30-60=0.5'}, follow_redirects=True)
    assert 'enregistrés' in r.get_data(as_text=True)
    from app.converter.catalog import load_settings
    with app.app_context():
        st = load_settings()
    assert st['night'] == {'after_sunset_minutes': 15, 'before_sunrise_minutes': 20}
    r = client.post('/converter/settings', data={'after_sunset_minutes': '15', 'before_sunrise_minutes': '20', 'tc_rounding': '0-10=0.0'}, follow_redirects=True)
    assert 'non enregistrés' in r.get_data(as_text=True)
    for url in ('/converter/airports', '/converter/aircrafts', '/converter/airports/new', '/converter/aircrafts/new', '/converter/rule/new'):
        assert client.get(url).status_code == 200
    r = client.post('/converter/aircrafts/new', data={'registration': 'c-gzzz', 'engine': 'single'}, follow_redirects=True)
    assert 'C-GZZZ' in r.get_data(as_text=True)


def test_new_account_gets_default_rules_selected(client, app):
    login(client)
    client.post('/accounts/new', data={'username': 'pilot4', 'password': 'pilot4pass', 'role': 'user'})
    with app.app_context():
        from app.converter.catalog import load_selection
        sel = load_selection(username="pilot4")
    assert 'date_from_parts' in sel and 'copy_registration' in sel
    assert 'daynight_single_pic' not in sel


def test_concurrent_startup_is_safe(tmp_path):
    """gunicorn boots several workers at once on a fresh install: they must not race."""
    import os, subprocess, sys
    env = {**os.environ, "APPDATA_DIR": str(tmp_path / "appdata"), "USERS_DIR": str(tmp_path / "users"),
           "PYTHONPATH": str(Path(__file__).parent.parent), "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "admin"}
    procs = [subprocess.Popen([sys.executable, "-c", "from app import create_app; create_app()"], env=env,
                              cwd=str(Path(__file__).parent.parent), stderr=subprocess.PIPE) for _ in range(6)]
    for proc in procs:
        _, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err.decode()


# ---------------- grilles Données brutes / Données converties ----------------

def test_data_grid_pagination_sort_filter_export(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'reg', 'arr'])
    for i in range(5):
        ws.append([2024, 1, i + 1, f'C-{i:03d}', 'YUL' if i % 2 else 'CYYZ'])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    r = client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    assert r.status_code == 302
    r = client.get('/data/rows')
    d = r.get_json()
    assert d['last_page'] == 1 and len(d['data']) == 5

    r = client.get('/data/rows?size=2&page=2')
    d = r.get_json()
    assert d['last_page'] == 3
    assert [x['registration'] for x in d['data']] == ['C-002', 'C-003']

    r = client.get('/data/rows?sort[0][field]=registration&sort[0][dir]=desc')
    assert [x['registration'] for x in r.get_json()['data']] == ['C-004', 'C-003', 'C-002', 'C-001', 'C-000']

    r = client.get('/data/rows?filter[0][field]=arrival&filter[0][value]=YUL')
    assert [x['registration'] for x in r.get_json()['data']] == ['C-001', 'C-003']

    r = client.get('/data/rows?filter[0][field]=arrival&filter[0][value]=%25')   # % littéral ne doit rien matcher
    assert r.get_json()['data'] == []

    r = client.get('/data/table-export.csv')
    assert r.status_code == 200 and r.data.decode('utf-8-sig').count('\n') == 6   # en-tête + 5 lignes
    r = client.get('/data/table-export.xlsx')
    assert r.status_code == 200 and r.data[:2] == b'PK'


def test_grid_rejects_unknown_columns_without_crashing(client, app):
    login(client)
    _import_flight(client, year=2024, month=1, day=1, reg='C-001')
    r = client.get('/data/rows?sort[0][field]=registration; DROP TABLE users;--&sort[0][dir]=asc')
    assert r.status_code == 200
    assert len(client.get('/data/rows').get_json()['data']) == 1   # la table existe toujours
    r = client.get('/data/rows?filter[0][field]=id; DROP TABLE users;--&filter[0][value]=x')
    assert r.status_code == 200


def test_logbook_db_grid_matches_converted_data(client, app):
    login(client)
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration']})
    client.post('/logbook/refresh')
    r = client.get('/logbook-db/rows')
    assert r.get_json()['data'][0]['registration'] == 'C-GABC'
    r = client.get('/logbook-db/table-export.csv')
    assert r.status_code == 200 and 'C-GABC' in r.data.decode('utf-8-sig')


def test_view_yaml_generated_with_sensible_defaults(client, app):
    login(client)
    client.get('/')          # génère <user>_data_view.yml
    client.get('/logbook-db')  # génère <user>_logbook_view.yml
    with app.app_context():
        from app.config import load_data_view, load_logbook_view, load_config
        data_view = load_data_view(load_config(username="admin"), username="admin")
        logbook_view = load_logbook_view(username="admin")
    assert data_view[0]['frozen'] is True                 # première colonne figée par défaut
    assert all(not c['frozen'] for c in data_view[1:])
    year_col = next(c for c in data_view if c['column'] == 'year')
    assert year_col['align'] == 'right'                    # colonnes numériques alignées à droite
    assert logbook_view[0]['column'] == 'date'


def test_logbook_page_grid_has_no_spacer_or_total_column(client, app):
    login(client)
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration']})
    client.post('/logbook/refresh')
    r = client.get('/logbook')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '"key": "spacer1"' not in body and '"key": "total"' not in body
    assert '"registration"' in body and 'C-GABC' in body


def test_edit_logbook_cell_rejects_invalid_column(client, app):
    login(client)
    with app.app_context():
        from app.db import logbook_connect
        c = logbook_connect(username="admin")
        c.execute("INSERT INTO logbook (date) VALUES ('2026-09-27')"); c.commit(); c.close()
    r = client.post('/logbook/cell', data={'row_id': 1, 'column': 'id', 'value': '999'})
    assert r.status_code == 400


def test_logbook_page_uses_manual_pagination_not_table_wide_calc(client, app):
    """Régression : Tabulator calcule bottomCalc sur TOUTES les données, pas sur la page
    affichée — on doit donc paginer nous-mêmes et ne jamais utiliser pagination:true."""
    login(client)
    with app.app_context():
        from app.refdata import save_aircraft
        save_aircraft(None, {"registration": "C-GABC", "engine": "single"})
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'reg', 'block'])
    for i in range(45):
        ws.append([2024, 1, (i % 28) + 1, 'C-GABC', '01:00:00'])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration', 'daynight_single_pic']})
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    assert "pagination: true" not in body and "pagination:true" not in body
    year_pages = json.loads(re.search(r'const yearPages = (\{.*?\});', body).group(1))
    pages = year_pages["2024"]
    assert [len(p) for p in pages] == [30, 15]
