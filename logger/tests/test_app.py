import os
import tempfile
from pathlib import Path
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
