import io
import json
import re
import tempfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from app import create_app
from conftest import CsrfClient

# Identifiants de test : conformes à la politique de sécurité (l'application refuse “test” / “admin” au démarrage).
TEST_SECRET = "0f9c1e7b52d84a36b8e1c07d93a45f6e1b2c3d4e5f60718293a4b5c6d7e8f901"
ADMIN_PW = "correct horse battery staple 42"
USER_PW = "a long enough test passphrase 1"



def use_rules(app, ids):
    """Conversion rules of the 'default' import profile for the current test (the engine converts by profile):
    the catalog rules with these ids, in catalog order."""
    from app.converter import engine, profiles
    from app.converter.catalog import load_rules, normalize_rule
    with app.app_context():
        chosen = [normalize_rule(r) for r in load_rules() if r['id'] in ids]
    engine.profile_rules = lambda pid: chosen if pid == 'default' else profiles.profile_rules(pid)


def _env_without_secrets():
    """Environnement pour les sous-processus : sans SECRET_KEY/ADMIN_* hérités du poste ou de la CI."""
    import os
    return {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD")}


@pytest.fixture()
def app(tmp_path):
    app = create_app({"APPDATA_DIR": str(tmp_path / "appdata"), "USERS_DIR": str(tmp_path / "users"), "SECRET_KEY": TEST_SECRET,
                      "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": ADMIN_PW, "PREFERRED_URL_SCHEME": "https", "TESTING": True})
    app.test_client_class = CsrfClient
    return app


@pytest.fixture()
def client(app): return app.test_client()


def login(client, username="admin", password=ADMIN_PW):
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
    assert client.get('/data').status_code == 200
    assert client.get('/logbook').status_code == 200
    assert 'Raw data' in client.get('/data').get_data(as_text=True)
    assert 'Logbook' in client.get('/logbook').get_data(as_text=True)


def test_import_and_refresh_logbook(client, app):
    login(client)
    r = client.post('/import', data={'profile': 'aircanada', 'files': [(excel(['year', 'month', 'day', 'reg', 'dep', 'arr'], [2026, 9, 27, 'C-AAA', 'YUL', 'YYZ']), 'flight.xlsx')]}, content_type='multipart/form-data')
    assert r.status_code == 302
    r = client.post('/logbook/refresh', follow_redirects=True); assert r.status_code == 200
    with app.app_context():
        from app.converter import list_logbook_rows
        rows = list_logbook_rows(username="admin")
    row = rows[0]
    assert row['date'] == '2026-09-27'; assert row['registration'] == 'C-AAA'
    assert row['departure'] == 'CYUL' and row['arrival'] == 'CYYZ'      # IATA -> ICAO (rules departure_icao / arrival_icao of the aircanada conversion profile)


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
    r = client.post('/logbook/settings/save', data={'rows_per_page': '30', 'row_height_u': '20', 'font_family': 'Arial', 'font_size': '10', 'header_font_size': '9', 'width_date': '7'}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.config import load_logbook_layout, load_logbook_db_config, load_config
        layout = load_logbook_layout(username="admin")
        db = load_logbook_db_config(username="admin")
        user = load_config(username="admin")
    assert layout['rows_per_page'] == 30 and layout['row_height_u'] == 20
    assert 'columns' in db['database']
    assert 'columns' in user['database']


def test_non_admin_cannot_manage_accounts(client, app):
    with app.app_context():
        from app.accounts import create_account
        create_account("pilot1", USER_PW, role="user")
    login(client, "pilot1", USER_PW)
    r = client.get('/accounts', follow_redirects=True)
    assert 'New account' not in r.get_data(as_text=True)


def test_admin_can_create_account_and_data_is_isolated(client, app):
    login(client)
    r = client.post('/accounts/new', data={'username': 'pilot2', 'password': USER_PW, 'role': 'user'}, follow_redirects=True)
    assert r.status_code == 200
    client.post('/logout')
    login(client, 'pilot2', USER_PW)
    r = client.get('/', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        user_dir = Path(app.config["USERS_DIR"]) / "pilot2"
        assert (user_dir / "pilot2_data.db").exists()


# ---------------- convertisseur ----------------

def _aircraft_type(app, code, engines):
    """Crée un type d'appareil de test. Le filtre moteur des règles jour/nuit lit le type (colonne “type”), plus l'immatriculation."""
    with app.app_context():
        from app.refdata import save_aircraft_type
        save_aircraft_type(None, {"code": code, "category": "airplane", "engines": engines})


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
        pass
    _aircraft_type(app, 'TST1', 'single')
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC', type='TST1', arr='YUL', block='01:23:00', fcv_on_millis_utc=1728680385000)
    use_rules(client.application, ['date_from_parts', 'registration_format', 'daynight_single_pic'])
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
    import html
    login(client)
    _aircraft_type(app, 'TST1', 'single')
    _import_flight(client, year=2024, month=10, day=11, reg='C-XXXX', type='ZZ99', arr='YUL', block='01:00:00', fcv_on_millis_utc=1728680385000)   # type inconnu
    _import_flight(client, year=2024, month=10, day=12, reg='C-XXXX', type='TST1', arr='ZZZ', block='01:00:00', fcv_on_millis_utc=1728680385000)   # aéroport inconnu
    use_rules(client.application, ['daynight_single_pic'])
    page = html.unescape(client.post('/logbook/refresh', follow_redirects=True).get_data(as_text=True))
    assert "Unknown aircraft type: ZZ99" in page
    assert 'Unknown airport: ZZZ' in page


def test_engine_filter_skips_other_engine(client, app):
    login(client)
    with app.app_context():
        pass
    _aircraft_type(app, 'TST2', 'multi')
    _import_flight(client, year=2024, month=10, day=11, reg='C-FMUL', type='TST2', arr='YUL', block='02:00:00', fcv_on_millis_utc=1728680385000)
    use_rules(client.application, ['daynight_single_pic', 'daynight_multi_pic'])
    client.post('/logbook/refresh')
    with app.app_context():
        from app.converter import list_logbook_rows
        row = list_logbook_rows(username="admin")[0]
    assert row['single_engine_pic_day'] is None
    assert float(row['multi_engine_pic_day']) == 2.0


def test_first_rule_wins_for_same_column(client, app):
    login(client)
    _import_flight(client, year=2024, month=10, day=11, dep_datetime_local='2020-01-01 10:00:00')
    use_rules(client.application, ['date_from_parts', 'date_from_departure'])
    client.post('/logbook/refresh')
    with app.app_context():
        from app.converter import list_logbook_rows
        assert list_logbook_rows(username="admin")[0]['date'] == '2024-10-11'


def test_only_admin_edits_catalog_and_users_tick_their_own(client, app):
    with app.app_context():
        from app.accounts import create_account
        create_account("pilot3", USER_PW, role="user")
    login(client, "pilot3", USER_PW)
    assert client.get('/converter').status_code == 200
    r = client.get('/converter/rule/new', follow_redirects=True)
    assert 'New rule' not in r.get_data(as_text=True) or 'Transform type' not in r.get_data(as_text=True)
    assert client.post('/converter/rule/copy_remarks/delete').status_code == 403   # non-admin : refusé (avant la 0.2.0 : redirection 302)
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
    assert 'Rule added' in r.get_data(as_text=True)
    r = client.post('/converter/rule/bloc_decimal/edit', data={'name': 'Bloc décimal 2', 'group': 'Temps', 'in_time': 'block_time',
                    'out_target': 'remarks', 'param_rounding': 'none'}, follow_redirects=True)
    assert 'Rule updated' in r.get_data(as_text=True)
    r = client.post('/converter/rule/new', data={'save': '1', 'transform': 'copy', 'name': 'Sans sortie', 'in_source': 'year'}, follow_redirects=True)
    assert 'required' in r.get_data(as_text=True)
    client.post('/converter/rule/bloc_decimal/delete')
    from app.converter.catalog import get_rule
    with app.app_context():
        assert get_rule('bloc_decimal') is None


def test_admin_settings_and_reference_pages(client, app):
    login(client)
    r = client.post('/converter/settings', data={'after_sunset_minutes': '15', 'before_sunrise_minutes': '20', 'tc_rounding': '0-29=0.0\n30-60=0.5'}, follow_redirects=True)
    assert 'saved' in r.get_data(as_text=True)
    from app.converter.catalog import load_settings
    with app.app_context():
        st = load_settings()
    assert st['night'] == {'after_sunset_minutes': 15, 'before_sunrise_minutes': 20}
    r = client.post('/converter/settings', data={'after_sunset_minutes': '15', 'before_sunrise_minutes': '20', 'tc_rounding': '0-10=0.0'}, follow_redirects=True)
    assert 'not saved' in r.get_data(as_text=True)
    for url in ('/converter/airports', '/converter/aircrafts', '/converter/airports/new', '/converter/aircrafts/new', '/converter/rule/new'):
        assert client.get(url).status_code == 200
    r = client.post('/converter/aircrafts/new', data={'code': 'zz99', 'category': 'airplane', 'engines': 'single'}, follow_redirects=True)
    assert 'ZZ99' in r.get_data(as_text=True)          # la page liste désormais des TYPES d'appareils (code en majuscules)


def test_new_account_gets_default_rules_selected(client, app):
    login(client)
    client.post('/accounts/new', data={'username': 'pilot4', 'password': USER_PW, 'role': 'user'})
    with app.app_context():
        from app.converter.catalog import load_selection
        sel = load_selection(username="pilot4")
    assert 'date_from_parts' in sel and 'registration_format' in sel
    assert 'daynight_single_pic' not in sel


def test_concurrent_startup_is_safe(tmp_path):
    """gunicorn boots several workers at once on a fresh install: they must not race."""
    import os, subprocess, sys
    env = {**_env_without_secrets(), "APPDATA_DIR": str(tmp_path / "appdata"), "USERS_DIR": str(tmp_path / "users"),
           "PYTHONPATH": str(Path(__file__).parent.parent), "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": ADMIN_PW}
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
    use_rules(client.application, ['date_from_parts', 'registration_format'])
    client.post('/logbook/refresh')
    r = client.get('/logbook-db/rows')
    assert r.get_json()['data'][0]['registration'] == 'C-GABC'
    r = client.get('/logbook-db/table-export.csv')
    assert r.status_code == 200 and 'C-GABC' in r.data.decode('utf-8-sig')


def test_view_yaml_generated_with_sensible_defaults(client, app):
    login(client)
    client.get('/data')      # génère <user>_data_view.yml
    client.get('/logbook-db')  # génère <user>_logbook_view.yml
    with app.app_context():
        from app.config import load_data_view, load_logbook_view, load_config
        data_view = load_data_view(load_config(username="admin"), username="admin")
        logbook_view = load_logbook_view(username="admin")
    assert data_view[0]['frozen'] is True                 # première colonne figée par défaut
    assert all(not c['frozen'] for c in data_view[1:])
    year_col = next(c for c in data_view if c['column'] == 'year')
    assert year_col['align'] == 'right'                    # colonnes numériques alignées à droite
    assert [c['column'] for c in logbook_view[:3]] == ['year', 'month', 'day']      # la date est séparée en 3 colonnes


def test_logbook_page_matches_template_structure(client, app):
    """Les colonnes spacer existent vraiment dans le modèle Excel (gap visuel entre
    SINGLE-ENGINE et MULTI-ENGINE) ; seule la colonne "total" (sans équivalent dans
    le modèle) est retirée. Remarks est une colonne unique et large (fusion J:K)."""
    login(client)
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC')
    use_rules(client.application, ['date_from_parts', 'registration_format'])
    client.post('/logbook/refresh')
    r = client.get('/logbook')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '"key": "spacer1"' in body and '"key": "spacer2"' in body
    assert '"key": "total"' not in body and '"key": "remarks_cont"' not in body
    with app.app_context():
        from app.config import load_logbook_layout
        cols = load_logbook_layout(username="admin")["columns"]
    remarks = next(c for c in cols if c["key"] == "remarks")
    assert remarks["width"] == 210
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
    use_rules(client.application, ['date_from_parts', 'registration_format', 'daynight_single_pic'])
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    assert "pagination: true" not in body and "pagination:true" not in body
    year_pages = json.loads(re.search(r'const yearPages = (\{.*?\});', body).group(1))
    pages = year_pages["2024"]
    assert [len(p) for p in pages] == [30, 15]


def test_logbook_page_totals_forwarded_and_to_date(client, app):
    login(client)
    with app.app_context():
        pass
    _aircraft_type(app, 'TST1', 'single')
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'reg', 'type', 'arr', 'block', 'fcv_on_millis_utc'])
    for i in range(35):
        ws.append([2024, 1, (i % 28) + 1, 'C-GABC', 'TST1', 'YUL', '00:20:00', 1728680385000])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'registration_format', 'daynight_single_pic'])
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    summaries = json.loads(re.search(r'const yearSummaries = (\{.*?\});', body).group(1))["2024"]
    page0 = {r['_kind']: r['se_pic_day'] for r in summaries[0]}
    page1 = {r['_kind']: r['se_pic_day'] for r in summaries[1]}
    assert page0 == {'page_total': 9.0, 'forwarded': 0.0, 'to_date': 9.0}
    assert page1 == {'page_total': 1.5, 'forwarded': 9.0, 'to_date': 10.5}
    assert "toFixed(1)" in body


def test_logbook_summary_rows_not_editable(client, app):
    login(client)
    assert "cell.getRow().getData()._kind" in client.get('/logbook').get_data(as_text=True)


# ---------------- tableau Logbook (HTML fusionné, v3) ----------------

def _logbook_html_rows(body):
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(s):
            super().__init__(); s.rows = []; s.cur = None; s.cell = None
        def handle_starttag(s, t, a):
            a = dict(a)
            if t == 'tr': s.cur = {'cls': a.get('class', ''), 'cells': []}
            if t in ('td', 'th') and s.cur is not None:
                s.cell = {'span': int(a.get('colspan', 1)), 'ce': a.get('contenteditable'), 'txt': '', 'cls': a.get('class', '')}
        def handle_data(s, d):
            if s.cell is not None: s.cell['txt'] += d
        def handle_endtag(s, t):
            if t in ('td', 'th') and s.cell is not None: s.cur['cells'].append(s.cell); s.cell = None
            if t == 'tr' and s.cur is not None: s.rows.append(s.cur); s.cur = None
    p = P(); p.feed(body)
    return [r for r in p.rows if r['cells']]


def test_logbook_table_is_30_rows_one_decimal_and_editable(client, app):
    login(client)
    wb = Workbook(); ws = wb.active
    ws.append(['year', 'month', 'day', 'type', 'reg', 'pic', 'se pic day', 'se dual day'])
    ws.append([2014, 3, 6, 'RH44', 'C-FARY', 'V.Fuzeau', 1, 1.25])
    ws.append([2014, 3, 10, 'RH44', 'C-FARY', 'V.Fuzeau', 0.2, None])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_aircraft_type', 'registration_format',
                'copy_pilot_in_command', 'copy_single_engine_pic_day', 'copy_single_engine_dual_day'])
    client.post('/logbook/refresh')
    rows = _logbook_html_rows(client.get('/logbook').get_data(as_text=True))
    data = [r for r in rows if 'data-row' in r['cls']]
    assert len(data) == 30                                           # 2 vols + 28 lignes vides, comme le modèle
    first = data[0]['cells']
    assert first[9]['txt'].strip() == '1,3' and first[10]['txt'].strip() == '1,0'   # jamais "1" ni "1.25" : virgule décimale
    assert [c['ce'] for c in first[2:9]] == ['true'] * 7             # texte réellement éditable
    assert first[0]['ce'] is None                                    # le mois (dérivé de la date) ne l'est pas
    assert all(sum(c['span'] for c in r['cells']) == 34 for r in data)
    footer = next(r for r in rows if 'footer-row' in r['cls'])
    assert sum(c['span'] for c in footer['cells']) == 34
    assert all(c['ce'] is None and c['txt'].strip() == '' for c in data[29]['cells'])   # lignes vides inertes


def test_hours1_filter_always_one_decimal(app):
    from app.main import _hours1
    assert [_hours1(v) for v in (1, '1', 1.25, '6.38', '6,44', 0, '0.2', '', None)] == \
           ['1,0', '1,0', '1,3', '6,4', '6,4', '0,0', '0,2', '', '']
    assert [_hours1(v) for v in ('1234.5', 12345.67, '1 234,5', 999.95, 1000000)] == \
           ['1\u00a0234,5', '12\u00a0345,7', '1\u00a0234,5', '1\u00a0000,0', '1\u00a0000\u00a0000,0']
    assert _hours1('abc') == 'abc'


def test_grand_total_is_totals_to_date_single_plus_multi_engine_only(client, app):
    """GRAND TOTAL = SUM de "Totals to date" sur monomoteur + multimoteur (=SUM(L38:W38) du modèle).
    Les heures aux instruments (et vol sur campagne, atterrissages, instruction) ne comptent pas."""
    login(client)
    wb = Workbook(); ws = wb.active
    ws.append(['year', 'month', 'day', 'se pic day', 'me pic day', 'ifr', 'cc pic day', 'ldg day'])
    for i in range(30):                                     # page 1 : 30 vols x 1.0 h monomoteur
        ws.append([2024, 1, (i % 28) + 1, 1, None, None, None, None])
    ws.append([2024, 2, 1, None, 2, 5, 4, 3])               # page 2 : 2.0 h multi + 5 IFR + 4 campagne + 3 atterrissages
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day',
                'copy_multi_engine_pic_day', 'copy_ifr', 'copy_cross_country_pic_day', 'copy_landings_day'])
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    cells = re.findall(r'class="grand-total"[^>]*>([^<]*)<', body)
    assert cells == ['GRAND TOTAL', '30,0', 'GRAND TOTAL', '32,0']      # 30.0 puis 30.0 + 2.0 ; les 5 h IFR ne comptent pas
    rows = _logbook_html_rows(body)
    last = [r for r in rows if 'total-last' in r['cls']]
    assert len(last) == 2                                   # une ligne Signature/Date/GRAND TOTAL par page
    assert all(sum(c['span'] for c in r['cells']) == 34 for r in last)


def test_totals_forwarded_carry_over_from_year_to_year(client, app):
    login(client)
    wb = Workbook(); ws = wb.active
    ws.append(['year', 'month', 'day', 'se pic day', 'ifr'])
    for y, n in ((2015, 3), (2016, 0), (2017, 2)):          # pas de vol en 2016 : le cumul saute simplement l'année
        for i in range(n): ws.append([y, 1, i + 1, 1, 7])
    ws.append([2014, 5, 5, 2.5, None])                       # inséré après : l'ordre du fichier ne doit pas compter
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day', 'copy_ifr'])
    client.post('/logbook/refresh')
    def page(year): return client.get(f'/logbook?year={year}').get_data(as_text=True)
    def pick(year, key):
        sums = json.loads(re.search(r'const yearSummaries = (\{.*?\});', page(year)).group(1))
        return {r['_kind']: r[key] for r in sums[year][0]}
    assert pick('2014', 'se_pic_day') == {'page_total': 2.5, 'forwarded': 0.0, 'to_date': 2.5}
    assert pick('2015', 'se_pic_day') == {'page_total': 3.0, 'forwarded': 2.5, 'to_date': 5.5}
    assert pick('2017', 'se_pic_day') == {'page_total': 2.0, 'forwarded': 5.5, 'to_date': 7.5}
    assert pick('2017', 'ifr') == {'page_total': 14.0, 'forwarded': 21.0, 'to_date': 35.0}      # les colonnes IFR se cumulent aussi
    # GRAND TOTAL (monomoteur + multimoteur) : cumul de toute la carrière, sans les 35 h d'IFR ; onglets de l'année la plus basse à la plus récente
    grand = lambda year: re.findall(r'class="grand-total"[^>]*>([^<]*)<', page(year))
    assert (grand('2014'), grand('2015'), grand('2017')) == (['GRAND TOTAL', '2,5'], ['GRAND TOTAL', '5,5'], ['GRAND TOTAL', '7,5'])


def _logbook_with_years(client, years):
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    for y in years: ws.append([y, 1, 1, 1])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day'])
    client.post('/logbook/refresh')
    return client.get('/logbook').get_data(as_text=True)


def test_year_tabs_ascending_with_most_recent_active_and_no_big_title(client, app):
    login(client)
    body = _logbook_with_years(client, [2017, 2014, 2015])
    assert re.findall(r'<a class="year-tab[^"]*" data-year="(\d+)"', body) == ['2014', '2015', '2017']        # plus basse à gauche
    assert re.search(r'class="year-tab active" data-year="2017"', body)                                       # la plus récente est affichée
    assert 'data-year-panel="2017"' in body and 'data-year-panel="2014"' not in body                           # une seule année rendue (page légère)
    assert 'href="/logbook?year=2014"' in body
    other = client.get('/logbook?year=2014').get_data(as_text=True)
    assert 'data-year-panel="2014"' in other and 'data-year-panel="2017"' not in other
    assert re.search(r'class="year-tab active" data-year="2014"', other)
    assert '<h2>Logbook</h2>' not in body                                                                     # gros titre retiré
    assert 'Settings' not in body                                                                             # bouton Settings retiré


def test_header_has_logbook_button_and_links_moved_to_account_page(client, app):
    login(client)
    header = re.search(r'<header>.*?</header>', client.get('/data').get_data(as_text=True), re.S).group(0)
    assert header.index('v' + app.config['APP_VERSION']) < header.index('class="header-btn"') < header.index('<nav>')        # bouton juste à droite de la version
    assert header.count('>Logbook<') == 1
    for gone in ('Raw data', 'Convertisseur', 'Work data'):
        assert gone not in header                                                                  # retirés de la barre du haut
    assert 'Logout' in header and 'admin' in header
    for entry in ('Logbook', 'Breakdown', 'Data', 'Export', 'Audit'):
        assert f'>{entry}<' in header                                                              # en-tête : 5 entrées seulement
    data = client.get('/hub/data').get_data(as_text=True)
    for link in ('>Import data<', '>Raw data<', '>Converter<', '>Work data<'):
        assert link in data                                                                        # ...the data actions are all on the Data page
    account = client.get('/accounts/me').get_data(as_text=True)
    for link in ('>Logbook settings<', '>Breakdown settings<', '>Configuration (YAML)<'):
        assert link in account                                                                     # ...et tous les réglages dans Mon compte


def test_sans_date_tab_goes_left_and_never_active_when_dated_years_exist(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    ws.append([2015, 1, 1, 1]); ws.append([None, None, None, 1])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day'])
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    assert re.findall(r'<a class="year-tab[^"]*" data-year="([^"]+)"', body) == ['No date', '2015']
    assert re.search(r'class="year-tab active" data-year="2015"', body)


# ---------------- accueil, numéros de page, dates, e-mail, espace entre les deux pages ----------------

def test_home_opens_logbook_on_current_year_else_most_recent(client, app):
    from datetime import datetime
    assert client.get('/').status_code == 302                       # non connecté : on passe par la connexion
    login(client)
    r = client.get('/')
    assert r.status_code == 302 and r.headers['Location'].endswith('/logbook')   # l'accueil, c'est le Logbook
    _logbook_with_years(client, [2014, 2015])                         # aucun vol cette année : la plus récente
    body = client.get('/', follow_redirects=True).get_data(as_text=True)
    assert re.search(r'class="year-tab active" data-year="2015"', body)
    now = datetime.now().year
    _logbook_with_years(client, [2014, now])                          # un vol cette année : c'est elle qui s'ouvre
    body = client.get('/', follow_redirects=True).get_data(as_text=True)
    assert re.search(rf'class="year-tab active" data-year="{now}"', body)
    assert client.post('/login', data={'username': 'admin', 'password': ADMIN_PW}).headers['Location'].endswith('/')   # après connexion -> accueil
    assert client.get('/data').status_code == 200                      # Données brutes, ailleurs


def test_page_numbers_start_at_2_and_3_and_follow_across_years(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    for i in range(31): ws.append([2014, 1, (i % 28) + 1, 1])         # 2014 : 2 feuilles (30 + 1)
    ws.append([2015, 1, 1, 1])                                         # 2015 : la feuille suivante
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day'])
    client.post('/logbook/refresh')
    pages = lambda year: re.findall(r'Page: (\d+)<', client.get(f'/logbook?year={year}').get_data(as_text=True))
    assert pages('2014') == ['2', '3', '4', '5']                       # comme C39=2 et S39=C39+1 du modèle, puis +2 par feuille
    assert pages('2015') == ['6', '7']


def test_month_and_day_always_two_digits_and_dates_in_words(client, app):
    login(client)
    _logbook_with_years(client, [2014])
    body = client.get('/logbook?year=2014').get_data(as_text=True)
    first = [r for r in _logbook_html_rows(body) if 'data-row' in r['cls']][0]['cells']
    assert first[0]['txt'].strip() == '01' and first[1]['txt'].strip() == '01'
    assert 'Period from: January 1, 2014 to: January 1, 2014' in body
    from app.main import _two
    assert [_two(v) for v in (5, '5', 12, '', None)] == ['05', '05', '12', '', '']


def test_two_empty_borderless_columns_between_single_and_multi_engine(client, app):
    """Comme P et Q dans le modèle Excel : deux vraies colonnes vides, sans bordures, entre SINGLE et MULTI-ENGINE."""
    login(client)
    body = _logbook_with_years(client, [2014])
    assert body.count('<col style=') == 34                                  # 32 colonnes + 2 colonnes vides
    widths = re.findall(r'<col style="width:([\d.]+)px">', body)
    assert widths[14:16] == ['4.80', '4.80']                                # 2 colonnes spacer de 5 u x 0,96 px
    rows = _logbook_html_rows(body)
    for r in [r for r in rows if 'data-row' in r['cls']]:
        cells = r['cells']
        assert [c['cls'] for c in cells[13:15]] == ['gap', 'gap']            # juste après la 4e colonne monomoteur
        assert all(c['txt'].strip() == '' and c['ce'] is None for c in cells[13:15])
        assert sum(c['span'] for c in cells) == 34
    assert body.count('<th rowspan="3" class="gap"></th>') == 2             # en-tête : les deux colonnes couvrent les 3 lignes
    assert '.logbook-table .gap{border:0!important' in body                 # sans aucune bordure
    assert 'page-gap' not in body                                           # l'ancienne bordure blanche a disparu


def test_email_setting_is_validated_saved_and_printed_in_both_footers(client, app):
    login(client)
    r = client.post('/accounts/me', data={'action': 'email', 'email': 'pas un mail'}, follow_redirects=True)
    assert 'Invalid email address' in r.get_data(as_text=True)
    r = client.post('/accounts/me', data={'action': 'email', 'email': 'pilote@example.com'}, follow_redirects=True)
    assert 'Email address saved' in r.get_data(as_text=True)
    assert 'value="pilote@example.com"' in client.get('/accounts/me').get_data(as_text=True)
    body = _logbook_with_years(client, [2014])
    assert body.count('class="email">pilote@example.com<') == 2        # pied de la page de gauche et de droite, comme L39 / AF39
    footer = next(r for r in _logbook_html_rows(body) if 'footer-row' in r['cls'])
    assert sum(c['span'] for c in footer['cells']) == 34
    client.post('/accounts/me', data={'action': 'email', 'email': ''})   # vider l'adresse l'efface
    assert 'pilote@example.com' not in client.get('/logbook').get_data(as_text=True)
    # le mot de passe se change toujours avec l'ancien formulaire (sans champ "action")
    r = client.post('/accounts/me', data={'current_password': ADMIN_PW, 'new_password': 'x1 is now a much longer passphrase', 'confirm_password': 'x1 is now a much longer passphrase'}, follow_redirects=True)
    assert 'Password changed' in r.get_data(as_text=True)


def test_accounts_db_without_email_column_is_migrated(tmp_path):
    import os, sqlite3, subprocess, sys
    appdata = tmp_path / "appdata"; (appdata / "db").mkdir(parents=True)
    conn = sqlite3.connect(appdata / "db" / "users.db")           # base d'avant cette version : pas de colonne email
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO accounts (username, password_hash, role) VALUES ('voxov', 'x', 'admin')"); conn.commit(); conn.close()
    env = {**_env_without_secrets(), "APPDATA_DIR": str(appdata), "USERS_DIR": str(tmp_path / "users"), "PYTHONPATH": str(Path(__file__).parent.parent)}
    subprocess.run([sys.executable, "-c", "from app import create_app; create_app()"], env=env, check=True, cwd=str(Path(__file__).parent.parent))
    cols = [r[1] for r in sqlite3.connect(appdata / "db" / "users.db").execute("PRAGMA table_info(accounts)")]
    assert "email" in cols


# ---------------- 1 234,5 · barre commune · Données converties éditables · éditeur YAML ----------------

def test_numbers_use_thousands_space_and_decimal_comma_everywhere(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    ws.append([2014, 1, 1, 1234.5])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'copy_single_engine_pic_day'])
    client.post('/logbook/refresh')
    body = client.get('/logbook?year=2014').get_data(as_text=True)
    first = [r for r in _logbook_html_rows(body) if 'data-row' in r['cls']][0]['cells']
    assert first[10]['txt'].strip() == '1\u00a0234,5'                       # cellule de vol
    assert re.findall(r'class="grand-total"[^>]*>([^<]*)<', body)[1] == '1\u00a0234,5'   # GRAND TOTAL
    assert 'parseHours' in body and 'formatHours' in body                    # même format après une modification à l'écran


def test_single_horizontal_scrollbar_drives_every_table(client, app):
    login(client)
    body = _logbook_with_years(client, [2014])
    assert body.count('id="hbar"') == 1                                      # une seule barre...
    assert '.logbook-wrap{overflow-x:auto;background:#fff;scrollbar-width:none}' in body   # ...les barres propres à chaque tableau sont masquées
    assert '.hbar{position:sticky;bottom:0' in body                          # collée en bas de la fenêtre
    assert "all.forEach(el=>el.addEventListener('scroll'" in body            # défilement synchronisé


def test_converted_data_splits_date_and_is_editable(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'reg'])
    for y, m, d, r in ((2014, 1, 5, 'C-AAA'), (2014, 3, 9, 'C-BBB'), (2015, 3, 12, 'C-CCC')): ws.append([y, m, d, r])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    use_rules(client.application, ['date_from_parts', 'registration_format'])
    client.post('/logbook/refresh')
    rows = client.get('/logbook-db/rows').get_json()['data']
    assert [(r['year'], r['month'], r['day']) for r in rows] == [('2014', '01', '05'), ('2014', '03', '09'), ('2015', '03', '12')]
    assert 'date' not in rows[0]                                             # la date est remplacée par 3 colonnes
    # filtres et tri par partie de date
    assert [r['registration'] for r in client.get('/logbook-db/rows?filter[0][field]=month&filter[0][value]=03').get_json()['data']] == ['C-BBB', 'C-CCC']
    assert [r['registration'] for r in client.get('/logbook-db/rows?filter[0][field]=year&filter[0][value]=2015').get_json()['data']] == ['C-CCC']
    assert [r['registration'] for r in client.get('/logbook-db/rows?sort[0][field]=day&sort[0][dir]=desc').get_json()['data']] == ['C-CCC', 'C-BBB', 'C-AAA']
    csv = client.get('/logbook-db/table-export.csv').data.decode('utf-8-sig').splitlines()[0].split(',')
    assert csv[:3] == ['year', 'month', 'day'] and 'date' not in csv        # l'export suit les mêmes colonnes
    # modification : une partie de date recompose la date ; une date impossible est refusée
    rid = rows[1]['id']
    assert client.post('/logbook/cell', data={'row_id': rid, 'column': 'month', 'value': '2'}).status_code == 204
    assert client.get('/logbook-db/rows?filter[0][field]=registration&filter[0][value]=BBB').get_json()['data'][0]['month'] == '02'
    r = client.post('/logbook/cell', data={'row_id': rid, 'column': 'day', 'value': '31'})
    assert r.status_code == 400 and 'Impossible date' in r.get_data(as_text=True)         # 31 février
    assert client.post('/logbook/cell', data={'row_id': rid, 'column': 'year', 'value': 'abc'}).status_code == 400
    # une colonne ordinaire s'édite aussi, et la page l'annonce (éditeur + avertissement avant Actualiser)
    assert client.post('/logbook/cell', data={'row_id': rid, 'column': 'registration', 'value': 'C-ZZZ'}).status_code == 204
    page = client.get('/logbook-db').get_data(as_text=True)
    assert 'editor: "input"' in page and 'data-confirm=' in page and 'erases the changes' in page   # confirmation via data-confirm (static/app.js), plus de confirm() inline : CSP


def test_yaml_editor_lists_files_and_rejects_unknown_ones(client, app):
    assert client.get('/config').status_code == 302                          # connexion obligatoire
    login(client)
    page = client.get('/config').get_data(as_text=True)
    for label in ('Raw data — structure', 'Raw data — display', 'Work data — structure',
                  'Work data — display', 'Logbook — layout'):
        assert label in page
    for key in ('data', 'data_view', 'logbook', 'logbook_view', 'layout'):
        assert client.get(f'/config?file={key}').status_code == 200
    assert client.get('/config?file=../../etc/passwd').status_code == 404    # aucun chemin ne vient de la requête
    assert client.get('/config?file=rules').status_code == 404
    assert 'Configuration (YAML)' in client.get('/accounts/me').get_data(as_text=True)


def test_yaml_editor_validates_before_saving_and_keeps_a_backup(client, app):
    login(client)
    path = Path(app.config["USERS_DIR"]) / "admin" / "admin_data.yml"
    original = path.read_text(encoding="utf-8")
    save = lambda text, key='data', action='save': client.post('/config', data={'file': key, 'content': text, 'action': action}, follow_redirects=True).get_data(as_text=True)
    # YAML invalide : message avec la ligne, rien n'est écrit
    assert 'Invalid YAML' in save("database:\n  columns:\n  - column: x\n   bad: [")
    assert 'must start with keys' in save("- juste\n- une liste")
    assert 'non-empty list' in save("database:\n  columns: 3")
    assert 'Duplicate' in save(original + "  - column: year\n    display_name: encore year\n    data_type: text\n")
    assert 'reserved' in save(original + "  - column: id2\n    display_name: x\n    data_type: text\n  - column: import_source\n    display_name: x\n    data_type: text\n")
    assert 'data_type must be' in save(original + "  - column: nouvelle\n    display_name: n\n    data_type: pourcentage\n")
    assert path.read_text(encoding="utf-8") == original                       # aucun enregistrement refusé n'a touché le fichier
    assert not path.with_name(path.name + ".bak").exists()
    assert 'Valid file' in save(original, action='validate')
    # enregistrement valable : nouvelle colonne, sauvegarde de l'ancienne version, base mise à jour
    new = original + "  - column: extra_note\n    display_name: extra note\n    position: 99\n    group: misc\n    data_type: text\n    nullable: true\n    visible: true\n    editable: true\n    import_rules:\n    - extra\n"
    assert 'File saved' in save(new)
    assert path.read_text(encoding="utf-8") == new
    assert path.with_name(path.name + ".bak").read_text(encoding="utf-8") == original
    assert client.get('/data/rows').status_code == 200                       # la colonne existe déjà dans la base
    with app.app_context():
        from app.db import connect
        conn = connect(username="admin")
        assert 'extra_note' in {r[1] for r in conn.execute("PRAGMA table_info(users)")}   # la base a reçu la nouvelle colonne
        conn.close()
    assert client.get('/data').status_code == 200
    # restauration : l'ancienne version est chargée dans l'éditeur sans rien appliquer
    page = client.post('/config', data={'file': 'data', 'content': new, 'action': 'restore'}).get_data(as_text=True)
    assert 'Previous backup loaded' in page and 'extra_note' not in page.split('<textarea')[1].split('</textarea>')[0]
    assert path.read_text(encoding="utf-8") == new


def test_yaml_editor_checks_layout_and_view_files_and_keeps_each_user_apart(client, app):
    login(client)
    layout_path = Path(app.config["USERS_DIR"]) / "admin" / "admin_layout.yml"
    layout = layout_path.read_text(encoding="utf-8")
    post = lambda key, text, action='save': client.post('/config', data={'file': key, 'content': text, 'action': action}, follow_redirects=True).get_data(as_text=True)
    assert 'rows_per_page must be a number' in post('layout', layout + "\nrows_per_page: abc\n")
    assert 'align must be' in post('data_view', "columns:\n- column: year\n  align: haut\n")
    assert 'frozen must be' in post('logbook_view', "columns:\n- column: year\n  frozen: oui\n")
    assert 'File saved' in post('layout', layout.replace("row_height_u: 22", "row_height_u: 20"))
    assert 'row_height_u: 20' in layout_path.read_text(encoding="utf-8")
    assert _logbook_with_years(client, [2014])                               # la page Logbook s'affiche avec le fichier modifié
    # un autre compte ne voit que ses propres fichiers
    with app.app_context():
        from app.accounts import create_account
        create_account("pilot9", USER_PW, role="user")
    client.post('/logout'); login(client, 'pilot9', USER_PW)
    other = client.get('/config?file=layout').get_data(as_text=True)
    assert 'pilot9_layout.yml' in other and 'row_height_u: 20' not in other


def test_logbook_table_grid_is_rectangular_with_closed_frame(client, app):
    """Simule la grille colspan/rowspan : 34 colonnes sur chaque ligne, aucun trou ni chevauchement, cadre noir
    fermé à gauche et à droite (le cadre vient des cellules, pas du tableau, pour garder les 2 colonnes vides ouvertes)."""
    from html.parser import HTMLParser
    login(client)
    body = _logbook_with_years(client, [2014])
    table = body[body.index('<table'):body.index('</table>')]

    class P(HTMLParser):
        def __init__(s): super().__init__(); s.rows = []; s.cur = None
        def handle_starttag(s, t, a):
            a = dict(a)
            if t == 'tr': s.cur = {'cls': a.get('class', ''), 'cells': []}
            if t in ('td', 'th') and s.cur is not None:
                s.cur['cells'].append({'cs': int(a.get('colspan', 1)), 'rs': int(a.get('rowspan', 1)), 'cls': a.get('class', '')})
        def handle_endtag(s, t):
            if t == 'tr' and s.cur is not None: s.rows.append(s.cur); s.cur = None
    p = P(); p.feed(table)
    occ = {}
    for ri, row in enumerate(p.rows):
        col = 0
        for cell in row['cells']:
            while (ri, col) in occ: col += 1
            for dr in range(cell['rs']):
                for dc in range(cell['cs']):
                    assert (ri + dr, col + dc) not in occ, f"chevauchement ligne {ri} colonne {col + dc}"
                    occ[(ri + dr, col + dc)] = cell
            col += cell['cs']
    assert len(p.rows) >= 37                                                  # 3 lignes d'en-tête + 30 + 3 totaux + signature + pied de page
    for ri, row in enumerate(p.rows):
        assert all((ri, c) in occ for c in range(34)), f"trou dans la ligne {ri}"
        assert max(c for (r, c) in occ if r == ri) == 33
        if row['cls'].startswith('footer'): continue
        assert 'outer-left' in occ[(ri, 0)]['cls'] and 'outer-right' in occ[(ri, 33)]['cls'], f"cadre ouvert ligne {ri}"
        assert 'gap' in occ[(ri, 14)]['cls'] and 'gap' in occ[(ri, 15)]['cls'], f"colonnes vides absentes ligne {ri}"
