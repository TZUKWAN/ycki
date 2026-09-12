# -*- coding: utf-8 -*-
"""canonical_v2 只读 API（/yangtze/v2/*，13 端点）集成测试。

三层（不需要真实数据库也能跑前两层）：
1. 路由注册：13 个 v2 端点全部挂载，且不破坏既有路由（app.py / yangtze v1）。
2. 纯逻辑：分页钳制、JSON 序列化归一、库不可达 → 503（monkeypatch DSN）。
3. 真实库冒烟（127.0.0.1:5433 可连才执行，否则 skipif）：
   /system /regions /hydro /domains /timeline /traditions /processes /flows
   /networks /evolution /structure /gaps /why-yangtze?entity_name=屈原
"""
from __future__ import annotations

import socket
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import api_v2  # noqa: E402
from dashboard.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

V2_PATHS = [
    "/yangtze/v2/system",
    "/yangtze/v2/regions",
    "/yangtze/v2/hydro",
    "/yangtze/v2/domains",
    "/yangtze/v2/timeline",
    "/yangtze/v2/traditions",
    "/yangtze/v2/processes",
    "/yangtze/v2/flows",
    "/yangtze/v2/networks",
    "/yangtze/v2/evolution",
    "/yangtze/v2/structure",
    "/yangtze/v2/gaps",
    "/yangtze/v2/why-yangtze",
]

LEGACY_PATHS = [
    "/",
    "/canonical",
    "/api/overview",
    "/api/topics",
    "/yangtze/entities",
    "/yangtze/claims",
    "/yangtze/gaps",
    "/yangtze/coverage",
]

client = TestClient(app)


def _pg_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5433), timeout=1.5):
            return True
    except OSError:
        return False


HAS_PG = _pg_reachable()
requires_pg = pytest.mark.skipif(
    not HAS_PG, reason="PostgreSQL 127.0.0.1:5433 不可达，跳过真实库冒烟测试")


# ----------------------------------------------------------------------
# 1. 路由注册（不依赖数据库）
# ----------------------------------------------------------------------

def test_all_13_v2_routes_registered():
    registered = {getattr(r, "path", "") for r in app.routes}
    for path in V2_PATHS:
        assert path in registered, f"缺少 v2 端点：{path}"
    v2_only = {p for p in registered if p.startswith("/yangtze/v2/")}
    assert v2_only == set(V2_PATHS), f"v2 路由应恰好 13 条，实际：{sorted(v2_only)}"


def test_legacy_routes_untouched():
    """v2 路由加入后，既有路由不得丢失。"""
    registered = {getattr(r, "path", "") for r in app.routes}
    for path in LEGACY_PATHS:
        assert path in registered, f"既有路由丢失：{path}"


def test_v2_endpoints_have_docstrings():
    for route in app.routes:
        if getattr(route, "path", "").startswith("/yangtze/v2/"):
            assert (route.endpoint.__doc__ or "").strip(), \
                f"{route.path} 缺少 docstring（schema documented 要求）"


# ----------------------------------------------------------------------
# 2. 纯逻辑：分页钳制 / JSON 归一 / 库不可达 503
# ----------------------------------------------------------------------

def test_clamp_page_bounds():
    assert api_v2._clamp_page(1, 20) == (1, 20)
    assert api_v2._clamp_page(0, -5) == (1, 1)
    assert api_v2._clamp_page(999, 999) == (999, 200), "page_size 上限 200"


def test_jsonable_normalizes_uuid_datetime_decimal():
    uid = uuid.uuid4()
    ts = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)
    row = {"id": uid, "at": ts, "ratio": Decimal("0.5"), "n": Decimal("7"),
           "arr": [uid, Decimal("3")], "nested": {"ok": True}}
    out = api_v2._jsonable(row)
    assert out["id"] == str(uid) and isinstance(out["id"], str)
    assert out["at"] == "2026-09-13 12:00:00+00:00"
    assert out["ratio"] == 0.5 and isinstance(out["ratio"], float)
    assert out["n"] == 7 and isinstance(out["n"], int), "整值 Decimal 应转 int"
    assert out["arr"] == [str(uid), 3]
    assert out["nested"] == {"ok": True}


def _closed_port_dsn() -> str:
    """拿一个当前空闲（必然拒绝连接）的本地端口构造坏 DSN。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"host=127.0.0.1 port={port} dbname=ycki user=postgres password=x connect_timeout=2"


def test_db_unreachable_returns_503(monkeypatch):
    """库连不上时端点必须 503 {"detail": "database unavailable"}，不得崩溃。"""
    monkeypatch.setattr(api_v2.SETTINGS, "pg_dsn", _closed_port_dsn())
    for path in ("/yangtze/v2/system", "/yangtze/v2/hydro", "/yangtze/v2/structure"):
        resp = client.get(path)
        assert resp.status_code == 503, f"{path} 应 503，实际 {resp.status_code}"
        assert resp.json() == {"detail": "database unavailable"}


def test_missing_table_maps_to_503(monkeypatch):
    """受控表不存在（UndefinedTable）也应被 _conn 归一为 503，不泄漏 SQL 错误。"""
    import psycopg2

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            raise psycopg2.errors.UndefinedTable(
                'relation "cultural_systems" does not exist')

    class _FakeConn:
        def cursor(self, cursor_factory=None):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(api_v2.psycopg2, "connect", lambda *a, **k: _FakeConn())
    resp = client.get("/yangtze/v2/system")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "database unavailable"}


# ----------------------------------------------------------------------
# 3. 真实库冒烟（5433 可连才执行）
# ----------------------------------------------------------------------

@requires_pg
def test_smoke_system_tree_contains_root():
    resp = client.get("/yangtze/v2/system")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(body["items"])
    names = [i["system_name"] for i in body["items"]]
    assert "长江文化" in names, "items 中必须含根系统 长江文化"
    roots = [n for n in body["tree"] if n["parent_system"] is None]
    assert len(roots) == 1 and len(roots[0]["children"]) == 7, "应为 根+7 区域系统树"
    for key in ("membership_count", "tradition_count", "process_count", "flow_count"):
        assert isinstance(body["totals"][key], int)


@requires_pg
def test_smoke_regions_payload():
    resp = client.get("/yangtze/v2/regions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 7
    for item in body["items"]:
        assert {"region_id", "region_name", "provinces", "hydro_basis",
                "system_count", "systems"} <= set(item)
        assert isinstance(item["systems"], list)


@requires_pg
def test_smoke_hydro_filters_and_pagination():
    resp = client.get("/yangtze/v2/hydro")
    assert resp.status_code == 200
    body = resp.json()
    assert {"total", "page", "page_size", "items"} <= set(body)
    assert body["total"] >= 30

    clamped = client.get("/yangtze/v2/hydro", params={"page": 0, "page_size": 9999}).json()
    assert clamped["page"] == 1 and clamped["page_size"] == 200

    basin = client.get("/yangtze/v2/hydro", params={"type": "Basin"}).json()
    assert basin["total"] >= 1
    assert all(i["hsu_type"] == "Basin" for i in basin["items"])

    stem = client.get("/yangtze/v2/hydro", params={"parent": "长江干流"})
    assert stem.status_code == 200
    assert all(i["parent_name"] == "长江干流" for i in stem.json()["items"])
    for item in body["items"]:
        assert isinstance(item["relation_count"], int)


@requires_pg
def test_smoke_domains_tree_nested():
    resp = client.get("/yangtze/v2/domains")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1 and isinstance(body["tree"], list)

    def flatten(nodes):
        for n in nodes:
            yield n["domain_name"]
            yield from flatten(n["children"])
    names = list(flatten(body["tree"]))
    assert len(names) == body["total"], "全树必须一次返回、不得丢节点"


@requires_pg
def test_smoke_timeline_13_phases_in_yaml_order():
    resp = client.get("/yangtze/v2/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 13
    names = [i["phase_name"] for i in body["items"]]
    assert names[0] == "史前时期" and names[-1] == "新时代"
    assert len(set(names)) == 13
    for item in body["items"]:
        assert isinstance(item["patterns"], list)
        assert isinstance(item["process_count"], int)
        assert isinstance(item["tradition_count"], int)
        for pat in item["patterns"]:
            assert {"pattern_id", "pattern_code", "pattern_name", "note"} <= set(pat)


@requires_pg
def test_smoke_traditions_processes_flows_envelope():
    for path, params in (
            ("/yangtze/v2/traditions", {"status": "CANDIDATE", "q": "稻作"}),
            ("/yangtze/v2/processes", {"process_type": "MIGRATION"}),
            ("/yangtze/v2/flows", {"flow_type": "TECHNOLOGY"})):
        resp = client.get(path, params=params)
        assert resp.status_code == 200, path
        body = resp.json()
        assert {"total", "page", "page_size", "items"} <= set(body)
        assert isinstance(body["items"], list)
    procs = client.get("/yangtze/v2/processes").json()
    for item in procs["items"]:
        assert isinstance(item["stage_count"], int)


@requires_pg
def test_smoke_networks_grouping():
    resp = client.get("/yangtze/v2/networks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == sum(p["total"] for p in body["by_predicate"])
    assert isinstance(body["by_knowledge_type"], dict)
    assert all(isinstance(v, int) for v in body["by_knowledge_type"].values())


@requires_pg
def test_smoke_evolution_matrix():
    resp = client.get("/yangtze/v2/evolution")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["phases"]) == 13
    assert len(body["matrix"]) == 13
    assert body["phases"][0] == "史前时期" and body["phases"][-1] == "新时代"
    assert body["patterns"], "至少应有一条宏观演化模式"
    for p in body["patterns"]:
        assert {"pattern_id", "pattern_code", "pattern_name", "phase_count"} <= set(p)
    for row in body["matrix"]:
        assert isinstance(row["patterns"], list)


@requires_pg
def test_smoke_structure_counts_and_manifest():
    resp = client.get("/yangtze/v2/structure")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["systems"] == 8
    assert body["counts"]["phases"] == 13
    assert all(isinstance(v, int) for v in body["counts"].values())
    assert body["manifest"]["mode"] == "counts_only"
    assert body["manifest"]["verified"] is False


@requires_pg
def test_smoke_gaps_envelope():
    resp = client.get("/yangtze/v2/gaps", params={"status": "OPEN"})
    assert resp.status_code == 200
    body = resp.json()
    assert {"total", "page", "page_size", "items"} <= set(body)


@requires_pg
def test_smoke_why_yangtze_quyuan_valid_json():
    """屈原：200（有结构路径）或 404（无该实体）之一，且 JSON 结构合法。"""
    resp = client.get("/yangtze/v2/why-yangtze", params={"entity_name": "屈原"})
    assert resp.status_code in (200, 404)
    body = resp.json()
    assert "detail" in body or {"entity", "target", "path_count", "paths",
                                "explanation"} <= set(body)
    if resp.status_code == 200:
        assert body["path_count"] == len(body["paths"])
        assert body["target"]
        assert body["explanation"].strip(), "200 时必须带解释文本"
        if not body["paths"]:
            # 实体存在但无结构锚点：允许 paths=[]，explanation 须说明原因
            assert "membership" in body["explanation"]
        for path in body["paths"]:
            assert path["steps"], "每条路径至少一步"
            for step in path["steps"]:
                assert {"from", "to", "relation", "evidence_id"} <= set(step)
            assert path["steps"][0]["from"]["name"] == "屈原"
            assert path["steps"][-1]["to"]["name"] == body["target"]


@requires_pg
def test_smoke_why_yangtze_unknown_entity_404():
    resp = client.get("/yangtze/v2/why-yangtze",
                      params={"entity_name": "绝不存在的实体_qqzz0019"})
    assert resp.status_code == 404
    assert "entity not found" in resp.json()["detail"]


@requires_pg
def test_smoke_why_yangtze_requires_entity_name():
    resp = client.get("/yangtze/v2/why-yangtze")
    assert resp.status_code == 400
