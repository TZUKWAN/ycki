#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_canonical_v2.py — canonical_v2 受控骨架确定性构建器（goal §6/§7/§9）。

受控本体（Controlled Backbone）的唯一写入者。seed 来源全部为 Git 内 YAML：

    yangtze/schema/cultural_systems.yaml      根+七大区域文化系统
    yangtze/schema/cultural_regions.yaml      七大文化区域
    yangtze/schema/cultural_domains.yaml      文化领域树
    yangtze/schema/historical_phases.yaml     13 历史分期 + 演化模式映射
    yangtze/schema/macro_evolution_patterns.yaml  宏观演化模式定义
    yangtze/schema/hydro_spatial.yaml         水系空间骨架（单元+拓扑）

用法：
    python tools/init_canonical_v2.py --dry-run         # 只打印 EXPECTED vs ACTUAL 漂移
    python tools/init_canonical_v2.py --apply           # 单事务构建/修复，失败回滚
    python tools/init_canonical_v2.py --verify          # 校验，漂移非零则 exit 1
    python tools/init_canonical_v2.py --manifest-hash   # 输出 seed manifest SHA256

性质：幂等（重复执行无重复对象）、事务化（任一步失败整体回滚）、
确定性（同一 manifest + 同一初始库状态 → 同一结果）。验收不使用硬编码数量，
EXPECTED 恒等于当前版本 manifest（goal §9）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "yangtze" / "schema"

SEED_FILES = [
    "cultural_systems.yaml",
    "cultural_regions.yaml",
    "cultural_domains.yaml",
    "historical_phases.yaml",
    "macro_evolution_patterns.yaml",
    "hydro_spatial.yaml",
]

ROOT_SYSTEM_NAME = "长江文化"
HYDRO_RELATION_TYPES = {
    "tributary_of", "flows_into", "part_of_basin", "upstream_of",
    "downstream_of", "hydrologically_connects", "passes_through", "adjacent_basin",
}
ONTOLOGY_RELATION_VERSION = "ontology_v2_0"


class BuilderError(RuntimeError):
    """Seed manifest 或数据库状态不合法。"""


@dataclass
class Drift:
    """单个漂移项。"""
    kind: str          # MISSING / UNEXPECTED / MISMATCH / CONSTRAINT
    table: str
    key: str
    detail: str = ""

    def line(self) -> str:
        return f"[{self.kind}] {self.table}: {self.key}" + (f" — {self.detail}" if self.detail else "")


# ----------------------------------------------------------------------
# seed 加载
# ----------------------------------------------------------------------

def _load_yaml(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    if not path.exists():
        raise BuilderError(f"seed 文件缺失: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise BuilderError(f"seed 文件结构非法: {path}")
    return data


@dataclass
class Seed:
    systems: list[dict[str, Any]] = field(default_factory=list)
    regions: list[dict[str, Any]] = field(default_factory=list)
    domains: list[dict[str, Any]] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    phase_patterns: dict[str, list[str]] = field(default_factory=dict)  # phase_name -> [code]
    hydro_units: list[dict[str, Any]] = field(default_factory=list)
    hydro_relations: list[tuple[str, str, str]] = field(default_factory=list)
    # 期望的受控本体结构关系（system_name, predicate, system_name）
    ontology_relations: list[tuple[str, str, str]] = field(default_factory=list)
    manifest_hash: str = ""

    @property
    def system_names(self) -> set[str]:
        return {s["name"] for s in self.systems}

    @property
    def region_names(self) -> set[str]:
        return {r["name"] for r in self.regions}

    @property
    def phase_names(self) -> set[str]:
        return {p["name"] for p in self.phases}


def load_seed() -> Seed:
    sys_y = _load_yaml("cultural_systems.yaml")
    reg_y = _load_yaml("cultural_regions.yaml")
    dom_y = _load_yaml("cultural_domains.yaml")
    ph_y = _load_yaml("historical_phases.yaml")
    pat_y = _load_yaml("macro_evolution_patterns.yaml")
    hy_y = _load_yaml("hydro_spatial.yaml")

    seed = Seed()

    # --- 文化系统：根 + 区域（YAML parent 为 id，解析为名称） ---
    raw_systems = sys_y.get("systems") or []
    id2name = {s["id"]: s["name"] for s in raw_systems}
    for s in raw_systems:
        parent = s.get("parent")
        if parent is not None:
            if parent not in id2name:
                raise BuilderError(f"文化系统 {s['name']} 引用未知 parent id: {parent}")
            parent = id2name[parent]
        seed.systems.append({
            "name": s["name"],
            "level": s.get("level", "REGIONAL"),
            "parent": parent,
            "description": (s.get("description") or "").strip(),
        })
    if not any(s["level"] == "ROOT" for s in seed.systems):
        raise BuilderError("cultural_systems.yaml 缺少 ROOT 系统")

    # --- 文化区域 ---
    for r in reg_y.get("regions") or []:
        seed.regions.append({
            "name": r["name"],
            "legacy_names": list(r.get("legacy_names") or []),
            "provinces": list(r.get("provinces") or []),
            "hydro_basis": list(r.get("hydro_basis") or []),
            "system": r.get("system"),
            "description": (r.get("description") or "").strip(),
        })

    # --- 文化领域：展开为 (name, parent_name|None) ---
    for d in dom_y.get("domains") or []:
        seed.domains.append({"name": d["name"], "parent": None})
        for child in d.get("children") or []:
            seed.domains.append({"name": child, "parent": d["name"]})

    # --- 历史分期：仅顶层分期入库（children 为语义词表提示，非表行） ---
    for p in ph_y.get("phases") or []:
        mp = p.get("macro_phase")
        seed.phases.append({
            "name": p["name"],
            "macro_phase": mp if isinstance(mp, str) else None,
            "description": (p.get("description") or "").strip(),
        })

    # --- 宏观演化模式 + 分期↔模式多对多 ---
    for pat in pat_y.get("patterns") or []:
        seed.patterns.append({
            "code": pat["code"],
            "name": pat["name"],
            "description": (pat.get("description") or "").strip(),
        })
    known_codes = {p["code"] for p in seed.patterns}
    for p in seed.phases:
        mp = p.get("macro_phase")
        if not mp:
            continue
        codes = mp if isinstance(mp, list) else [mp]
        for code in codes:
            if code not in known_codes:
                raise BuilderError(f"分期 {p['name']} 引用未定义的演化模式 {code}")
            seed.phase_patterns.setdefault(p["name"], []).append(code)

    # --- 水系单元与拓扑 ---
    for u in hy_y.get("units") or []:
        seed.hydro_units.append({
            "name": u["name"],
            "type": u["type"],
            "parent": u.get("parent"),
            "provinces": list(u.get("provinces") or []),
            "description": (u.get("description") or "").strip(),
        })
    seen_units: set[tuple[str, str]] = set()
    for u in seed.hydro_units:
        key = (u["name"], u["type"])
        if key in seen_units:
            raise BuilderError(f"水系单元重复定义: {key}")
        seen_units.add(key)
    for rel in hy_y.get("relations") or []:
        triple = (rel["from"], rel["relation"], rel["to"])
        if rel["relation"] not in HYDRO_RELATION_TYPES:
            raise BuilderError(f"非法水系关系谓词: {triple}")
        if triple in seed.hydro_relations:
            raise BuilderError(f"水系关系重复定义: {triple}")
        if rel["from"] == rel["to"]:
            raise BuilderError(f"水系关系自环: {triple}")
        seed.hydro_relations.append(triple)

    # --- 受控本体结构关系：区域系统 constitutes 根系统 ---
    for s in seed.systems:
        if s["level"] == "REGIONAL":
            if s.get("parent") != ROOT_SYSTEM_NAME:
                raise BuilderError(f"区域系统 {s['name']} 的 parent 必须是 {ROOT_SYSTEM_NAME}")
            seed.ontology_relations.append((s["name"], "constitutes", ROOT_SYSTEM_NAME))

    # --- manifest hash：规范化 JSON 的 SHA256 ---
    canon = {
        "systems": sorted(seed.systems, key=lambda x: x["name"]),
        "regions": sorted(seed.regions, key=lambda x: x["name"]),
        "domains": sorted((d["name"], d["parent"]) for d in seed.domains),
        "phases": sorted(seed.phases, key=lambda x: x["name"]),
        "patterns": sorted(seed.patterns, key=lambda x: x["code"]),
        "phase_patterns": {k: sorted(v) for k, v in sorted(seed.phase_patterns.items())},
        "hydro_units": sorted((u["name"], u["type"], u["parent"]) for u in seed.hydro_units),
        "hydro_relations": sorted(seed.hydro_relations),
        "ontology_relations": sorted(seed.ontology_relations),
    }
    seed.manifest_hash = hashlib.sha256(
        json.dumps(canon, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return seed


# ----------------------------------------------------------------------
# ACTUAL 读取
# ----------------------------------------------------------------------

def _fetch(cur, sql: str, params: tuple = ()) -> list[tuple]:
    cur.execute(sql, params)
    return cur.fetchall()


def read_actual(cur, seed: Seed) -> dict[str, Any]:
    a: dict[str, Any] = {}
    a["systems"] = {
        name: {"level": lvl, "parent": parent, "description": desc}
        for name, lvl, parent, desc in _fetch(cur, (
            "SELECT s.system_name, s.system_level, p.system_name, COALESCE(s.description,'') "
            "FROM cultural_systems s LEFT JOIN cultural_systems p ON s.parent_system=p.system_id "
            "WHERE s.system_level IN ('ROOT','REGIONAL')"))
    }
    a["regions"] = {
        name: {"provinces": provs or [], "hydro_basis": hb or [], "system": sysname, "description": desc}
        for name, provs, hb, sysname, desc in _fetch(cur, (
            "SELECT r.region_name, r.provinces, r.hydro_basis, s.system_name, COALESCE(r.description,'') "
            "FROM cultural_regions r LEFT JOIN cultural_systems s ON r.entity_id=s.system_id"))
    }
    a["domains"] = {
        name: parent
        for name, parent in _fetch(cur, (
            "SELECT d.domain_name, p.domain_name FROM cultural_domains d "
            "LEFT JOIN cultural_domains p ON d.parent_domain=p.domain_id"))
    }
    a["phases"] = {
        name: macro
        for name, macro in _fetch(cur, "SELECT phase_name, macro_phase FROM historical_phases")
    }
    a["phase_patterns"] = {}
    for pname, codes in _fetch(cur, (
            "SELECT hp.phase_name, array_agg(mp.pattern_code ORDER BY mp.pattern_code) "
            "FROM historical_phase_patterns hpp "
            "JOIN historical_phases hp ON hpp.phase_id=hp.phase_id "
            "JOIN macro_evolution_patterns mp ON hpp.pattern_id=mp.pattern_id "
            "GROUP BY hp.phase_name")):
        a["phase_patterns"][pname] = list(codes or [])
    a["patterns"] = {
        code: name for code, name in _fetch(cur,
            "SELECT pattern_code, pattern_name FROM macro_evolution_patterns")
    }
    a["hydro_units"] = {
        name: {"type": utype, "parent": parent, "province": prov, "description": desc}
        for name, utype, parent, prov, desc in _fetch(cur, (
            "SELECT u.hsu_name, u.hsu_type, p.hsu_name, u.province, COALESCE(u.description,'') "
            "FROM hydro_spatial_units u LEFT JOIN hydro_spatial_units p ON u.parent_hsu=p.hsu_id"))
    }
    a["hydro_relations"] = {
        (f, rel, t) for f, rel, t in _fetch(cur, (
            "SELECT a.hsu_name, r.relation, b.hsu_name FROM hydro_spatial_relations r "
            "JOIN hydro_spatial_units a ON r.from_hsu=a.hsu_id "
            "JOIN hydro_spatial_units b ON r.to_hsu=b.hsu_id"))
    }
    a["ontology_relations"] = {
        (sname, pred, oname)
        for sname, pred, oname in _fetch(cur, (
            "SELECT s.system_name, r.predicate, o.system_name FROM structural_relations r "
            "JOIN cultural_systems s ON r.subject_id=s.system_id "
            "JOIN cultural_systems o ON r.object_id=o.system_id "
            "WHERE r.knowledge_type='ONTOLOGY_RELATION'"))
    }
    return a


# ----------------------------------------------------------------------
# 漂移比较
# ----------------------------------------------------------------------

def compare(seed: Seed, a: dict[str, Any]) -> list[Drift]:
    d: list[Drift] = []

    exp_systems = {s["name"]: {"level": s["level"], "parent": s["parent"], "description": s["description"]}
                   for s in seed.systems}
    for name, exp in exp_systems.items():
        act = a["systems"].get(name)
        if act is None:
            d.append(Drift("MISSING", "cultural_systems", name))
        elif (act["level"] != exp["level"] or act["parent"] != exp["parent"]):
            d.append(Drift("MISMATCH", "cultural_systems", name,
                           f"expected {exp} actual {act}"))
    for name in set(a["systems"]) - set(exp_systems):
        d.append(Drift("UNEXPECTED", "cultural_systems", name, "受控层之外的系统对象"))

    exp_regions = {r["name"]: r for r in seed.regions}
    for name, exp in exp_regions.items():
        act = a["regions"].get(name)
        if act is None:
            d.append(Drift("MISSING", "cultural_regions", name))
        elif (act["system"] != exp["system"] or act["provinces"] != exp["provinces"]
              or act["hydro_basis"] != exp["hydro_basis"]):
            d.append(Drift("MISMATCH", "cultural_regions", name,
                           f"expected provinces={exp['provinces']} hydro={exp['hydro_basis']} system={exp['system']} "
                           f"actual provinces={act['provinces']} hydro={act['hydro_basis']} system={act['system']}"))
    for name in set(a["regions"]) - set(exp_regions):
        d.append(Drift("UNEXPECTED", "cultural_regions", name, "受控层之外的区域对象"))

    exp_domains = {x["name"]: x["parent"] for x in seed.domains}
    for name, parent in exp_domains.items():
        act = a["domains"].get(name)
        if act is None and name not in a["domains"]:
            d.append(Drift("MISSING", "cultural_domains", name))
        elif act is not None and act != parent and not (act is None and parent is None):
            if act != parent:
                d.append(Drift("MISMATCH", "cultural_domains", name,
                               f"expected parent={parent} actual parent={act}"))
    for name in set(a["domains"]) - set(exp_domains):
        d.append(Drift("UNEXPECTED", "cultural_domains", name, "受控层之外的领域对象"))

    exp_phases = {p["name"]: p["macro_phase"] for p in seed.phases}
    for name, macro in exp_phases.items():
        if name not in a["phases"]:
            d.append(Drift("MISSING", "historical_phases", name))
        elif a["phases"][name] != macro:
            d.append(Drift("MISMATCH", "historical_phases", name,
                           f"expected macro_phase={macro} actual={a['phases'][name]}"))
    for name in set(a["phases"]) - set(exp_phases):
        d.append(Drift("UNEXPECTED", "historical_phases", name, "受控层之外的分期对象"))

    for pat in seed.patterns:
        if pat["code"] not in a["patterns"]:
            d.append(Drift("MISSING", "macro_evolution_patterns", pat["code"]))
    for code in set(a["patterns"]) - {p["code"] for p in seed.patterns}:
        d.append(Drift("UNEXPECTED", "macro_evolution_patterns", code))
    for pname, codes in seed.phase_patterns.items():
        act_codes = set(a["phase_patterns"].get(pname) or [])
        if act_codes != set(codes):
            d.append(Drift("MISMATCH", "historical_phase_patterns", pname,
                           f"expected {sorted(codes)} actual {sorted(act_codes)}"))

    exp_units = {u["name"]: u for u in seed.hydro_units}
    for name, exp in exp_units.items():
        act = a["hydro_units"].get(name)
        if act is None:
            d.append(Drift("MISSING", "hydro_spatial_units", name))
        elif act["type"] != exp["type"] or act["parent"] != exp["parent"]:
            d.append(Drift("MISMATCH", "hydro_spatial_units", name,
                           f"expected ({exp['type']}, parent={exp['parent']}) "
                           f"actual ({act['type']}, parent={act['parent']})"))
    for name in set(a["hydro_units"]) - set(exp_units):
        d.append(Drift("UNEXPECTED", "hydro_spatial_units", name, "受控层之外的水系单元"))

    exp_rels = set(seed.hydro_relations)
    for t in exp_rels - a["hydro_relations"]:
        d.append(Drift("MISSING", "hydro_spatial_relations", str(t)))
    for t in a["hydro_relations"] - exp_rels:
        d.append(Drift("UNEXPECTED", "hydro_spatial_relations", str(t)))

    exp_onto = set(seed.ontology_relations)
    for t in exp_onto - a["ontology_relations"]:
        d.append(Drift("MISSING", "structural_relations[ONTOLOGY]", str(t)))
    for t in a["ontology_relations"] - exp_onto:
        d.append(Drift("UNEXPECTED", "structural_relations[ONTOLOGY]", str(t)))

    return d


def verify_constraints(cur) -> list[Drift]:
    d: list[Drift] = []
    checks = [
        ("SELECT count(*) FROM cultural_domains d LEFT JOIN cultural_domains p "
         "ON d.parent_domain=p.domain_id WHERE d.parent_domain IS NOT NULL AND p.domain_id IS NULL",
         "cultural_domains.orphan_parent"),
        ("SELECT count(*) FROM hydro_spatial_units u LEFT JOIN hydro_spatial_units p "
         "ON u.parent_hsu=p.hsu_id WHERE u.parent_hsu IS NOT NULL AND p.hsu_id IS NULL",
         "hydro_spatial_units.orphan_parent"),
        ("SELECT count(*) FROM cultural_systems s LEFT JOIN cultural_systems p "
         "ON s.parent_system=p.system_id WHERE s.parent_system IS NOT NULL AND p.system_id IS NULL",
         "cultural_systems.orphan_parent"),
        ("SELECT count(*) FROM historical_phase_patterns hpp "
         "LEFT JOIN historical_phases hp ON hpp.phase_id=hp.phase_id "
         "LEFT JOIN macro_evolution_patterns mp ON hpp.pattern_id=mp.pattern_id "
         "WHERE hp.phase_id IS NULL OR mp.pattern_id IS NULL",
         "historical_phase_patterns.orphan"),
    ]
    for sql, label in checks:
        cur.execute(sql)
        (cnt,) = cur.fetchone()
        if cnt:
            d.append(Drift("CONSTRAINT", label, f"{cnt} rows"))
    return d


# ----------------------------------------------------------------------
# APPLY（单事务）
# ----------------------------------------------------------------------

def apply_seed(conn, seed: Seed, dry_run: bool) -> None:
    with conn.cursor() as cur:
        # 1. 宏观演化模式
        for pat in seed.patterns:
            cur.execute(
                "INSERT INTO macro_evolution_patterns (pattern_code, pattern_name, description) "
                "VALUES (%s,%s,%s) ON CONFLICT (pattern_code) DO UPDATE "
                "SET pattern_name=EXCLUDED.pattern_name, description=EXCLUDED.description",
                (pat["code"], pat["name"], pat["description"]))

        # 2. 文化系统（先插节点再挂父链）
        for s in seed.systems:
            cur.execute(
                "INSERT INTO cultural_systems (system_name, system_level, description) "
                "VALUES (%s,%s,%s) ON CONFLICT (system_name) DO UPDATE "
                "SET system_level=EXCLUDED.system_level, description=EXCLUDED.description",
                (s["name"], s["level"], s["description"]))
        for s in seed.systems:
            if s["parent"]:
                cur.execute(
                    "UPDATE cultural_systems c SET parent_system=(SELECT system_id FROM cultural_systems WHERE system_name=%s) "
                    "WHERE c.system_name=%s", (s["parent"], s["name"]))

        # 3. 文化区域（legacy 名称确定性归一到 canonical 名称）
        for r in seed.regions:
            cur.execute("SELECT region_id FROM cultural_regions WHERE region_name=%s", (r["name"],))
            canon_row = cur.fetchone()
            legacy = [n for n in r["legacy_names"] if n != r["name"]]
            legacy_ids: list = []
            if legacy:
                cur.execute(
                    "SELECT region_id FROM cultural_regions WHERE region_name = ANY(%s) ORDER BY region_name",
                    (legacy,))
                legacy_ids = [x[0] for x in cur.fetchall()]
            if canon_row is None and legacy_ids:
                # 改名第一条 legacy 行为 canonical（其 memberships 随行保留），其余删除
                cur.execute("UPDATE cultural_regions SET region_name=%s WHERE region_id=%s",
                            (r["name"], legacy_ids[0]))
                legacy_ids = legacy_ids[1:]
            if legacy_ids:
                if canon_row is not None:
                    # 双行并存：membership 重指向 canonical 行后删除 legacy 行
                    cur.execute("UPDATE system_memberships SET region_id=%s::uuid WHERE region_id = ANY(%s::uuid[])",
                                (str(canon_row[0]), [str(x) for x in legacy_ids]))
                cur.execute("DELETE FROM cultural_regions WHERE region_id = ANY(%s::uuid[])", ([str(x) for x in legacy_ids],))
            cur.execute(
                "INSERT INTO cultural_regions (region_name, provinces, hydro_basis, description) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (region_name) DO UPDATE SET provinces=EXCLUDED.provinces, "
                "hydro_basis=EXCLUDED.hydro_basis, description=EXCLUDED.description",
                (r["name"], r["provinces"], r["hydro_basis"], r["description"]))
            if r["system"]:
                cur.execute(
                    "UPDATE cultural_regions SET entity_id=(SELECT system_id FROM cultural_systems WHERE system_name=%s) "
                    "WHERE region_name=%s", (r["system"], r["name"]))
                cur.execute(
                    "UPDATE cultural_systems SET region_id=(SELECT region_id FROM cultural_regions WHERE region_name=%s) "
                    "WHERE system_name=%s", (r["name"], r["system"]))

        # 4. 文化领域（父先于子；名字唯一索引由 007 提供）
        order: list[dict] = []
        pending = list(seed.domains)
        placed = {None}
        guard = 0
        while pending:
            guard += 1
            if guard > len(seed.domains) + 2:
                raise BuilderError("cultural_domains.yaml 存在无法解析的父链（疑似环）")
            rest = []
            for item in pending:
                if item["parent"] in placed:
                    order.append(item)
                    placed.add(item["name"])
                else:
                    rest.append(item)
            pending = rest
        for item in order:
            cur.execute(
                "INSERT INTO cultural_domains (domain_name) VALUES (%s) "
                "ON CONFLICT (domain_name) DO NOTHING",
                (item["name"],))
        for item in order:
            if item["parent"]:
                cur.execute(
                    "UPDATE cultural_domains d SET parent_domain="
                    "(SELECT p.domain_id FROM cultural_domains p WHERE p.domain_name=%s) "
                    "WHERE d.domain_name=%s",
                    (item["parent"], item["name"]))

        # 5. 历史分期
        for p in seed.phases:
            cur.execute(
                "INSERT INTO historical_phases (phase_name, macro_phase, description) VALUES (%s,%s,%s) "
                "ON CONFLICT (phase_name) DO UPDATE SET macro_phase=EXCLUDED.macro_phase, description=EXCLUDED.description",
                (p["name"], p["macro_phase"], p["description"]))

        # 6. 分期↔模式 junction（受控分期全量重建其映射）
        cur.execute(
            "DELETE FROM historical_phase_patterns hpp USING historical_phases hp "
            "WHERE hpp.phase_id=hp.phase_id AND hp.phase_name = ANY(%s)",
            ([p["name"] for p in seed.phases],))
        for pname, codes in seed.phase_patterns.items():
            for code in codes:
                cur.execute(
                    "INSERT INTO historical_phase_patterns (phase_id, pattern_id) "
                    "SELECT hp.phase_id, mp.pattern_id FROM historical_phases hp, macro_evolution_patterns mp "
                    "WHERE hp.phase_name=%s AND mp.pattern_code=%s "
                    "AND NOT EXISTS (SELECT 1 FROM historical_phase_patterns x WHERE x.phase_id=hp.phase_id AND x.pattern_id=mp.pattern_id)",
                    (pname, code))

        # 7. 水系单元：先断自引用、清受控拓扑与历史改型行，再 upsert
        cur.execute("DELETE FROM hydro_spatial_relations")
        cur.execute("UPDATE hydro_spatial_units SET parent_hsu=NULL WHERE parent_hsu IS NOT NULL")
        manifest_types: dict[str, set[str]] = {}
        for u in seed.hydro_units:
            manifest_types.setdefault(u["name"], set()).add(u["type"])
        for name, types in manifest_types.items():
            cur.execute("SELECT hsu_id, hsu_type FROM hydro_spatial_units WHERE hsu_name=%s", (name,))
            for hid, htype in cur.fetchall():
                if htype not in types:
                    cur.execute("DELETE FROM hydro_place_mapping WHERE hsu_id=%s", (hid,))
                    cur.execute("DELETE FROM hydro_spatial_units WHERE hsu_id=%s", (hid,))
        for u in seed.hydro_units:
            cur.execute(
                "INSERT INTO hydro_spatial_units (hsu_name, hsu_type, province, description) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (hsu_name, hsu_type) DO UPDATE SET province=EXCLUDED.province, description=EXCLUDED.description",
                (u["name"], u["type"], "、".join(u["provinces"]) or None, u["description"]))
        for u in seed.hydro_units:
            if u["parent"]:
                cur.execute(
                    "UPDATE hydro_spatial_units c SET parent_hsu=(SELECT hsu_id FROM hydro_spatial_units WHERE hsu_name=%s) "
                    "WHERE c.hsu_name=%s", (u["parent"], u["name"]))

        # 8. 水系拓扑（受控集合全量重建）
        for f, rel, t in seed.hydro_relations:
            cur.execute(
                "INSERT INTO hydro_spatial_relations (from_hsu, relation, to_hsu) "
                "SELECT a.hsu_id, %s, b.hsu_id FROM hydro_spatial_units a, hydro_spatial_units b "
                "WHERE a.hsu_name=%s AND b.hsu_name=%s "
                "ON CONFLICT (from_hsu, relation, to_hsu) DO NOTHING",
                (rel, f, t))

        # 9. 受控本体结构关系（ONTOLOGY_RELATION，免证据策略）：先清后建
        cur.execute(
            "DELETE FROM structural_relation_evidence se USING structural_relations r "
            "WHERE se.relation_id=r.relation_id AND r.knowledge_type='ONTOLOGY_RELATION'")
        cur.execute("DELETE FROM structural_relations WHERE knowledge_type='ONTOLOGY_RELATION'")
        cur.execute("DELETE FROM structural_relation_evidence se USING structural_relations r "
                    "WHERE se.relation_id=r.relation_id AND r.knowledge_type='ONTOLOGY_RELATION'")
        cur.execute("DELETE FROM structural_relations WHERE knowledge_type='ONTOLOGY_RELATION'")
        for sname, pred, oname in seed.ontology_relations:
            cur.execute(
                "INSERT INTO structural_relations (subject_id, predicate, object_id, confidence, status, "
                "evidence_count, independent_source_count, model, prompt_version, knowledge_type, evidence_policy_version) "
                "SELECT s.system_id, %s, o.system_id, 1.0, 'ADMITTED', 0, 0, "
                "'controlled_ontology', %s, 'ONTOLOGY_RELATION', 'ONTOLOGY_EXEMPT' "
                "FROM cultural_systems s, cultural_systems o WHERE s.system_name=%s AND o.system_name=%s "
                "AND NOT EXISTS (SELECT 1 FROM structural_relations x WHERE x.subject_id=s.system_id "
                "AND x.predicate=%s AND x.object_id=o.system_id AND x.knowledge_type='ONTOLOGY_RELATION')",
                (pred, ONTOLOGY_RELATION_VERSION, sname, oname, pred))

        if dry_run:
            raise _DryRunRollback()


class _DryRunRollback(Exception):
    """dry-run 模式下主动回滚，检验事务可整体撤销。"""


# ----------------------------------------------------------------------
# 命令入口
# ----------------------------------------------------------------------

def dsn(override: str | None = None) -> str:
    if override:
        return override
    sys.path.insert(0, str(ROOT))
    try:
        from config.settings import SETTINGS  # type: ignore
        return SETTINGS.pg_dsn
    except Exception:
        return "host=127.0.0.1 port=5433 dbname=ycki user=postgres password=ycki_pg_2026"


def main() -> int:
    ap = argparse.ArgumentParser(description="canonical_v2 受控骨架确定性构建器")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="事务内试跑并回滚，打印将执行的修复")
    g.add_argument("--apply", action="store_true", help="单事务构建/修复受控骨架")
    g.add_argument("--verify", action="store_true", help="校验 EXPECTED(manifest)==ACTUAL(db)")
    g.add_argument("--manifest-hash", action="store_true", help="输出 seed manifest SHA256")
    ap.add_argument("--dsn", default=None, help="覆盖 PG DSN（clean-room 测试用）")
    args = ap.parse_args()

    seed = load_seed()

    if args.manifest_hash:
        print(seed.manifest_hash)
        return 0

    conn = psycopg2.connect(dsn(args.dsn))
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if args.apply or args.dry_run:
                try:
                    apply_seed(conn, seed, dry_run=args.dry_run)
                except _DryRunRollback:
                    conn.rollback()
                    print("DRY-RUN OK：事务已回滚，seed 可完整应用。")
                    print(f"manifest_hash={seed.manifest_hash}")
                    return 0
                conn.commit()
                print(f"APPLY OK  manifest_hash={seed.manifest_hash}")
                drift = []
                with conn.cursor() as cur2:
                    actual = read_actual(cur2, seed)
                    drift = compare(seed, actual) + verify_constraints(cur2)
                if drift:
                    print(f"APPLY 后仍存在 {len(drift)} 项漂移（apply 不应发生）：")
                    for x in drift:
                        print("  " + x.line())
                    return 1
                print("VERIFY after APPLY: 0 drift")
                return 0

            # --verify
            actual = read_actual(cur, seed)
            drift = compare(seed, actual) + verify_constraints(cur)
        if drift:
            print(f"VERIFY FAIL：{len(drift)} 项漂移")
            for x in drift:
                print("  " + x.line())
            return 1
        print("VERIFY PASS：EXPECTED == ACTUAL，0 漂移")
        print(f"manifest_hash={seed.manifest_hash}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except BuilderError as exc:
        print(f"SEED ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
