import os
import tempfile
from pathlib import Path
from datetime import time
import pytest
from app import create_app
from app.models import connect, load_config

@pytest.fixture()
def app():
    instance = tempfile.mkdtemp()
    app = create_app()
    app.instance_path = instance
    Path(instance).mkdir(exist_ok=True)
    app.config.update(TESTING=True, SECRET_KEY="test", ADMIN_USERNAME="admin", ADMIN_PASSWORD="admin")
    # create_app initialized its original instance; initialize again on the temporary instance
    from app.models import init_db
    with app.app_context():
        init_db(app)
    return app

@pytest.fixture()
def client(app):
    return app.test_client()

def login(client):
    return client.post('/login', data={'username':'admin','password':'admin'}, follow_redirects=True)

def test_settings_is_yaml(client, app):
    login(client)
    response = client.get('/settings')
    assert response.status_code == 200
    assert (Path(app.instance_path) / 'configuration.yml').exists()

def test_multi_file_import_and_unknown_columns(client, app):
    login(client)
    from openpyxl import Workbook
    def make(name, reg):
        wb=Workbook(); ws=wb.active; ws.title='raw'
        ws.append(['year','month','day','type','reg','truc_inconnu'])
        ws.append([2026,9,26,'R44',reg,'ignored'])
        path=Path(app.instance_path)/name
        wb.save(path); return path
    a,b=make('a.xlsx','C-AAA'),make('b.xlsx','C-BBB')
    with a.open('rb') as fa,b.open('rb') as fb:
        r=client.post('/import', data={'files':[(fa,'a.xlsx'),(fb,'b.xlsx')]}, content_type='multipart/form-data')
    assert r.status_code == 302
    with app.app_context():
        conn=connect(); rows=conn.execute('SELECT registration, year, month, day, type, import_source FROM users ORDER BY id').fetchall(); cols=[x[1] for x in conn.execute('PRAGMA table_info(users)')]
        conn.close()
    assert len(rows)==2 and {r['registration'] for r in rows}=={'C-AAA','C-BBB'}
    assert 'truc_inconnu' not in cols

def test_reimport_same_source_replaces_only_that_source(client, app):
    login(client)
    from openpyxl import Workbook
    def payload(reg):
        wb=Workbook(); ws=wb.active; ws.title='raw'; ws.append(['year','month','day','type','reg']); ws.append([2026,9,26,'R44',reg]);
        import io; bio=io.BytesIO(); wb.save(bio); bio.seek(0); return bio
    client.post('/import', data={'files':[(payload('OLD'),'same.xlsx')]}, content_type='multipart/form-data')
    client.post('/import', data={'files':[(payload('OTHER'),'other.xlsx')]}, content_type='multipart/form-data')
    client.post('/import', data={'files':[(payload('NEW'),'same.xlsx')]}, content_type='multipart/form-data')
    with app.app_context():
        conn=connect(); rows=conn.execute('SELECT registration, import_source FROM users ORDER BY id').fetchall(); conn.close()
    assert [(r['registration'],r['import_source']) for r in rows] == [('OTHER','other.xlsx'),('NEW','same.xlsx')]

def test_excel_time_value_is_sqlite_compatible():
    from datetime import time
    from app.importer import sqlite_value
    assert sqlite_value(time(8, 30, 0)) == "08:30:00"


def test_import_normalizes_punctuation_and_spaces():
    from app.importer import importable_rows
    from openpyxl import Workbook
    import io
    wb = Workbook(); ws = wb.active; ws.title = 'raw'
    ws.append(['SE-DUAL-DAY', 'some unknown'])
    ws.append([time(8, 30), 'ignored'])
    buf = io.BytesIO(); wb.save(buf)
    categories = [{'display_name':'single engine dual day','group':'time','import_rules':['se dual day'],'column':'single_engine_dual_day'}]
    rows, matched = importable_rows('test.xlsx', buf.getvalue(), categories)
    assert matched == 1
    assert rows[0]['single_engine_dual_day'] == '08:30:00'

def test_configuration_uses_single_database_columns_list(client, app):
    login(client)
    with app.app_context():
        config = load_config()
    columns = config['database']['columns']
    assert {c['column'] for c in columns if c['group'] == 'system'} == {'id', 'created_at', 'updated_at', 'import_source'}
    assert all(set(['column','display_name','position','group','data_type','nullable','visible','editable','import_rules']).issubset(c) for c in columns if c['group'] != 'system')
    text = (Path(app.instance_path) / 'configuration.yml').read_text()
    assert 'database:' in text and 'columns:' in text
    assert 'categories:' not in text


def test_system_columns_exist_and_are_hidden_from_main_table(client, app):
    login(client)
    with app.app_context():
        conn = connect()
        cols = [r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        conn.close()
    assert {'id', 'created_at', 'updated_at', 'import_source'}.issubset(cols)
    response = client.get('/')
    body = response.get_data(as_text=True)
    assert '<th>ID</th>' not in body
    assert 'Created at' not in body
    assert 'Updated at' not in body
    assert 'Import source' not in body


def test_deleting_configured_column_drops_database_column(client, app):
    login(client)
    with app.app_context():
        conn = connect()
        assert 'year' in [r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        conn.close()
    response = client.post('/settings/category/1/delete', follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        conn = connect()
        cols = [r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        config = load_config()
        conn.close()
    assert 'year' not in cols
    assert 'year' not in {c['column'] for c in config['database']['columns']}
    assert {'id', 'created_at', 'updated_at', 'import_source'}.issubset(cols)


def test_logbook_is_created_and_date_is_built_from_user_date(client, app):
    login(client)
    from openpyxl import Workbook
    import io
    wb=Workbook(); ws=wb.active; ws.title='raw'
    ws.append(['year','month','day','reg'])
    ws.append([2026,9,27,'C-AAA'])
    bio=io.BytesIO(); wb.save(bio); bio.seek(0)
    response=client.post('/import', data={'files':[(bio,'logbook-source.xlsx')]}, content_type='multipart/form-data')
    assert response.status_code == 302
    response=client.post('/logbook/refresh', follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        from app.models import logbook_connect, load_config
        conn=logbook_connect()
        row=conn.execute('SELECT date FROM logbook ORDER BY id').fetchone()
        cols=[r[1] for r in conn.execute('PRAGMA table_info(logbook)').fetchall()]
        conn.close()
        config=load_config()
    assert 'date' in cols
    assert row['date'] == '2026-09-27'
    assert config['logbook']['columns'][4]['column'] == 'date'
    assert config['logbook']['columns'][4]['source'] == ['users.year','users.month','users.day']
    assert config['logbook']['columns'][4]['transformation'] == 'date'
