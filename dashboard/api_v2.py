# -*- coding: utf-8 -*-
"""/yangtze/v2/* — canonical_v2 受控本体只读 API（13 端点）。

数据源：deploy/sql/006_cultural_system_v2.sql + 007_structural_layer_v2.sql
创建的 canonical_v2 受控表（cultural_systems / cultural_regions /
cultural_domains / historical_phases / hydro_spatial_units /
hydro_spatial_relations / system_memberships / structural_relations /
cultural_traditions / cultural_processes / cultural_flows /
macro_evolution_patterns / historical_phase_patterns / structural_gaps /
interpretations / structural_admissions）。只读，不写任何表。

质量约定（目标 §79-80）：
- 全部参数化查询（%s 占位），零字符串拼接 SQL；
- 分页端点统一返回 {total, page, page_size, items}，page_size 默认 20、上限 200；
- 库连不上 / 受控表缺失 → 503 {"detail": "database unavailable"}；
- 其余未预期异常 → 500 {"detail": "internal error"}（原始错误只进日志，不外泄）；
- uuid/datetime 统一转 str、count 一律 int，保证全部响应可 JSON 序列化；
- 每个端点 docstring 注明返回结构（schema documented）。
"""
from __future__ import annotations

import functools
import logging
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2
import psycopg2.extras
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.settings import SETTINGS

logger = logging.getLogger("ycki.api_v2")

router = APIRouter(prefix="/yangtze/v2", tags=["canonical-v2"])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200

# 分期 YAML 顺序的权威来源（只读 seed，不修改）
PHASE_SEED_YAML = ROOT / "yangtze" / "schema" / "historical_phases.yaml"


class DatabaseUnavailable(Exception):
    """受控库不可达或受控表缺失（对外一律 503）。"""


# ----------------------------------------------------------------------
# 基础设施
# ----------------------------------------------------------------------

def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """page 从 1 起；page_size 夹在 [1, 200]。"""
    return max(1, page), max(1, min(page_size, PAGE_SIZE_MAX))


def _jsonable(value):
    """uuid/datetime → str，Decimal → int/float，递归处理 dict/list/tuple/set。"""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (uuid.UUID, datetime, date, dtime)):
        return str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@contextmanager
def _conn():
    """受控库连接；连不上或执行出错统一抛 DatabaseUnavailable（路由层转 503）。"""
    dsn = SETTINGS.pg_dsn
    kw = {} if "connect_timeout" in dsn else {"connect_timeout": 5}
    try:
        conn = psycopg2.connect(dsn, **kw)
    except psycopg2.Error as exc:
        raise DatabaseUnavailable() from exc
    try:
        yield conn
    except psycopg2.Error as exc:
        raise DatabaseUnavailable() from exc
    finally:
        conn.close()


def _guarded(fn):
    """路由守卫：DB 问题→503；其余异常→500（log 后只返回固定 detail）。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatabaseUnavailable:
            logger.warning("api_v2 %s: database unavailable", fn.__name__)
            return JSONResponse({"detail": "database unavailable"}, status_code=503)
        except Exception:
            logger.exception("api_v2 %s: internal error", fn.__name__)
            return JSONResponse({"detail": "internal error"}, status_code=500)
    return wrapper


@functools.lru_cache(maxsize=1)
def _phase_seed_order() -> tuple[str, ...] | None:
    """historical_phases.yaml 中 13 分期的权威顺序；seed 不可读时返回 None。"""
    try:
        import yaml
        with PHASE_SEED_YAML.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        names = tuple(p["name"] for p in (data.get("phases") or [])
                      if isinstance(p, dict) and p.get("name"))
        return names or None
    except Exception:
        return None


def _sort_phases_yaml(rows: list[dict]) -> list[dict]:
    """按 seed YAML 顺序稳定排序分期行；YAML 中未登记的分期按原顺序追加在尾部。"""
    order = _phase_seed_order()
    if not order:
        return rows
    idx = {name: i for i, name in enumerate(order)}
    return sorted(rows, key=lambda r: idx.get(r.get("phase_name"), len(idx)))


# ----------------------------------------------------------------------
# 1. GET /yangtze/v2/system — 根系统 + 7 区域系统树
# ----------------------------------------------------------------------

@router.get("/system")
@_guarded
def system_tree():
    """受控文化系统树（根系统 + 区域子系统）及计数。

    返回：{total, items: [展平系统节点], tree: [根节点(嵌套 children)],
           totals: {membership_count, tradition_count, process_count, flow_count}}
    节点字段：system_id, system_name, system_level, parent_system, description,
              region {region_id, region_name} | null,
              membership_count（system_memberships 直挂数）,
              tradition_count（tradition_variants.system_id 关联的区域变体数）,
              process_count（cultural_processes.origin/destination_region =
              本系统关联区域名）,
              flow_count（cultural_flows.origin/destination 同上）,
              children（仅 tree 内）。
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT s.system_id, s.system_name, s.system_level, s.parent_system,
                   s.description, r.region_id, r.region_name,
                   (SELECT count(*) FROM system_memberships m
                     WHERE m.system_id = s.system_id) AS membership_count,
                   (SELECT count(*) FROM tradition_variants tv
                     WHERE tv.system_id = s.system_id) AS tradition_count,
                   (SELECT count(*) FROM cultural_processes p
                     WHERE r.region_name IS NOT NULL
                       AND (p.origin_region = r.region_name
                            OR p.destination_region = r.region_name)) AS process_count,
                   (SELECT count(*) FROM cultural_flows f
                     WHERE r.region_name IS NOT NULL
                       AND (f.origin = r.region_name
                            OR f.destination = r.region_name)) AS flow_count
            FROM cultural_systems s
            LEFT JOIN cultural_regions r ON r.region_id = s.region_id
            ORDER BY s.created_at, s.system_name""")
        rows = [_jsonable(r) for r in cur.fetchall()]
    by_id: dict[str, dict] = {}
    for row in rows:
        row["region"] = ({"region_id": row.pop("region_id"),
                          "region_name": row.pop("region_name")}
                         if row.get("region_id") else None)
        row["children"] = []
        by_id[row["system_id"]] = row
    tree = []
    for row in rows:
        parent = by_id.get(row.get("parent_system"))
        (parent["children"] if parent else tree).append(row)
    keys = ("membership_count", "tradition_count", "process_count", "flow_count")
    totals = {k: int(sum(int(r.get(k) or 0) for r in rows)) for k in keys}
    items = [{k: v for k, v in r.items() if k != "children"} for r in rows]
    return {"total": len(rows), "items": items, "tree": tree, "totals": totals}


# ----------------------------------------------------------------------
# 2. GET /yangtze/v2/regions — 文化区域
# ----------------------------------------------------------------------

@router.get("/regions")
@_guarded
def regions():
    """文化区域列表（含省份、水系基础与关联系统）。

    返回：{total, items: [{region_id, region_name, parent_region, provinces,
           hydro_basis, description, system_count,
           systems: [{system_id, system_name, system_level}]}]}
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT r.region_id, r.region_name, r.parent_region, r.provinces,
                   r.hydro_basis, r.description,
                   (SELECT count(*) FROM cultural_systems s
                     WHERE s.region_id = r.region_id) AS system_count
            FROM cultural_regions r
            ORDER BY r.created_at, r.region_name""")
        items = [_jsonable(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT s.system_id, s.system_name, s.system_level, s.region_id
            FROM cultural_systems s
            WHERE s.region_id IS NOT NULL
            ORDER BY s.created_at""")
        systems = [_jsonable(r) for r in cur.fetchall()]
    by_region: dict[str, list] = {}
    for s in systems:
        by_region.setdefault(s.pop("region_id"), []).append(s)
    for item in items:
        item["systems"] = by_region.get(item["region_id"], [])
    return {"total": len(items), "items": items}


# ----------------------------------------------------------------------
# 3. GET /yangtze/v2/hydro — 水系单元
# ----------------------------------------------------------------------

@router.get("/hydro")
@_guarded
def hydro(type: str = "", parent: str = "", page: int = 1, page_size: int = PAGE_SIZE_DEFAULT):
    """水系空间单元列表（支持 ?type=&parent= 过滤 + 分页）。

    查询参数：type（hsu_type 精确匹配，如 Basin/MainStem/Tributary），
              parent（父单元名称精确匹配，如 长江干流），page/page_size。
    返回：{total, page, page_size,
           items: [{hsu_id, hsu_name, hsu_type, parent_hsu, parent_name,
                    province, description, relation_count}]}
    relation_count = hydro_spatial_relations 中以该单元为 from 或 to 的边数。
    """
    page, page_size = _clamp_page(page, page_size)
    where = """WHERE (COALESCE(%s,'')='' OR u.hsu_type=%s)
               AND (COALESCE(%s,'')='' OR p.hsu_name=%s)"""
    params = (type, type, parent, parent)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS total FROM hydro_spatial_units u "
                    f"LEFT JOIN hydro_spatial_units p ON p.hsu_id = u.parent_hsu {where}",
                    params)
        total = int(cur.fetchone()["total"])
        cur.execute(f"""
            SELECT u.hsu_id, u.hsu_name, u.hsu_type, u.parent_hsu,
                   p.hsu_name AS parent_name, u.province, u.description,
                   (SELECT count(*) FROM hydro_spatial_relations r
                     WHERE r.from_hsu = u.hsu_id OR r.to_hsu = u.hsu_id) AS relation_count
            FROM hydro_spatial_units u
            LEFT JOIN hydro_spatial_units p ON p.hsu_id = u.parent_hsu
            {where}
            ORDER BY u.created_at, u.hsu_name
            LIMIT %s OFFSET %s""",
            params + (page_size, (page - 1) * page_size))
        items = [_jsonable(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ----------------------------------------------------------------------
# 4. GET /yangtze/v2/domains — 领域树
# ----------------------------------------------------------------------

@router.get("/domains")
@_guarded
def domains():
    """文化领域树（父子嵌套，一次返回全树）。

    返回：{total: 全部领域数, tree: [{domain_id, domain_name, description,
           children: [嵌套子领域]}]}
    父域缺失的孤儿节点按根处理，保证全部领域可见。
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT domain_id, domain_name, parent_domain, description
                       FROM cultural_domains ORDER BY created_at, domain_name""")
        rows = [_jsonable(r) for r in cur.fetchall()]
    by_id: dict[str, dict] = {}
    for row in rows:
        row["children"] = []
        by_id[row["domain_id"]] = row
    tree = []
    for row in rows:
        parent = by_id.get(row.get("parent_domain"))
        (parent["children"] if parent else tree).append(row)
    return {"total": len(rows), "tree": tree}


# ----------------------------------------------------------------------
# 5. GET /yangtze/v2/timeline — 13 历史分期
# ----------------------------------------------------------------------

@router.get("/timeline")
@_guarded
def timeline():
    """13 历史分期（按 seed YAML 顺序：史前时期→…→新时代）。

    返回：{total, items: [{phase_id, phase_name, macro_phase, start_year,
           end_year, approximate, description, process_count, tradition_count,
           patterns: [{pattern_id, pattern_code, pattern_name, note}]}]}
    process_count = cultural_processes.historical_phase 直挂该分期数；
    tradition_count = 传统 origin/historical_development 文本提及该分期名的
    弱链接计数（cultural_traditions 无分期外键）；
    patterns 来自 historical_phase_patterns × macro_evolution_patterns 多对多。
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT p.phase_id, p.phase_name, p.macro_phase, p.start_year, p.end_year,
                   p.approximate, p.description,
                   (SELECT count(*) FROM cultural_processes cp
                     WHERE cp.historical_phase = p.phase_id) AS process_count,
                   (SELECT count(*) FROM cultural_traditions ct
                     WHERE ct.origin ILIKE '%%'||p.phase_name||'%%'
                        OR ct.historical_development ILIKE '%%'||p.phase_name||'%%'
                     ) AS tradition_count
            FROM historical_phases p
            ORDER BY p.created_at, p.phase_name""")
        rows = [_jsonable(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT hpp.phase_id, mep.pattern_id, mep.pattern_code,
                   mep.pattern_name, hpp.note
            FROM historical_phase_patterns hpp
            JOIN macro_evolution_patterns mep ON mep.pattern_id = hpp.pattern_id
            ORDER BY mep.created_at, mep.pattern_code""")
        links = [_jsonable(r) for r in cur.fetchall()]
    by_phase: dict[str, list] = {}
    for link in links:
        by_phase.setdefault(link.pop("phase_id"), []).append(link)
    for row in rows:
        row["patterns"] = by_phase.get(row["phase_id"], [])
    rows = _sort_phases_yaml(rows)
    return {"total": len(rows), "items": rows}


# ----------------------------------------------------------------------
# 6. GET /yangtze/v2/traditions — 文化传统
# ----------------------------------------------------------------------

@router.get("/traditions")
@_guarded
def traditions(status: str = "", domain_id: str = "", q: str = "",
               page: int = 1, page_size: int = PAGE_SIZE_DEFAULT):
    """文化传统列表（?status=&domain_id=&q= 过滤 + 分页）。

    q 对 tradition_name / description / origin 做 ILIKE 包含匹配；
    domain_id 按字符串比较（非法值静默返回空集，不报 500）。
    返回：{total, page, page_size,
           items: [{tradition_id, tradition_name, domain_id, domain_name,
                    origin, historical_development, description, status,
                    confidence, created_at}]}
    """
    page, page_size = _clamp_page(page, page_size)
    where = """WHERE (COALESCE(%s,'')='' OR t.status=%s)
               AND (COALESCE(%s,'')='' OR t.domain_id::text=%s)
               AND (COALESCE(%s,'')='' OR t.tradition_name ILIKE '%%'||%s||'%%'
                    OR t.description ILIKE '%%'||%s||'%%'
                    OR t.origin ILIKE '%%'||%s||'%%')"""
    params = (status, status, domain_id, domain_id, q, q, q, q)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS total FROM cultural_traditions t {where}", params)
        total = int(cur.fetchone()["total"])
        cur.execute(f"""
            SELECT t.tradition_id, t.tradition_name, t.domain_id,
                   d.domain_name, t.origin, t.historical_development,
                   t.description, t.status, t.confidence, t.created_at
            FROM cultural_traditions t
            LEFT JOIN cultural_domains d ON d.domain_id = t.domain_id
            {where}
            ORDER BY t.created_at, t.tradition_name
            LIMIT %s OFFSET %s""",
            params + (page_size, (page - 1) * page_size))
        items = [_jsonable(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ----------------------------------------------------------------------
# 7. GET /yangtze/v2/processes — 文化过程
# ----------------------------------------------------------------------

@router.get("/processes")
@_guarded
def processes(status: str = "", process_type: str = "", q: str = "",
              page: int = 1, page_size: int = PAGE_SIZE_DEFAULT):
    """文化过程列表（?status=&process_type=&q= 过滤 + 分页）。

    q 对 process_name / description 做 ILIKE 包含匹配。
    返回：{total, page, page_size,
           items: [{process_id, process_name, process_type, status, confidence,
                    start_time, end_time, phase_id, phase_name,
                    origin_region, destination_region, evidence_count,
                    stage_count, created_at}]}
    stage_count = process_stages 中该过程的阶段数。
    """
    page, page_size = _clamp_page(page, page_size)
    where = """WHERE (COALESCE(%s,'')='' OR p.status=%s)
               AND (COALESCE(%s,'')='' OR p.process_type=%s)
               AND (COALESCE(%s,'')='' OR p.process_name ILIKE '%%'||%s||'%%'
                    OR p.description ILIKE '%%'||%s||'%%')"""
    params = (status, status, process_type, process_type, q, q, q)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS total FROM cultural_processes p {where}", params)
        total = int(cur.fetchone()["total"])
        cur.execute(f"""
            SELECT p.process_id, p.process_name, p.process_type, p.status,
                   p.confidence, p.start_time, p.end_time,
                   p.historical_phase AS phase_id, hp.phase_name,
                   p.origin_region, p.destination_region, p.evidence_count,
                   (SELECT count(*) FROM process_stages st
                     WHERE st.process_id = p.process_id) AS stage_count,
                   p.created_at
            FROM cultural_processes p
            LEFT JOIN historical_phases hp ON hp.phase_id = p.historical_phase
            {where}
            ORDER BY p.created_at, p.process_name
            LIMIT %s OFFSET %s""",
            params + (page_size, (page - 1) * page_size))
        items = [_jsonable(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ----------------------------------------------------------------------
# 8. GET /yangtze/v2/flows — 文化流动
# ----------------------------------------------------------------------

@router.get("/flows")
@_guarded
def flows(flow_type: str = "", q: str = "",
          page: int = 1, page_size: int = PAGE_SIZE_DEFAULT):
    """文化流动列表（?flow_type=&q= 过滤 + 分页）。

    q 对 content / carrier / origin / destination 做 ILIKE 包含匹配。
    返回：{total, page, page_size,
           items: [{flow_id, process_id, flow_type, origin, destination, via,
                    time_range, carrier, content, created_at}]}
    """
    page, page_size = _clamp_page(page, page_size)
    where = """WHERE (COALESCE(%s,'')='' OR f.flow_type=%s)
               AND (COALESCE(%s,'')='' OR f.content ILIKE '%%'||%s||'%%'
                    OR f.carrier ILIKE '%%'||%s||'%%'
                    OR f.origin ILIKE '%%'||%s||'%%'
                    OR f.destination ILIKE '%%'||%s||'%%')"""
    params = (flow_type, flow_type, q, q, q, q, q)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS total FROM cultural_flows f {where}", params)
        total = int(cur.fetchone()["total"])
        cur.execute(f"""
            SELECT f.flow_id, f.process_id, f.flow_type, f.origin, f.destination,
                   f.via, f.time_range, f.carrier, f.content, f.created_at
            FROM cultural_flows f
            {where}
            ORDER BY f.created_at
            LIMIT %s OFFSET %s""",
            params + (page_size, (page - 1) * page_size))
        items = [_jsonable(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ----------------------------------------------------------------------
# 9. GET /yangtze/v2/networks — 结构网络概览
# ----------------------------------------------------------------------

@router.get("/networks")
@_guarded
def networks():
    """结构关系（structural_relations）网络概览。

    返回：{total, by_predicate: [{predicate, total, ontology_count,
           evidence_backed_count, admitted_count, candidate_count}],
           by_knowledge_type: {"ONTOLOGY_RELATION": n, "EVIDENCE_BACKED": n,
                               "UNKNOWN": n}}
    knowledge_type 未标注的行计入 UNKNOWN。
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT predicate, count(*) AS total,
                   count(*) FILTER (WHERE knowledge_type = 'ONTOLOGY_RELATION') AS ontology_count,
                   count(*) FILTER (WHERE knowledge_type = 'EVIDENCE_BACKED') AS evidence_backed_count,
                   count(*) FILTER (WHERE status = 'ADMITTED') AS admitted_count,
                   count(*) FILTER (WHERE status = 'CANDIDATE') AS candidate_count
            FROM structural_relations
            GROUP BY predicate
            ORDER BY count(*) DESC, predicate""")
        by_predicate = [_jsonable(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT COALESCE(knowledge_type, 'UNKNOWN') AS knowledge_type, count(*)
            FROM structural_relations GROUP BY 1 ORDER BY 2 DESC""")
        by_knowledge_type = {r["knowledge_type"]: int(r["count"]) for r in cur.fetchall()}
    total = int(sum(r["total"] for r in by_predicate))
    return {"total": total, "by_predicate": by_predicate,
            "by_knowledge_type": by_knowledge_type}


# ----------------------------------------------------------------------
# 10. GET /yangtze/v2/evolution — 分期 × 演化模式矩阵
# ----------------------------------------------------------------------

@router.get("/evolution")
@_guarded
def evolution():
    """分期 × 宏观演化模式矩阵（13 行 × 模式列，多对多）。

    返回：{phases: [分期名（YAML 顺序）],
           patterns: [{pattern_id, pattern_code, pattern_name, description,
                       phase_count}],
           matrix: [{phase_id, phase_name,
                     patterns: [{pattern_id, pattern_code, pattern_name, note}]}]}
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT phase_id, phase_name FROM historical_phases
                       ORDER BY created_at, phase_name""")
        phases = [_jsonable(r) for r in cur.fetchall()]
        cur.execute("""SELECT pattern_id, pattern_code, pattern_name, description
                       FROM macro_evolution_patterns
                       ORDER BY created_at, pattern_code""")
        patterns = [_jsonable(r) for r in cur.fetchall()]
        cur.execute("""SELECT hpp.phase_id, hpp.pattern_id, hpp.note
                       FROM historical_phase_patterns hpp""")
        links = [_jsonable(r) for r in cur.fetchall()]
    phases = _sort_phases_yaml(phases)
    code_map = {p["pattern_id"]: p["pattern_code"] for p in patterns}
    name_map = {p["pattern_id"]: p["pattern_name"] for p in patterns}
    by_phase: dict[str, list] = {}
    for link in links:
        by_phase.setdefault(link["phase_id"], []).append({
            "pattern_id": link["pattern_id"],
            "pattern_code": code_map.get(link["pattern_id"]),
            "pattern_name": name_map.get(link["pattern_id"]),
            "note": link.get("note"),
        })
    matrix = [{"phase_id": ph["phase_id"], "phase_name": ph["phase_name"],
               "patterns": by_phase.get(ph["phase_id"], [])} for ph in phases]
    phase_count_by_pattern: dict[str, int] = {}
    for link in links:
        phase_count_by_pattern[link["pattern_id"]] = \
            phase_count_by_pattern.get(link["pattern_id"], 0) + 1
    for p in patterns:
        p["phase_count"] = int(phase_count_by_pattern.get(p["pattern_id"], 0))
    return {"phases": [ph["phase_name"] for ph in phases],
            "patterns": patterns, "matrix": matrix}


# ----------------------------------------------------------------------
# 11. GET /yangtze/v2/structure — 受控骨架总览
# ----------------------------------------------------------------------

@router.get("/structure")
@_guarded
def structure():
    """受控骨架总览：各受控表行数 + manifest 校验状态（轻量模式）。

    返回：{counts: {systems, regions, domains, phases, evolution_patterns,
           phase_pattern_links, hydro_units, hydro_relations, memberships,
           structural_relations, traditions, processes, flows, gaps,
           interpretations, structural_admissions},
           manifest: {mode: "counts_only", verified: false,
           note: 完整校验需运行 tools/init_canonical_v2.py --verify}}
    轻量模式只统计行数，不加载 seed manifest（避免重逻辑进请求路径）。
    """
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT (SELECT count(*) FROM cultural_systems) AS systems,
                   (SELECT count(*) FROM cultural_regions) AS regions,
                   (SELECT count(*) FROM cultural_domains) AS domains,
                   (SELECT count(*) FROM historical_phases) AS phases,
                   (SELECT count(*) FROM macro_evolution_patterns) AS evolution_patterns,
                   (SELECT count(*) FROM historical_phase_patterns) AS phase_pattern_links,
                   (SELECT count(*) FROM hydro_spatial_units) AS hydro_units,
                   (SELECT count(*) FROM hydro_spatial_relations) AS hydro_relations,
                   (SELECT count(*) FROM system_memberships) AS memberships,
                   (SELECT count(*) FROM structural_relations) AS structural_relations,
                   (SELECT count(*) FROM cultural_traditions) AS traditions,
                   (SELECT count(*) FROM cultural_processes) AS processes,
                   (SELECT count(*) FROM cultural_flows) AS flows,
                   (SELECT count(*) FROM structural_gaps) AS gaps,
                   (SELECT count(*) FROM interpretations) AS interpretations,
                   (SELECT count(*) FROM structural_admissions) AS structural_admissions""")
        counts = {k: int(v) for k, v in dict(cur.fetchone()).items()}
    return {"counts": counts,
            "manifest": {"mode": "counts_only", "verified": False,
                         "note": "counts-only 轻量校验；完整 manifest 校验请运行 "
                                 "python tools/init_canonical_v2.py --verify"}}


# ----------------------------------------------------------------------
# 12. GET /yangtze/v2/gaps — 结构缺口
# ----------------------------------------------------------------------

@router.get("/gaps")
@_guarded
def gaps(status: str = "", gap_type: str = "",
         page: int = 1, page_size: int = PAGE_SIZE_DEFAULT):
    """结构缺口 / 研究任务列表（?status=&gap_type= 过滤 + 分页）。

    返回：{total, page, page_size,
           items: [{gap_id, gap_type, target_entity, target_system,
                    target_region, target_period, target_domain, priority,
                    status, created_at}]}
    """
    page, page_size = _clamp_page(page, page_size)
    where = """WHERE (COALESCE(%s,'')='' OR g.status=%s)
               AND (COALESCE(%s,'')='' OR g.gap_type=%s)"""
    params = (status, status, gap_type, gap_type)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS total FROM structural_gaps g {where}", params)
        total = int(cur.fetchone()["total"])
        cur.execute(f"""
            SELECT g.gap_id, g.gap_type, g.target_entity, g.target_system,
                   g.target_region, g.target_period, g.target_domain,
                   g.priority, g.status, g.created_at
            FROM structural_gaps g
            {where}
            ORDER BY g.priority DESC, g.created_at DESC
            LIMIT %s OFFSET %s""",
            params + (page_size, (page - 1) * page_size))
        items = [_jsonable(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ----------------------------------------------------------------------
# 13. GET /yangtze/v2/why-yangtze — 解释路径
# ----------------------------------------------------------------------

@router.get("/why-yangtze")
@_guarded
def why_yangtze(entity_name: str = ""):
    """解释路径：实体 → system_memberships → 文化系统 → 区域/水系 → 长江文化。

    查询参数：entity_name（必填；先精确匹配 canonical_name，再查 entity_aliases
    别名，最后 canonical_name ILIKE 包含匹配）。
    返回：{entity: {entity_id, canonical_name, entity_type}, target: 根系统名,
           path_count, paths: [{membership_id, membership_role, status, steps}],
           explanation}
    每个 step = {from: {kind, id?, name?}, to: {kind, ...}, relation,
                 evidence_id}（evidence_id 取 membership.evidence_id /
                 supporting_evidence_ids[0]，缺省为 null 占位）。
    实体不存在 → 404 {"detail": "entity not found: X"}；
    实体存在但无结构锚点 → 200 paths=[] + explanation。
    """
    name = (entity_name or "").strip()
    if not name:
        return JSONResponse({"detail": "entity_name query parameter is required"},
                            status_code=400)
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT entity_id, canonical_name, entity_type
                       FROM canonical_entities WHERE canonical_name = %s LIMIT 1""", (name,))
        entity = cur.fetchone()
        if not entity:
            cur.execute("""SELECT e.entity_id, e.canonical_name, e.entity_type
                           FROM entity_aliases a
                           JOIN canonical_entities e ON e.entity_id = a.entity_id
                           WHERE a.alias = %s LIMIT 1""", (name,))
            entity = cur.fetchone()
        if not entity:
            cur.execute("""SELECT entity_id, canonical_name, entity_type
                           FROM canonical_entities
                           WHERE canonical_name ILIKE '%%'||%s||'%%' LIMIT 1""", (name,))
            entity = cur.fetchone()
        if not entity:
            return JSONResponse({"detail": f"entity not found: {name}"}, status_code=404)
        entity_id = entity["entity_id"]

        cur.execute("""SELECT system_name FROM cultural_systems
                       WHERE system_level = 'ROOT' ORDER BY created_at LIMIT 1""")
        root_row = cur.fetchone()
        target_name = root_row["system_name"] if root_row else "长江文化"

        cur.execute("""
            SELECT m.membership_id, m.membership_role, m.status AS membership_status,
                   m.evidence_id, m.supporting_evidence_ids,
                   s.system_id, s.system_name, s.system_level,
                   ps.system_id AS parent_system_id, ps.system_name AS parent_system_name,
                   r.region_id, r.region_name, r.hydro_basis
            FROM system_memberships m
            JOIN cultural_systems s ON s.system_id = m.system_id
            LEFT JOIN cultural_systems ps ON ps.system_id = s.parent_system
            LEFT JOIN cultural_regions r ON r.region_id = s.region_id
            WHERE m.object_id = %s
            ORDER BY m.created_at""", (entity_id,))
        memberships = [_jsonable(r) for r in cur.fetchall()]

    entity_out = _jsonable(dict(entity))
    paths = []
    for m in memberships:
        evidence = m.get("evidence_id")
        if not evidence:
            supporting = m.get("supporting_evidence_ids") or []
            evidence = supporting[0] if supporting else None
        steps = [
            {"from": {"kind": "entity", "id": entity_out["entity_id"],
                      "name": entity_out["canonical_name"]},
             "to": {"kind": "membership", "id": m["membership_id"],
                    "role": m["membership_role"]},
             "relation": "has_system_membership", "evidence_id": evidence},
            {"from": {"kind": "membership", "id": m["membership_id"]},
             "to": {"kind": "system", "id": m["system_id"],
                    "name": m["system_name"]},
             "relation": "member_of_system", "evidence_id": evidence},
        ]
        if m.get("parent_system_id"):
            steps.append({
                "from": {"kind": "system", "id": m["system_id"],
                         "name": m["system_name"]},
                "to": {"kind": "system", "id": m["parent_system_id"],
                       "name": m["parent_system_name"]},
                "relation": "child_system_of", "evidence_id": None})
        if m.get("region_id"):
            steps.append({
                "from": {"kind": "system", "id": m["system_id"],
                         "name": m["system_name"]},
                "to": {"kind": "region", "id": m["region_id"],
                       "name": m["region_name"]},
                "relation": "anchored_to_region", "evidence_id": None})
            if m.get("hydro_basis"):
                steps.append({
                    "from": {"kind": "region", "id": m["region_id"],
                             "name": m["region_name"]},
                    "to": {"kind": "hydro", "names": m["hydro_basis"]},
                    "relation": "has_hydro_basis", "evidence_id": None})
        steps.append({
            "from": {"kind": "system",
                     "id": m["parent_system_id"] or m["system_id"],
                     "name": m["parent_system_name"] or m["system_name"]},
            "to": {"kind": "system", "name": target_name},
            "relation": "constitutes_root_culture", "evidence_id": None})
        paths.append({"membership_id": m["membership_id"],
                      "membership_role": m["membership_role"],
                      "status": m["membership_status"], "steps": steps})

    if paths:
        explanation = (f"{name} 通过 {len(paths)} 条 system_memberships 结构锚点"
                       f"接入受控文化系统树，最终归入『{target_name}』。")
    else:
        explanation = (f"{name} 存在于 canonical 实体层，但尚无 system_memberships "
                       f"结构锚点（等待 membership 重建管线推导），"
                       f"因此无法给出到『{target_name}』的结构路径。")
    return {"entity": entity_out, "target": target_name,
            "path_count": len(paths), "paths": paths, "explanation": explanation}
