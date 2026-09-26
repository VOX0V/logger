import sqlite3
from app.importer import build_records


def test_unmapped_category_is_ignored_when_db_column_is_missing():
    categories = [
        {"id": 1, "column_name": "year"},
        {"id": 2, "column_name": "type"},
    ]
    # Simulates a DB that only has type; year has no destination.
    existing_columns = {"type"}
    importable = [c for c in categories if c["column_name"] in existing_columns]
    rules = {1: ["year"], 2: ["type"]}
    sources = [("flights.xlsx", "Sheet1", ["year", "type"], [(2026, "R44")])]

    records, _ = build_records(sources, importable, rules)

    assert records == [{"type": "R44", "_import_source": "flights.xlsx"}]


def test_same_import_source_replaces_previous_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, type TEXT, import_source TEXT)")
    conn.execute("INSERT INTO users(type, import_source) VALUES(?, ?)", ("OLD", "flights.xlsx"))
    conn.execute("INSERT INTO users(type, import_source) VALUES(?, ?)", ("KEEP", "other.xlsx"))

    records = [
        {"type": "NEW", "_import_source": "flights.xlsx"},
        {"type": "NEW2", "_import_source": "flights.xlsx"},
    ]
    conn.execute("DELETE FROM users WHERE import_source = ?", ("flights.xlsx",))
    conn.executemany(
        "INSERT INTO users(type, import_source) VALUES(?, ?)",
        [(r["type"], r["_import_source"]) for r in records],
    )
    conn.commit()

    assert conn.execute("SELECT type FROM users ORDER BY id").fetchall() == [("KEEP",), ("NEW",), ("NEW2",)]
