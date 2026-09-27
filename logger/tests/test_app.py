import io
import tempfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from app import create_app
from app.models import connect, load_config, load_logbook_db_config, load_logbook_layout

@pytest.fixture()
def app():
    instance=tempfile.mkdtemp()
    app=create_app(); app.instance_path=instance
    Path(instance).mkdir(exist_ok=True)
    app.config.update(TESTING=True, SECRET_KEY="test", ADMIN_USERNAME="admin", ADMIN_PASSWORD="admin")
    from app.models import init_db
    with app.app_context(): init_db(app)
    return app

@pytest.fixture()
def client(app): return app.test_client()

def login(client): return client.post('/login',data={'username':'admin','password':'admin'},follow_redirects=True)

def excel(headers, values):
    wb=Workbook(); ws=wb.active; ws.title='raw'; ws.append(headers); ws.append(values)
    b=io.BytesIO(); wb.save(b); b.seek(0); return b

def test_three_yaml_files_exist(client,app):
    login(client)
    for name in ('userdb.yml','logbookdb.yml','logbook.yml'):
        assert (Path(app.instance_path)/name).exists()
    assert not (Path(app.instance_path)/'configuration.yml').exists()

def test_user_db_and_logbook_db_pages(client):
    login(client)
    assert client.get('/').status_code==200
    assert client.get('/logbook').status_code==200
    assert 'user.db' in client.get('/').get_data(as_text=True)
    assert 'Logbook' in client.get('/logbook').get_data(as_text=True)

def test_import_and_refresh_logbook(client,app):
    login(client)
    r=client.post('/import',data={'files':[(excel(['year','month','day','reg','dep','arr'],[2026,9,27,'C-AAA','YUL','YYZ']),'flight.xlsx')]},content_type='multipart/form-data')
    assert r.status_code==302
    r=client.post('/logbook/refresh',follow_redirects=True); assert r.status_code==200
    with app.app_context():
        from app.models import logbook_connect
        c=logbook_connect(); row=c.execute('SELECT date,registration,departure,arrival FROM logbook').fetchone(); c.close()
    assert row['date']=='2026-09-27'; assert row['registration']=='C-AAA'; assert row['departure']=='YUL'; assert row['arrival']=='YYZ'

def test_date_fallback_to_departure_local(client,app):
    login(client)
    # Add departure_local through the user YAML, then import a row without date parts.
    from app.models import save_config
    with app.app_context():
        cfg=load_config(); cfg['database']['columns'].append({'column':'departure_local','display_name':'departure local','position':len(cfg['database']['columns'])-3,'group':'date','data_type':'datetime','nullable':True,'visible':True,'editable':True,'import_rules':['dep datetime local']}); save_config(cfg)
        from app.models import init_db; init_db(app)
    client.post('/import',data={'files':[(excel(['dep datetime local','reg'],['2024-02-27 09:02:00','C-BBB']),'fallback.xlsx')]},content_type='multipart/form-data')
    client.post('/logbook/refresh')
    with app.app_context():
        from app.models import logbook_connect
        c=logbook_connect(); row=c.execute('SELECT date FROM logbook ORDER BY id DESC LIMIT 1').fetchone(); c.close()
    assert row['date']=='2024-02-27'

def test_logbook_has_30_rows_and_totals(client,app):
    login(client)
    # Seed 31 logbook rows directly to exercise pagination and totals.
    with app.app_context():
        from app.models import logbook_connect
        c=logbook_connect()
        for i in range(31): c.execute('INSERT INTO logbook (date,registration,single_engine_dual_day) VALUES (?,?,?)',(f'2026-09-{(i%28)+1:02d}',f'C-{i:03d}',1.5))
        c.commit(); c.close()
    body=client.get('/logbook').get_data(as_text=True)
    assert body.count('class="empty-row"')==0
    assert 'Page 1 / 2' in body
    assert 'Page Totals' in body and 'GRAND TOTAL' in body
    assert '45.00' in body

def test_logbook_cell_edit(client,app):
    login(client)
    with app.app_context():
        from app.models import logbook_connect
        c=logbook_connect(); c.execute("INSERT INTO logbook (date,registration) VALUES ('2026-09-27','OLD')"); c.commit(); c.close()
    r=client.post('/logbook/cell',data={'row_id':1,'column':'registration','value':'NEW','page':1},follow_redirects=True)
    assert r.status_code==200
    with app.app_context():
        c=__import__('app.models',fromlist=['logbook_connect']).logbook_connect(); row=c.execute('SELECT registration FROM logbook WHERE id=1').fetchone(); c.close()
    assert row['registration']=='NEW'

def test_logbook_settings_are_separate(client,app):
    login(client)
    assert client.get('/logbook/settings').status_code==200
    r=client.post('/logbook/settings/save',data={'rows_per_page':'30','row_height':'20','font_family':'Arial','font_size':'10','header_font_size':'9','width_date':'7'},follow_redirects=True)
    assert r.status_code==200
    with app.app_context():
        layout=load_logbook_layout(); db=load_logbook_db_config(); user=load_config()
    assert layout['rows_per_page']==30 and layout['row_height']==20
    assert db['database']['name']=='logbook'
    assert user['database']['name'] in {'user','users'}
