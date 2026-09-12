#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_v2_ontology.py — canonical_v2 本体验证器（goal §10.3 / G02）。

验证对象分两层：
  A. Git seed manifest（yangtze/schema/*.yaml）
  B. 运行库受控表（cultural_systems / cultural_regions / cultural_domains /
     historical_phases / macro_evolution_patterns / historical_phase_patterns /
     hydro_spatial_units / hydro_spatial_relations）

检查项（任一 ERROR → exit 1）：
  type_collision      同一名称在受控层不同类型对象间冲突（§10.1/§10.2）
  cycle               受控父子链成环（系统/领域/分期/水系）
  dangling_parent     parent 指向不存在的对象
  duplicate_id        manifest 内 id 重复
  duplicate_name      同表内名称重复
  illegal_child_type  领域树下出现事件/实体语义的子域（§10.2 黑名单扫描）
  missing_metadata    必填元数据缺失（描述/类型/分期锚）
  narrative_leak      受控本体混入历史叙事表达（§12）
  hydro_topology      自环 / 支流环 / 非法谓词（§16.3）

用法：
  python tools/validate_v2_ontology.py            # seed + 运行库全量验证
  python tools/validate_v2_ontology.py --seed-only
  python tools/validate_v2_ontology.py --json     # 机器可读输出
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import psycopg2
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "yangtze" / "schema"

# §10.2：这些是事件/工程/复合概念，不得作为 CulturalDomain 出现
DOMAIN_BLACKLIST = {
    "辛亥革命", "大革命", "土地革命", "解放战争", "抗战文化",
    "三线建设", "工业遗产", "洋务企业", "民族工业", "战时工业",
    "长三角文化", "长江文化", "巴蜀文化", "荆楚文化", "湖湘文化",
    "吴越文化", "赣鄱文化", "徽州文化", "羌藏文化", "滇黔文化",
}
# §12：受控本体只能保存稳定定义，历史判断进入 Interpretation 层
NARRATIVE_PATTERN = re.compile(
    r"(连续体|发展为|演化为|融合为|源自|起源于|从.{1,12}到.{1,12}|影响并|促进了)"
)


class Finding:
    def __init__(self, level: str, code: str, where: str, detail: str):
        self.level, self.code, self.where, self.detail = level, code, where, detail

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "where": self.where, "detail": self.detail}


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _walk_cycles(graph: dict[str, str | None]) -> list[str]:
    """graph: child -> parent。返回所有处于环上的节点。"""
    color: dict[str, int] = {}
    cyc: list[str] = []

    def visit(n: str) -> None:
        color[n] = 1
        p = graph.get(n)
        if p and p in graph:
            c = color.get(p, 0)
            if c == 1:
                cyc.append(n)
            elif c == 0:
                visit(p)
        color[n] = 2

    for n in graph:
        if color.get(n, 0) == 0:
            visit(n)
    return cyc


def validate_seed() -> list[Finding]:
    out: list[Finding] = []
    systems = _yaml("cultural_systems.yaml").get("systems") or []
    regions = _yaml("cultural_regions.yaml").get("regions") or []
    domains = _yaml("cultural_domains.yaml").get("domains") or []
    phases = _yaml("historical_phases.yaml").get("phases") or []
    patterns = _yaml("macro_evolution_patterns.yaml").get("patterns") or []
    hydro = _yaml("hydro_spatial.yaml")

    # duplicate id / name
    for label, items, key in [
        ("cultural_systems.yaml", systems, "id"),
        ("cultural_regions.yaml", regions, "name"),
        ("historical_phases.yaml", phases, "id"),
        ("macro_evolution_patterns.yaml", patterns, "code"),
    ]:
        seen: dict[Any, int] = {}
        for it in items:
            seen[it.get(key)] = seen.get(it.get(key), 0) + 1
        for k, n in seen.items():
            if n > 1:
                out.append(Finding("ERROR", "duplicate_id", label, f"{key}={k} 出现 {n} 次"))

    # 领域展开 + duplicate_name + illegal_child_type + missing_metadata
    dom_names: list[str] = []
    for d in domains:
        if not d.get("name") or not d.get("id"):
            out.append(Finding("ERROR", "missing_metadata", "cultural_domains.yaml",
                               f"顶层领域缺 id/name: {d}"))
        dom_names.append(d["name"])
        for c in d.get("children") or []:
            dom_names.append(c)
            if c in DOMAIN_BLACKLIST:
                out.append(Finding("ERROR", "illegal_child_type", "cultural_domains.yaml",
                                   f"「{c}」是事件/工程/复合概念，不得作为 CulturalDomain child（§10.2）"))
        if NARRATIVE_PATTERN.search(d.get("name", "") or ""):
            out.append(Finding("ERROR", "narrative_leak", "cultural_domains.yaml", d["name"]))
    dup: dict[str, int] = {}
    for n in dom_names:
        dup[n] = dup.get(n, 0) + 1
    for n, c in dup.items():
        if c > 1:
            out.append(Finding("ERROR", "duplicate_name", "cultural_domains.yaml",
                               f"领域名「{n}」出现 {c} 次"))

    # type_collision：同一名称跨受控类型
    sys_names = {s["name"] for s in systems}
    reg_names = {r["name"] for r in regions}
    phase_names = {p["name"] for p in phases}
    for n in sys_names & reg_names:
        out.append(Finding("ERROR", "type_collision", "seed",
                           f"「{n}」同时是 CulturalSystem 与 CulturalRegion（§10.1）"))
    for n in sys_names & phase_names:
        out.append(Finding("ERROR", "type_collision", "seed",
                           f"「{n}」同时是 CulturalSystem 与 HistoricalPhase"))

    # dangling parent / cycle：系统与分期
    id2name_sys = {s["id"]: s["name"] for s in systems}
    sys_parent = {s["name"]: (id2name_sys.get(s.get("parent")) if s.get("parent") else None)
                  for s in systems}
    for s in systems:
        if s.get("parent") and s["parent"] not in id2name_sys:
            out.append(Finding("ERROR", "dangling_parent", "cultural_systems.yaml",
                               f"{s['name']} → {s['parent']}"))
    for n in _walk_cycles(sys_parent):
        out.append(Finding("ERROR", "cycle", "cultural_systems.yaml", n))
    for s in systems:
        if not (s.get("description") or "").strip():
            out.append(Finding("ERROR", "missing_metadata", "cultural_systems.yaml",
                               f"{s['name']} 缺 description"))

    ph_names = {p["name"] for p in phases}
    ph_parent = {}
    for p in phases:
        par = p.get("parent")
        if par and par not in ph_names:
            out.append(Finding("ERROR", "dangling_parent", "historical_phases.yaml",
                               f"{p['name']} → {par}"))
        ph_parent[p["name"]] = par if par in ph_names else None
        if not p.get("macro_phase"):
            out.append(Finding("ERROR", "missing_metadata", "historical_phases.yaml",
                               f"{p['name']} 缺 macro_phase 锚"))
    for n in _walk_cycles(ph_parent):
        out.append(Finding("ERROR", "cycle", "historical_phases.yaml", n))

    # 区域 missing_metadata + 指向合法系统
    for r in regions:
        if not (r.get("description") or "").strip() or not (r.get("provinces") or []):
            out.append(Finding("ERROR", "missing_metadata", "cultural_regions.yaml",
                               f"{r['name']} 缺 description/provinces"))
        if r.get("system") and r["system"] not in sys_names:
            out.append(Finding("ERROR", "dangling_parent", "cultural_regions.yaml",
                               f"{r['name']} → system {r['system']}"))

    # hydro：缺引用、非法谓词、自环、支流环
    units = hydro.get("units") or []
    unit_names: dict[str, int] = {}
    for u in units:
        unit_names[u["name"]] = unit_names.get(u["name"], 0) + 1
        if not (u.get("description") or "").strip() or not u.get("type"):
            out.append(Finding("ERROR", "missing_metadata", "hydro_spatial.yaml",
                               f"{u.get('name')} 缺 type/description"))
    for n, c in unit_names.items():
        if c > 1:
            out.append(Finding("ERROR", "duplicate_name", "hydro_spatial.yaml",
                               f"单元「{n}」出现 {c} 次"))
    valid_types = {"Basin", "MainStem", "RiverSection", "Tributary", "Lake", "Wetland",
                   "Delta", "Plain", "MountainRegion", "Valley", "SubBasin",
                   "WaterTransportCorridor"}
    valid_rels = {"tributary_of", "flows_into", "part_of_basin", "upstream_of",
                  "downstream_of", "hydrologically_connects", "passes_through",
                  "adjacent_basin"}
    for u in units:
        if u.get("type") not in valid_types:
            out.append(Finding("ERROR", "illegal_child_type", "hydro_spatial.yaml",
                               f"{u['name']} 非法类型 {u.get('type')}"))
        par = u.get("parent")
        if par and par not in unit_names:
            out.append(Finding("ERROR", "dangling_parent", "hydro_spatial.yaml",
                               f"{u['name']} → {par}"))
    hy_parent = {u["name"]: (u.get("parent") if u.get("parent") in unit_names else None)
                 for u in units}
    for n in _walk_cycles(hy_parent):
        out.append(Finding("ERROR", "cycle", "hydro_spatial.yaml", f"parent链: {n}"))
    tri_set: set[tuple[str, str, str]] = set()
    for rel in hydro.get("relations") or []:
        t = (rel["from"], rel["relation"], rel["to"])
        if rel["relation"] not in valid_rels:
            out.append(Finding("ERROR", "illegal_child_type", "hydro_spatial.yaml",
                               f"非法水系谓词 {t}"))
        if t[0] == t[2]:
            out.append(Finding("ERROR", "hydro_topology", "hydro_spatial.yaml", f"自环 {t}"))
        if t in tri_set:
            out.append(Finding("ERROR", "duplicate_name", "hydro_spatial.yaml", f"重复三元组 {t}"))
        tri_set.add(t)
        for side in (t[0], t[2]):
            if side not in unit_names:
                out.append(Finding("ERROR", "dangling_parent", "hydro_spatial.yaml",
                                   f"{t} 引用未定义单元 {side}"))
    # tributary_of 子图无环（把 tributary_of/fl flows_into 当有向边查环）
    flow_graph: dict[str, str] = {}
    for f, rel, to in tri_set:
        if rel in ("tributary_of", "flows_into"):
            flow_graph[f] = to
    for n in _walk_cycles(flow_graph):
        out.append(Finding("ERROR", "hydro_topology", "hydro_spatial.yaml", f"汇流环: {n}"))
    # 受控单元不悬空：每单元至少一条关系（§16.3 dangling unit = 0）
    touched: set[str] = set()
    for f, _, to in tri_set:
        touched.add(f)
        touched.add(to)
    for n in unit_names:
        if n not in touched:
            out.append(Finding("ERROR", "hydro_topology", "hydro_spatial.yaml",
                               f"悬空受控单元（无任何关系）: {n}"))

    # 演化模式被分期引用检查
    codes = {p["code"] for p in patterns}
    for p in phases:
        mp = p.get("macro_phase")
        need = mp if isinstance(mp, list) else ([mp] if mp else [])
        for c in need:
            if c not in codes:
                out.append(Finding("ERROR", "dangling_parent", "historical_phases.yaml",
                                   f"{p['name']} 引用未定义模式 {c}"))
    return out


def validate_db() -> list[Finding]:
    out: list[Finding] = []
    sys.path.insert(0, str(ROOT))
    try:
        from config.settings import SETTINGS  # type: ignore
        dsn = SETTINGS.pg_dsn
    except Exception:
        dsn = "host=127.0.0.1 port=5433 dbname=ycki user=postgres password=ycki_pg_2026"
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            # DB 侧重名（种子唯一性在 DB 未必有约束的全部表）
            for table, col in [("cultural_domains", "domain_name"),
                               ("historical_phases", "phase_name"),
                               ("hydro_spatial_units", "hsu_name")]:
                cur.execute(f"SELECT {col}, count(*) FROM {table} GROUP BY 1 HAVING count(*)>1")
                for n, c in cur.fetchall():
                    out.append(Finding("ERROR", "duplicate_name", f"db.{table}", f"{n} ×{c}"))
            # 父链环（DB）
            cur.execute("SELECT d.domain_name, p.domain_name FROM cultural_domains d "
                        "LEFT JOIN cultural_domains p ON d.parent_domain=p.domain_id")
            for n in _walk_cycles({a: b for a, b in cur.fetchall() if a and b}):
                out.append(Finding("ERROR", "cycle", "db.cultural_domains", n))
            cur.execute("SELECT u.hsu_name, p.hsu_name FROM hydro_spatial_units u "
                        "LEFT JOIN hydro_spatial_units p ON u.parent_hsu=p.hsu_id")
            for n in _walk_cycles({a: b for a, b in cur.fetchall() if a and b}):
                out.append(Finding("ERROR", "cycle", "db.hydro_spatial_units", n))
            # 水系自环/非法谓词（DB）
            cur.execute("SELECT a.hsu_name, r.relation, b.hsu_name FROM hydro_spatial_relations r "
                        "JOIN hydro_spatial_units a ON r.from_hsu=a.hsu_id "
                        "JOIN hydro_spatial_units b ON r.to_hsu=b.hsu_id")
            for f, rel, t in cur.fetchall():
                if f == t:
                    out.append(Finding("ERROR", "hydro_topology", "db.hydro_spatial_relations",
                                       f"自环 {f}-{rel}-{t}"))
            # domain 挂黑名单（DB 已入库的受控领域名）
            cur.execute("SELECT domain_name FROM cultural_domains")
            for (n,) in cur.fetchall():
                if n in DOMAIN_BLACKLIST:
                    out.append(Finding("ERROR", "illegal_child_type", "db.cultural_domains",
                                       f"「{n}」应属事件/工程概念（§10.2）"))
            # ONTOLOGY 结构关系必须指向受控系统且构成根
            cur.execute(
                "SELECT count(*) FROM structural_relations r "
                "LEFT JOIN cultural_systems s ON r.subject_id=s.system_id "
                "LEFT JOIN cultural_systems o ON r.object_id=o.system_id "
                "WHERE r.knowledge_type='ONTOLOGY_RELATION' AND (s.system_id IS NULL OR o.system_id IS NULL)")
            (bad,) = cur.fetchone()
            if bad:
                out.append(Finding("ERROR", "type_collision", "db.structural_relations",
                                   f"{bad} 条 ONTOLOGY 关系端点不在受控系统表"))
    finally:
        conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    findings = validate_seed()
    if not args.seed_only:
        findings += validate_db()

    errors = [f for f in findings if f.level == "ERROR"]
    warnings = [f for f in findings if f.level == "WARN"]

    if args.json:
        print(json.dumps({
            "errors": [f.as_dict() for f in errors],
            "warnings": [f.as_dict() for f in warnings],
            "error_count": len(errors),
        }, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f.level:5s} {f.code:18s} {f.where}: {f.detail}")
        print(f"\nERROR={len(errors)} WARN={len(warnings)}")
        print("RESULT:", "PASS" if not errors else "FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
