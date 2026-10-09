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


def test_logbook_page_matches_template_structure(client, app):
    """Les colonnes spacer existent vraiment dans le modèle Excel (gap visuel entre
    SINGLE-ENGINE et MULTI-ENGINE) ; seule la colonne "total" (sans équivalent dans
    le modèle) est retirée. Remarks est une colonne unique et large (fusion J:K)."""
    login(client)
    _import_flight(client, year=2024, month=10, day=11, reg='C-GABC')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration']})
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
    assert remarks["width"] == 37.11
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


def test_logbook_page_totals_forwarded_and_to_date(client, app):
    login(client)
    with app.app_context():
        from app.refdata import save_aircraft
        save_aircraft(None, {"registration": "C-GABC", "engine": "single"})
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'reg', 'arr', 'block', 'fcv_on_millis_utc'])
    for i in range(35):
        ws.append([2024, 1, (i % 28) + 1, 'C-GABC', 'YUL', '00:20:00', 1728680385000])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_registration', 'daynight_single_pic']})
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
                s.cell = {'span': int(a.get('colspan', 1)), 'ce': a.get('contenteditable'), 'txt': ''}
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
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_aircraft_type', 'copy_registration',
                'copy_pilot_in_command', 'copy_single_engine_pic_day', 'copy_single_engine_dual_day']})
    client.post('/logbook/refresh')
    rows = _logbook_html_rows(client.get('/logbook').get_data(as_text=True))
    data = [r for r in rows if 'data-row' in r['cls']]
    assert len(data) == 30                                           # 2 vols + 28 lignes vides, comme le modèle
    first = data[0]['cells']
    assert first[9]['txt'].strip() == '1.3' and first[10]['txt'].strip() == '1.0'   # jamais "1" ni "1.25"
    assert [c['ce'] for c in first[2:9]] == ['true'] * 7             # texte réellement éditable
    assert first[0]['ce'] is None                                    # le mois (dérivé de la date) ne l'est pas
    assert all(sum(c['span'] for c in r['cells']) == 32 for r in data)
    footer = next(r for r in rows if 'footer-row' in r['cls'])
    assert sum(c['span'] for c in footer['cells']) == 32
    assert all(c['ce'] is None and c['txt'].strip() == '' for c in data[29]['cells'])   # lignes vides inertes


def test_hours1_filter_always_one_decimal(app):
    from app.main import _hours1
    assert [_hours1(v) for v in (1, '1', 1.25, '6.38', '6,44', 0, '0.2', '', None)] == \
           ['1.0', '1.0', '1.3', '6.4', '6.4', '0.0', '0.2', '', '']
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
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_single_engine_pic_day',
                'copy_multi_engine_pic_day', 'copy_ifr', 'copy_cross_country_pic_day', 'copy_landings_day']})
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    cells = re.findall(r'class="grand-total"[^>]*>([^<]*)<', body)
    assert cells == ['GRAND TOTAL', '30.0', 'GRAND TOTAL', '32.0']      # 30.0 puis 30.0 + 2.0 ; les 5 h IFR ne comptent pas
    rows = _logbook_html_rows(body)
    last = [r for r in rows if 'total-last' in r['cls']]
    assert len(last) == 2                                   # une ligne Signature/Date/GRAND TOTAL par page
    assert all(sum(c['span'] for c in r['cells']) == 32 for r in last)


def test_totals_forwarded_carry_over_from_year_to_year(client, app):
    login(client)
    wb = Workbook(); ws = wb.active
    ws.append(['year', 'month', 'day', 'se pic day', 'ifr'])
    for y, n in ((2015, 3), (2016, 0), (2017, 2)):          # pas de vol en 2016 : le cumul saute simplement l'année
        for i in range(n): ws.append([y, 1, i + 1, 1, 7])
    ws.append([2014, 5, 5, 2.5, None])                       # inséré après : l'ordre du fichier ne doit pas compter
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_single_engine_pic_day', 'copy_ifr']})
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    sums = json.loads(re.search(r'const yearSummaries = (\{.*?\});', body).group(1))
    def pick(year, key): return {r['_kind']: r[key] for r in sums[year][0]}
    assert pick('2014', 'se_pic_day') == {'page_total': 2.5, 'forwarded': 0.0, 'to_date': 2.5}
    assert pick('2015', 'se_pic_day') == {'page_total': 3.0, 'forwarded': 2.5, 'to_date': 5.5}
    assert pick('2017', 'se_pic_day') == {'page_total': 2.0, 'forwarded': 5.5, 'to_date': 7.5}
    assert pick('2017', 'ifr') == {'page_total': 14.0, 'forwarded': 21.0, 'to_date': 35.0}      # les colonnes IFR se cumulent aussi
    # GRAND TOTAL (monomoteur + multimoteur) : cumul de toute la carrière, sans les 35 h d'IFR ; onglets de l'année la plus basse à la plus récente
    assert re.findall(r'class="grand-total"[^>]*>([^<]*)<', body) == ['GRAND TOTAL', '2.5', 'GRAND TOTAL', '5.5', 'GRAND TOTAL', '7.5']


def _logbook_with_years(client, years):
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    for y in years: ws.append([y, 1, 1, 1])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_single_engine_pic_day']})
    client.post('/logbook/refresh')
    return client.get('/logbook').get_data(as_text=True)


def test_year_tabs_ascending_with_most_recent_active_and_no_big_title(client, app):
    login(client)
    body = _logbook_with_years(client, [2017, 2014, 2015])
    assert re.findall(r'<button class="year-tab[^"]*" data-year="(\d+)"', body) == ['2014', '2015', '2017']   # plus basse à gauche
    assert re.search(r'class="year-tab active" data-year="2017"', body)                                       # la plus récente est affichée
    assert 'class="year-panel" data-year-panel="2017"' in body and 'year-panel hidden" data-year-panel="2014"' in body
    assert '<h2>Logbook</h2>' not in body                                                                     # gros titre retiré
    assert 'Settings</a></div>' in body and body.index('year-tab') < body.index('Settings</a>')               # Settings sur la ligne des onglets


def test_header_has_logbook_button_and_links_moved_to_account_page(client, app):
    login(client)
    header = re.search(r'<header>.*?</header>', client.get('/').get_data(as_text=True), re.S).group(0)
    assert header.index('v1.') < header.index('class="header-btn"') < header.index('<nav>')        # bouton juste à droite de la version
    assert header.count('>Logbook<') == 1
    for gone in ('Données brutes', 'Convertisseur', 'Données converties'):
        assert gone not in header                                                                  # retirés de la barre du haut
    assert 'Logout' in header and 'admin' in header
    account = client.get('/accounts/me').get_data(as_text=True)
    for link in ('>Logbook<', '>Données brutes<', '>Convertisseur<', '>Données converties<'):
        assert link in account                                                                     # ...et présents dans Mon compte


def test_sans_date_tab_goes_left_and_never_active_when_dated_years_exist(client, app):
    login(client)
    wb = Workbook(); ws = wb.active; ws.append(['year', 'month', 'day', 'se pic day'])
    ws.append([2015, 1, 1, 1]); ws.append([None, None, None, 1])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    client.post('/import', data={'files': [(buf, 'f.xlsx')]}, content_type='multipart/form-data')
    client.post('/converter/select', data={'enabled': ['date_from_parts', 'copy_single_engine_pic_day']})
    client.post('/logbook/refresh')
    body = client.get('/logbook').get_data(as_text=True)
    assert re.findall(r'<button class="year-tab[^"]*" data-year="([^"]+)"', body) == ['Sans date', '2015']
    assert re.search(r'class="year-tab active" data-year="2015"', body)
