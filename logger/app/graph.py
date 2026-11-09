"""Graph page: charts of the work data defined in YAML files (<app root>/graph/*.yml, edited copies in appdata/graph/).
The format is described at the top of the shipped file graph/10_hours.yml. Expressions are those of the global profiles."""
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import yaml
from flask import Blueprint, g, jsonify, render_template, request

from . import audit, workdb          # audit adds num(), iif()... to the expression language
from . import fields as efields
from .auth import login_required
from .db import logbook_connect

graph_bp = Blueprint("graph", __name__, url_prefix="/graph")

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "graph"
FILE_ID = re.compile(r"[a-z0-9_-]+")
TYPES = ("bar", "line", "area")
TIME_KEYS = ("year", "month", "year_month")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CHART_KEYS = {"name", "type", "group_by", "measure", "cumulative", "stack_by", "stacked", "horizontal", "where", "limit"}


def edited_dir():
    try:
        from .db import appdata_root
        return appdata_root() / "graph"
    except RuntimeError:
        return None


def graph_ids():
    ids = set()
    for folder in (BUNDLED_DIR, edited_dir()):
        if folder is not None and folder.is_dir():
            ids |= {p.stem for p in folder.glob("*.yml")}
    return sorted(i for i in ids if FILE_ID.fullmatch(i))


def graph_path(file_id):
    edited = edited_dir()
    if edited is not None and (edited / f"{file_id}.yml").is_file():
        return edited / f"{file_id}.yml"
    return BUNDLED_DIR / f"{file_id}.yml"


def parse_graph(data):
    """Validates and compiles one graph file; raises workdb.SpecError with a readable message."""
    if not isinstance(data, dict) or set(data) - {"name", "measures", "charts"}:
        raise workdb.SpecError("The file contains “name”, “measures” and “charts” (see the shipped file).")
    measures = data.get("measures") or {}
    if not isinstance(measures, dict):
        raise workdb.SpecError("“measures” must map a name to an expression.")
    out = {"measures": {str(k): workdb._compile(v, f"measure {k}") for k, v in measures.items()}, "charts": []}
    for i, chart in enumerate(data.get("charts") or [], 1):
        if not isinstance(chart, dict) or not chart.get("name"):
            raise workdb.SpecError(f"chart #{i}: each chart needs a “name”.")
        where = f"chart “{chart['name']}”"
        if set(chart) - CHART_KEYS:
            raise workdb.SpecError(f"{where}: unknown key “{sorted(set(chart) - CHART_KEYS)[0]}”.")
        if chart.get("type") not in TYPES:
            raise workdb.SpecError(f"{where}: type must be bar, line or area.")
        if not isinstance(chart.get("group_by"), str):
            raise workdb.SpecError(f"{where}: “group_by” is required (year, month, year_month or a column).")
        names = chart.get("measure")
        names = [names] if isinstance(names, str) else names
        if not (isinstance(names, list) and names and all(isinstance(n, str) for n in names)):
            raise workdb.SpecError(f"{where}: “measure” is a measure name or a list of names.")
        if chart.get("stack_by") and len(names) > 1:
            raise workdb.SpecError(f"{where}: stack_by works with one measure only.")
        if chart.get("limit") is not None and not (isinstance(chart["limit"], int) and chart["limit"] > 0):
            raise workdb.SpecError(f"{where}: limit must be a positive whole number.")
        out["charts"].append({**chart, "measures": names, "name": str(chart["name"]),
                              "where_ast": workdb._compile(chart["where"], f"{where} (where)") if chart.get("where") else None})
    return out


def load_graphs():
    """(measures, charts, problems) merged from every file."""
    measures, charts, problems = {}, [], []
    for file_id in graph_ids():
        try:
            part = parse_graph(yaml.safe_load(graph_path(file_id).read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, workdb.SpecError) as exc:
            problems.append(f"{file_id}.yml : {exc}")
            continue
        measures.update(part["measures"]); charts += part["charts"]
    return measures, charts, problems


def _key(name, env):
    """(sort key, label) of a row for a time grouping or a column; None when the row has no usable date."""
    try:
        if name == "year":
            y = int(float(env.get("year"))); return (y, str(y))
        if name == "month":
            m = int(float(env.get("month"))); return (m, MONTHS[m - 1]) if 1 <= m <= 12 else None
        if name == "year_month":
            y, m = int(float(env.get("year"))), int(float(env.get("month")))
            return (y * 12 + m - 1, f"{y}-{m:02d}") if 1 <= m <= 12 else None
    except (TypeError, ValueError):
        return None
    value = env.get(name.lower())
    text = "" if value is None else str(value).strip()
    return (text.upper(), text or "(blank)")


def build_chart(chart, measures, rows):
    for name in chart["measures"]:
        if name not in measures:
            raise workdb.SpecError(f"unknown measure “{name}”.")
    group, stack = chart["group_by"], chart.get("stack_by")
    sums = defaultdict(float)            # (group sort key, series) -> hours
    labels, series_order = {}, []
    for row in rows:
        env = {str(k).lower(): v for k, v in row.items()}
        if chart["where_ast"] is not None and not audit._truthy(workdb._eval(chart["where_ast"], env, lambda _m: None)):
            continue
        gk = _key(group, env)
        sk = _key(stack, env) if stack else None
        if gk is None or (stack and sk is None):
            continue
        labels[gk[0]] = gk[1]
        for name in chart["measures"]:
            series = sk[1] if stack else name
            value = workdb._eval(measures[name], env, lambda _m: None)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = 0.0
            if series not in series_order:
                series_order.append(series)
            sums[(gk[0], series)] += value
    keys = sorted(labels)
    if group == "year_month" and keys:           # continuous months, even without a flight
        keys = list(range(keys[0], keys[-1] + 1))
        labels = {k: f"{k // 12}-{k % 12 + 1:02d}" for k in keys}
    elif group == "year" and keys:
        keys = list(range(keys[0], keys[-1] + 1)); labels = {k: str(k) for k in keys}
    elif group == "month":
        keys = list(range(1, 13)); labels = {k: MONTHS[k - 1] for k in keys}
    elif group not in TIME_KEYS:                 # a column: the biggest groups first
        keys.sort(key=lambda k: -sum(sums[(k, s)] for s in series_order))
        if chart.get("limit") and len(keys) > chart["limit"]:
            rest = keys[chart["limit"]:]; keys = keys[:chart["limit"]] + ["~other"]
            labels["~other"] = "Other"
            for s in series_order:
                sums[("~other", s)] = sum(sums[(k, s)] for k in rest)
    if stack:
        series_order.sort(key=lambda s: s.upper())
    datasets = []
    for s in series_order:
        data, running = [], 0.0
        for k in keys:
            running = running + sums[(k, s)] if chart.get("cumulative") else sums[(k, s)]
            data.append(round(running, 2))
        datasets.append({"label": s, "data": data})
    stacked = chart.get("stacked", len(datasets) > 1)
    return {"name": chart["name"], "type": chart["type"], "labels": [labels[k] for k in keys], "datasets": datasets,
            "stacked": bool(stacked), "horizontal": bool(chart.get("horizontal")), "cumulative": bool(chart.get("cumulative")),
            "total": round(sum(sums.values()) if not chart.get("cumulative") else sum(sums.values()), 1)}


def _rows():
    try:
        conn = logbook_connect()
        conn.row_factory = sqlite3.Row
        try:
            return efields.work_rows(conn, "SELECT * FROM logbook")
        finally:
            conn.close()
    except sqlite3.Error:
        return []


@graph_bp.route("/")
@login_required
def index():
    _m, charts, problems = load_graphs()
    edit_files = []
    if g.get("role") == "admin":
        for file_id in graph_ids():
            try:
                label = str(yaml.safe_load(graph_path(file_id).read_text(encoding="utf-8")).get("name") or file_id)
            except Exception:
                label = file_id
            edit_files.append((f"graph_{file_id}", label))
    return render_template("graph.html", charts=[c["name"] for c in charts], problems=problems, edit_files=edit_files)


@graph_bp.route("/data")
@login_required
def data():
    measures, charts, _p = load_graphs()
    try:
        chart = charts[int(request.args.get("chart", "0"))]
        return jsonify(build_chart(chart, measures, _rows()))
    except (ValueError, IndexError):
        return jsonify(error="Unknown chart.")
    except (workdb.SpecError, workdb.ExprError) as exc:
        return jsonify(error=str(exc))
