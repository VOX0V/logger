"""Server-side pagination/sort/filter/export for the Tabulator grids on the
Données brutes and Données converties pages (reads only ; cell edits go through
the dedicated /logbook/cell route). `expressions` maps a displayed column to an
SQL expression, e.g. year/month/day extracted from the ISO date."""
import csv
import io

from flask import request, jsonify, send_file
from openpyxl import Workbook

from .db import safe_identifier


def _sql(col, expressions):
    return (expressions or {}).get(col) or f'"{safe_identifier(col)}"'


def _clauses(columns, expressions=None):
    allowed = set(columns)
    args = request.args
    where, params = [], []
    i = 0
    while f"filter[{i}][field]" in args:
        field = args.get(f"filter[{i}][field]", "")
        value = args.get(f"filter[{i}][value]", "")
        if field in allowed and value != "":
            where.append(f'CAST({_sql(field, expressions)} AS TEXT) LIKE ? ESCAPE \'\\\'')
            params.append("%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        i += 1
    sorts = []
    j = 0
    while f"sort[{j}][field]" in args:
        field = args.get(f"sort[{j}][field]", "")
        direction = args.get(f"sort[{j}][dir]", "asc")
        if field in allowed and direction in ("asc", "desc"):
            sorts.append(f'{_sql(field, expressions)} {direction.upper()}')
        j += 1
    return where, params, sorts


def _select(table, columns, where, params, sorts, limit_offset=None, expressions=None):
    select = ",".join(["id"] + [f'{_sql(c, expressions)} AS "{safe_identifier(c)}"' for c in columns])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = f"ORDER BY {', '.join(sorts)}" if sorts else "ORDER BY id"
    sql = f"SELECT {select} FROM {table} {where_sql} {order_sql}"
    if limit_offset:
        sql += " LIMIT ? OFFSET ?"; params = params + list(limit_offset)
    return sql, params


def grid_data(conn, table, columns, expressions=None):
    """JSON response for one Tabulator page, honoring its sort/filter state."""
    where, params, sorts = _clauses(columns, expressions)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0]
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(2000, max(1, int(request.args.get("size", 200))))
    except ValueError:
        page, size = 1, 200
    sql, sql_params = _select(table, columns, where, params, sorts, limit_offset=(size, (page - 1) * size), expressions=expressions)
    rows = conn.execute(sql, sql_params).fetchall()
    return jsonify({"data": [dict(r) for r in rows], "last_page": max(1, -(-total // size))})


def grid_export(conn, table, columns, labels, fmt, filename, expressions=None):
    """Export every row matching the grid's current filter/sort as CSV or XLSX."""
    where, params, sorts = _clauses(columns, expressions)
    sql, sql_params = _select(table, columns, where, params, sorts, expressions=expressions)
    rows = conn.execute(sql, sql_params).fetchall()
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(labels)
        for r in rows:
            writer.writerow([r[c] for c in columns])
        data = buf.getvalue().encode("utf-8-sig")
        return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True, download_name=f"{filename}.csv")
    if fmt == "xlsx":
        wb = Workbook(); ws = wb.active
        ws.append(list(labels))
        for r in rows:
            ws.append([r[c] for c in columns])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    raise ValueError("Format d'export invalide.")
