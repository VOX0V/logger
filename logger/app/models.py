import re
import sqlite3
from pathlib import Path
import yaml
import shutil
from flask import current_app

SYSTEM_COLUMNS = [
    {"column":"id","display_name":"ID","position":0,"group":"system","data_type":"integer","nullable":False,"visible":False,"editable":False,"primary_key":True},
    {"column":"created_at","display_name":"Created at","position":0,"group":"system","data_type":"datetime","nullable":False,"visible":False,"editable":False},
    {"column":"updated_at","display_name":"Updated at","position":0,"group":"system","data_type":"datetime","nullable":False,"visible":False,"editable":False},
    {"column":"import_source","display_name":"Import source","position":0,"group":"system","data_type":"text","nullable":True,"visible":False,"editable":False},
]
LOGBOOK_SYSTEM_COLUMNS = [dict(c) for c in SYSTEM_COLUMNS]
DEFAULT_COLUMNS = [
 {"position":1,"display_name":"year","group":"date","column":"year","data_type":"integer","nullable":True,"visible":True,"editable":True,"import_rules":["year"]},
 {"position":2,"display_name":"month","group":"date","column":"month","data_type":"integer","nullable":True,"visible":True,"editable":True,"import_rules":["month"]},
 {"position":3,"display_name":"day","group":"date","column":"day","data_type":"integer","nullable":True,"visible":True,"editable":True,"import_rules":["day"]},
 {"position":4,"display_name":"type","group":"aircraft","column":"type","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["type"]},
 {"position":5,"display_name":"registration","group":"aircraft","column":"registration","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["immat","reg","registration"]},
 {"position":6,"display_name":"pilot in command","group":"crew","column":"pilot_in_command","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["pic"]},
 {"position":7,"display_name":"copilot","group":"crew","column":"copilot","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["copi"]},
 {"position":8,"display_name":"departure","group":"route","column":"departure","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["dep"]},
 {"position":9,"display_name":"arrival","group":"route","column":"arrival","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["arr"]},
 {"position":10,"display_name":"remarks","group":"remarks","column":"remarks","data_type":"text","nullable":True,"visible":True,"editable":True,"import_rules":["remarks"]},
]

DEFAULT_LOGBOOK_DB_COLUMNS = [
 {"column":"date","display_name":"date","position":1,"group":"date","data_type":"date","nullable":True,"visible":True,"editable":True,
  "source":[{"type":"date_parts","source":["users.year","users.month","users.day"]},{"type":"datetime","source":["users.departure_local"]}],"transformation":"date"},
]

# Layout is deliberately separate from the logbook database schema.
DEFAULT_LOGBOOK_LAYOUT = {
 "title":"Logbook",
 "rows_per_page":30,
 "row_height":16.95,
 "header_heights":[16.95,16.95,16.95,16.95],
 "styles":{"font_family":"Arial","font_size":10,"header_font_size":9,"border":"1px solid #000000","header_background":"#ffffff","total_background":"#eeeeee","text_align":"center","vertical_align":"middle"},
 "columns":[
  {"key":"year","label":"YEAR","db_column":"date","date_part":"year","width":6.55,"group":"date"},
  {"key":"month","label":"Month","db_column":"date","date_part":"month","width":13,"group":"date"},
  {"key":"day","label":"Day","db_column":"date","date_part":"day","width":13,"group":"date"},
  {"key":"type","label":"Type","db_column":"aircraft_type","width":13,"group":"aircraft"},
  {"key":"registration","label":"Registr.","db_column":"registration","width":8.33,"group":"aircraft"},
  {"key":"pilot","label":"Pilot","db_column":"pilot_in_command","width":11.55,"group":"crew"},
  {"key":"copilot","label":"Co-Pilot","db_column":"copilot","width":13,"group":"crew"},
  {"key":"departure","label":"Departure","db_column":"departure","width":10,"group":"route"},
  {"key":"arrival","label":"Arrival","db_column":"arrival","width":13,"group":"route"},
  {"key":"remarks","label":"Exercise, Mission, Flight Number…","db_column":"remarks","width":13,"group":"remarks","colspan":2},
  {"key":"remarks_cont","label":"","width":27.11,"group":"remarks_cont"},
  {"key":"se_dual_day","label":"Dual","db_column":"single_engine_dual_day","width":7.55,"group":"single_engine","subgroup":"Day"},
  {"key":"se_pic_day","label":"PIC","db_column":"single_engine_pic_day","width":13,"group":"single_engine","subgroup":"Day"},
  {"key":"se_dual_night","label":"Dual","db_column":"single_engine_dual_night","width":13,"group":"single_engine","subgroup":"Night"},
  {"key":"se_pic_night","label":"PIC","db_column":"single_engine_pic_night","width":13,"group":"single_engine","subgroup":"Night"},
  {"key":"spacer1","label":"","width":3.89,"group":"spacer"},
  {"key":"spacer2","label":"","width":4.89,"group":"spacer"},
  {"key":"me_dual_day","label":"Dual","db_column":"multi_engine_dual_day","width":7.66,"group":"multi_engine","subgroup":"Day"},
  {"key":"me_pic_day","label":"PIC","db_column":"multi_engine_pic_day","width":13,"group":"multi_engine","subgroup":"Day"},
  {"key":"me_copilot_day","label":"Co-Pilot","db_column":"multi_engine_copi_day","width":13,"group":"multi_engine","subgroup":"Day"},
  {"key":"me_dual_night","label":"Dual","db_column":"multi_engine_dual_night","width":13,"group":"multi_engine","subgroup":"Night"},
  {"key":"me_pic_night","label":"PIC","db_column":"multi_engine_pic_night","width":13,"group":"multi_engine","subgroup":"Night"},
  {"key":"me_copilot_night","label":"Co-Pilot","db_column":"multi_engine_copi_night","width":13,"group":"multi_engine","subgroup":"Night"},
  {"key":"ifr","label":"IFR","db_column":"ifr","width":13,"group":"instruments"},
  {"key":"hood","label":"Hood","db_column":"hood","width":13,"group":"instruments"},
  {"key":"ftd","label":"FTD","db_column":"ftd","width":13,"group":"instruments"},
  {"key":"ifr_app","label":"IFR app","db_column":"ifr_approach","width":13,"group":"instruments"},
  {"key":"cc_dual_day","label":"Dual","db_column":"cross_country_dual_day","width":13,"group":"cross_country","subgroup":"Day"},
  {"key":"cc_pic_day","label":"PIC","db_column":"cross_country_pic_day","width":13,"group":"cross_country","subgroup":"Day"},
  {"key":"cc_dual_night","label":"Dual","db_column":"cross_country_dual_night","width":13,"group":"cross_country","subgroup":"Night"},
  {"key":"cc_pic_night","label":"PIC","db_column":"cross_country_pic_night","width":13,"group":"cross_country","subgroup":"Night"},
  {"key":"land_day","label":"Day","db_column":"landings_day","width":13,"group":"landings"},
  {"key":"land_night","label":"Night","db_column":"landings_night","width":13,"group":"landings"},
  {"key":"instruction_day","label":"Day","db_column":"instruction_day","width":13,"group":"instruction"},
  {"key":"instruction_night","label":"Night","db_column":"instruction_night","width":13,"group":"instruction"},
  {"key":"total","label":"Total","width":5,"group":"total","total":True},
 ],
 "group_labels":{"date":"YEAR","aircraft":"AIRCRAFT","crew":"FLIGHT CREW","route":"ROUTE OF FLIGHT","remarks":"REMARKS","single_engine":"SINGLE-ENGINE","multi_engine":"MULTI-ENGINE","instruments":"INSTRUMENTS","cross_country":"CROSS-COUNTRY","landings":"TAKEOFFS & LANDINGS","instruction":"INSTRUCTION","total":""},
 "group_spans":{"date":3,"aircraft":2,"crew":2,"route":2,"remarks":2,"single_engine":4,"spacer":2,"multi_engine":6,"instruments":4,"cross_country":4,"landings":2,"instruction":2,"total":1}
}

def instance_file(name):
    return Path(current_app.instance_path) / name

def config_path(): return instance_file("userdb.yml")
def logbook_db_config_path(): return instance_file("logbookdb.yml")
def logbook_layout_path(): return instance_file("logbook.yml")
def legacy_config_path(): return instance_file("configuration.yml")

def safe_identifier(value):
    value=str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value): raise ValueError(f"Nom de colonne technique invalide: {value}")
    return value

def _technical_name(display_name):
    value=re.sub(r"_+","_",re.sub(r"[^a-z0-9]+","_",str(display_name or "").strip().lower())).strip("_")
    if not value: raise ValueError("Le display_name doit produire un nom de colonne technique valide.")
    if value[0].isdigit(): value="_"+value
    safe_identifier(value)
    return value

def _norm_user(raw,index):
    item=dict(raw or {}); display=str(item.get("display_name",item.get("affichage","")) or "").strip(); col=str(item.get("column",item.get("colonne_technique","")) or "").strip() or _technical_name(display)
    safe_identifier(col); rules=item.get("import_rules",item.get("import",[])) or []; rules=list(dict.fromkeys(str(x).strip() for x in rules if str(x).strip()))
    dt=str(item.get("data_type","text") or "text").lower()
    return {"column":col,"display_name":display,"position":index,"group":str(item.get("group",item.get("groupe","")) or "").strip(),"data_type":dt,"nullable":bool(item.get("nullable",True)),"visible":bool(item.get("visible",True)),"editable":bool(item.get("editable",True)),"import_rules":rules}

def _norm_system(raw, base):
    by={x.get("column"):dict(x) for x in (raw or []) if x.get("column")}; out=[]
    for b in base:
        x=dict(b); x.update(by.get(b["column"],{})); x.update(group="system",position=0,visible=False,editable=False); out.append(x)
    return out

def _norm_lb(raw,index):
    x=dict(raw or {}); display=str(x.get("display_name",x.get("affichage","")) or "").strip(); col=str(x.get("column","") or "").strip() or _technical_name(display); safe_identifier(col)
    src=x.get("source",[]) or []
    if isinstance(src,str): src=[src]
    # Preserve structured source rules for fallbacks.
    norm=[]
    for s in src:
        if isinstance(s,dict): norm.append({"type":str(s.get("type","")),"source":[str(v).strip() for v in (s.get("source",[]) or [])]})
        else: norm.append(str(s).strip())
    return {"column":col,"display_name":display,"position":index,"group":str(x.get("group",x.get("groupe","")) or ""),"data_type":str(x.get("data_type","text") or "text").lower(),"nullable":bool(x.get("nullable",True)),"visible":bool(x.get("visible",True)),"editable":bool(x.get("editable",True)),"source":norm,"transformation":str(x.get("transformation","") or "")}

def _load_yaml(path, fallback):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_text(yaml.safe_dump(fallback,allow_unicode=True,sort_keys=False),encoding="utf-8")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

def ensure_configs():
    instance=Path(current_app.instance_path); instance.mkdir(parents=True,exist_ok=True)
    legacy=legacy_config_path()
    if legacy.exists() and (not config_path().exists() or not logbook_db_config_path().exists()):
        old=yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}
        if not config_path().exists(): config_path().write_text(yaml.safe_dump({"database":old.get("database",{})},allow_unicode=True,sort_keys=False),encoding="utf-8")
        if not logbook_db_config_path().exists(): logbook_db_config_path().write_text(yaml.safe_dump({"database":{"name":"logbook","columns":old.get("logbook",{}).get("columns",DEFAULT_LOGBOOK_DB_COLUMNS)}},allow_unicode=True,sort_keys=False),encoding="utf-8")
        # The legacy file has been split into the three new configuration files.
        try: legacy.unlink()
        except OSError: pass
    if not config_path().exists():
        bundled=Path(current_app.root_path).parent/"default-userdb.yml"
        data=yaml.safe_load(bundled.read_text(encoding="utf-8")) if bundled.exists() else {"database":{"name":"user","columns":DEFAULT_COLUMNS}}
        config_path().write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding="utf-8")
    if not logbook_db_config_path().exists(): logbook_db_config_path().write_text(yaml.safe_dump({"database":{"name":"logbook","columns":DEFAULT_LOGBOOK_DB_COLUMNS}},allow_unicode=True,sort_keys=False),encoding="utf-8")
    if not logbook_layout_path().exists(): logbook_layout_path().write_text(yaml.safe_dump(DEFAULT_LOGBOOK_LAYOUT,allow_unicode=True,sort_keys=False),encoding="utf-8")

def load_config():
    ensure_configs(); raw=_load_yaml(config_path(),{})
    db=raw.get("database",raw); cols=db.get("columns",raw.get("categories",[])) or []
    systems=_norm_system(cols,SYSTEM_COLUMNS); normal=[_norm_user(x,i) for i,x in enumerate([x for x in cols if x.get("group")!="system"],1)]
    return {"database":{"name":db.get("name","user"),"columns":systems+normal}}

def save_config(data):
    db=data.get("database",data); cols=db.get("columns",[]); config_path().write_text(yaml.safe_dump({"database":{"name":db.get("name","user"),"columns":cols}},allow_unicode=True,sort_keys=False),encoding="utf-8")

def load_logbook_db_config():
    ensure_configs(); raw=_load_yaml(logbook_db_config_path(),{}); db=raw.get("database",raw); cols=db.get("columns",[]) or []
    systems=_norm_system(cols,LOGBOOK_SYSTEM_COLUMNS); normal=[_norm_lb(x,i) for i,x in enumerate([x for x in cols if x.get("group")!="system"],1)]
    return {"database":{"name":"logbook","columns":systems+normal}}

def save_logbook_db_config(data):
    db=data.get("database",data); logbook_db_config_path().write_text(yaml.safe_dump({"database":{"name":"logbook","columns":db.get("columns",[])}},allow_unicode=True,sort_keys=False),encoding="utf-8")

def load_logbook_layout():
    ensure_configs(); raw=_load_yaml(logbook_layout_path(),DEFAULT_LOGBOOK_LAYOUT); cfg=dict(DEFAULT_LOGBOOK_LAYOUT); cfg.update(raw or {}); cfg["styles"]={**DEFAULT_LOGBOOK_LAYOUT["styles"],**(raw or {}).get("styles",{})}; cfg["columns"]=(raw or {}).get("columns",DEFAULT_LOGBOOK_LAYOUT["columns"]); return cfg

def save_logbook_layout(data): logbook_layout_path().write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding="utf-8")

def configurable_columns(config): return [c for c in config["database"]["columns"] if c.get("group")!="system"]
def logbook_columns(config): return [c for c in load_logbook_db_config()["database"]["columns"] if c.get("group")!="system"]
def system_columns(config): return [c for c in config["database"]["columns"] if c.get("group")=="system"]
def db_path(): return instance_file("user.db")
def logbook_db_path(): return instance_file("logbook.db")
def sqlite_type(dt): return {"integer":"INTEGER","decimal":"REAL","boolean":"INTEGER","date":"TEXT","datetime":"TEXT","text":"TEXT"}.get(dt,"TEXT")
def connect():
    conn=sqlite3.connect(db_path()); conn.row_factory=sqlite3.Row; return conn
def logbook_connect():
    conn=sqlite3.connect(logbook_db_path()); conn.row_factory=sqlite3.Row; return conn

def sync_columns(conn,table,columns):
    existing={r[1] for r in conn.execute(f'PRAGMA table_info({safe_identifier(table)})').fetchall()}
    for c in columns:
        col=safe_identifier(c["column"])
        if col=="id" or col in existing: continue
        nullable="" if not c.get("nullable",True) else ""
        conn.execute(f'ALTER TABLE "{safe_identifier(table)}" ADD COLUMN "{col}" {sqlite_type(c.get("data_type"))}{" NOT NULL" if nullable=="" and not c.get("nullable",True) else ""}')

def sync_user_columns(conn,config): sync_columns(conn,"users",config["database"]["columns"])
def sync_logbook_columns(conn,config): sync_columns(conn,"logbook",load_logbook_db_config()["database"]["columns"])

def drop_unused_columns(conn,config):
    configured={c["column"] for c in config["database"]["columns"]}; existing=[r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    for col in existing:
        if col not in configured and col not in {c["column"] for c in SYSTEM_COLUMNS}: conn.execute(f'DROP COLUMN "{safe_identifier(col)}"')
def drop_unused_logbook_columns(conn,config):
    configured={c["column"] for c in load_logbook_db_config()["database"]["columns"]}; existing=[r[1] for r in conn.execute("PRAGMA table_info(logbook)").fetchall()]
    for col in existing:
        if col not in configured and col not in {c["column"] for c in LOGBOOK_SYSTEM_COLUMNS}: conn.execute(f'DROP COLUMN "{safe_identifier(col)}"')

def import_rows(source,rows,config):
    conn=connect(); sync_user_columns(conn,config); drop_unused_columns(conn,config); cols=[safe_identifier(c["column"]) for c in configurable_columns(config)]; conn.execute("DELETE FROM users WHERE import_source=?",(source,))
    if rows and cols:
        sql=f'INSERT INTO users (import_source,{",".join(chr(34)+c+chr(34) for c in cols)}) VALUES (?,{",".join("?" for _ in cols)})'
        for row in rows: conn.execute(sql,[source]+[row.get(c) for c in cols])
    conn.commit(); conn.close()

def list_users(config):
    conn=connect(); visible=[c for c in configurable_columns(config) if c.get("visible",True)]; cols=[c["column"] for c in sorted(visible,key=lambda c:int(c["position"]))]; select=",".join(["id"]+[f'"{safe_identifier(c)}"' for c in cols]); rows=conn.execute(f"SELECT {select} FROM users ORDER BY id").fetchall(); conn.close(); return cols,rows

def _row_value(row,path):
    key=path.split(".",1)[1] if "." in path else path
    return row[key] if key in row.keys() else None

def transform_logbook_value(column,row):
    source=column.get("source",[]) or []
    if column.get("transformation")=="date":
        for rule in source:
            if isinstance(rule,dict):
                typ=rule.get("type"); vals=[_row_value(row,s) for s in rule.get("source",[])]
                if typ=="date_parts" and len(vals)>=3 and all(v not in (None,"") for v in vals[:3]):
                    try: return f"{int(vals[0]):04d}-{int(vals[1]):02d}-{int(vals[2]):02d}"
                    except (TypeError,ValueError): pass
                if typ=="datetime" and vals and vals[0] not in (None,""):
                    text=str(vals[0]); return text[:10] if len(text)>=10 else None
        vals=[_row_value(row,s) for s in source if isinstance(s,str)]
        if len(vals)>=3 and all(v not in (None,"") for v in vals[:3]):
            try:return f"{int(vals[0]):04d}-{int(vals[1]):02d}-{int(vals[2]):02d}"
            except (TypeError,ValueError): pass
        return None
    vals=[_row_value(row,s) for s in source if isinstance(s,str)]
    return vals[0] if len(vals)==1 else (" ".join(str(v) for v in vals if v not in (None,"")) or None)

def refresh_logbook(config):
    lcfg=load_logbook_db_config(); conn=logbook_connect(); uc=connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)"); sync_logbook_columns(conn,config); drop_unused_logbook_columns(conn,config)
        ucols=[c["column"] for c in configurable_columns(config)]; select=",".join(["id","import_source"]+[f'"{safe_identifier(c)}"' for c in ucols]); rows=uc.execute(f"SELECT {select} FROM users ORDER BY id").fetchall(); cols=lcfg["database"]["columns"][4:]; names=[safe_identifier(c["column"]) for c in cols]; conn.execute("DELETE FROM logbook")
        for row in rows:
            values=[transform_logbook_value(c,row) for c in cols]
            if names: conn.execute(f'INSERT INTO logbook (import_source,{",".join(chr(34)+n+chr(34) for n in names)}) VALUES (?,{",".join("?" for _ in names)})',[row["import_source"]]+values)
        conn.commit()
    finally: uc.close(); conn.close()

def list_logbook_rows():
    conn=logbook_connect(); rows=conn.execute("SELECT * FROM logbook ORDER BY id").fetchall(); conn.close(); return rows

def update_logbook_cell(row_id,column,value):
    safe_identifier(column); conn=logbook_connect(); conn.execute(f'UPDATE logbook SET "{column}"=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',(value,row_id)); conn.commit(); conn.close()

def init_db(app):
    with app.app_context():
        config=load_config(); lcfg=load_logbook_db_config(); conn=connect(); conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)"); sync_user_columns(conn,config); conn.commit(); conn.close()
        lb=logbook_connect(); lb.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)"); sync_logbook_columns(lb,config); lb.commit(); lb.close()
