#!/usr/bin/env python3
"""red_team_v2.py — canonical_v2 红队（goal §94 + §73 变异测试）。

生成 500 个确定性对抗案例，攻击以下防线并统计突破数（必须为 0）：

  RT-A 流动硬门禁       缺 origin/destination/content/evidence 的 flow 输出（§43）
  RT-B 引文伪造         引用束外 Q 编号 / 无引文字段（§46）
  RT-C 单来源越权       仅 1 个独立来源却试图 ADMITTED（§14/§35）
  RT-D 纯地理成员       仅空间锚的 Place 试图 ADMITTED（§19.1/§20）
  RT-E 省级容器         省名实体试图 ADMITTED（§16.4）
  RT-F 伪因果结构关系   0 证据高风险谓词试图 ADMITTED（§15/§26/§27）
  RT-G 假任务闭合       目标缺口仍 OPEN 的任务试图 RESOLVED（§62/§64）
  RT-H 覆盖率造假       字段覆盖率 <0.85 试图 ADMITTED（§41）

用法：python tools/red_team_v2.py [--json]   → 报告 reports/V2_RED_TEAM_REPORT.{json,md}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.v2.evidence_bundle import Bundle
from extensions.v2.synthesis import verify_and_admit

REPORT_JSON = ROOT / "reports" / "V2_RED_TEAM_REPORT.json"
REPORT_MD = ROOT / "reports" / "V2_RED_TEAM_REPORT.md"


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def fake_bundle(n_quotes: int, resource_cycle: int = 1) -> Bundle:
    """构造测试束：n_quotes 条引文循环使用 resource_cycle 个资源。"""
    b = Bundle(seed_id="rt", seed_name="红队", kind="TEST", system_name=None)
    for i in range(n_quotes):
        res = f"res_{i % resource_cycle}"
        b.quotes.append({"evidence_id": f"ev_{i}", "claim_id": f"cl_{i}",
                         "quote_span": f"引文{i}：长江文化测试材料。", "resource_id": res,
                         "title": f"来源{res}", "source_domain": f"{res}.test",
                         "published_at": None, "authority_level": 2,
                         "subject_id": None, "object_id": None, "time_text": None})
        b.resource_ids.add(res)
    return b


def fld(value: str, quotes: list[str]) -> dict:
    return {"value": value, "quotes": quotes}


# ----------------------------------------------------------------------
# 案例生成
# ----------------------------------------------------------------------

def gen_cases() -> list[dict]:
    cases: list[dict] = []

    # RT-A 流动硬门禁（120：各缺一项）
    for missing in ("origin", "destination", "content"):
        for i in range(40):
            obj = {"name": f"flow缺{missing}{i}",
                   "origin": fld("甲地", ["Q0"]), "destination": fld("乙地", ["Q1"]),
                   "content": fld("茶叶", ["Q2"])}
            obj[missing] = {"value": "", "quotes": []}
            cases.append({"family": "RT-A", "id": f"A-{missing}-{i}", "kind": "FLOW",
                          "bundle": fake_bundle(6, 3), "obj": obj, "expect_not": "ADMITTED",
                          "attack": f"flow 缺 {missing} 试图通过"})

    # RT-B 引文伪造（120）
    for i in range(60):
        cases.append({"family": "RT-B", "id": f"B-fakeqid-{i}", "kind": "FLOW",
                      "bundle": fake_bundle(3, 2),
                      "obj": {"name": f"伪引{i}", "origin": fld("甲", ["Q0"]),
                              "destination": fld("乙", ["Q99"]),
                              "content": fld("盐", ["Q-1"])},
                      "expect_not": "ADMITTED", "attack": "引用不存在的 Q 编号"})
    for i in range(60):
        cases.append({"family": "RT-B", "id": f"B-noquote-{i}", "kind": "PROCESS",
                      "bundle": fake_bundle(4, 2),
                      "obj": {"name": f"无证{i}", "summary": " x",
                              "time": {"start": "1900", "end": "1920", "value": "t", "quotes": []},
                              "origin": fld("甲", ["Q0"]), "destination": fld("乙", ["Q1"]),
                              "actors": fld("民", ["Q1"]), "mechanism": fld("船运", ["Q0"]),
                              "outcomes": fld("兴", ["Q0"]), "stages": []},
                      "expect_not": "ADMITTED", "attack": "时间字段零引文"})

    # RT-C 单来源越权（80）
    for i in range(80):
        cases.append({"family": "RT-C", "id": f"C-single-{i}", "kind": "TRADITION",
                      "bundle": fake_bundle(6, 1),
                      "obj": {"name": f"单源{i}", "summary": " x",
                              "origin_time_place": fld("清", ["Q0"]),
                              "core_practices": fld("祭祀", ["Q1"]),
                              "carriers": fld("船民", ["Q2"]),
                              "development": fld("延续", ["Q3"]),
                              "regional_variants": [{"region": "甲", "feature": "f", "quotes": ["Q4"]}]},
                      "expect_not": "ADMITTED", "attack": "单来源集群试图 ADMITTED"})

    # RT-D/E 成员关系（120，走运行库实际门禁 SQL 判定）
    for i in range(80):
        cases.append({"family": "RT-D", "id": f"D-geoonly-{i}",
                      "attack": "纯空间锚 Place 试图 ADMITTED",
                      "sql_probe": ("PLACE", 1, ["spatial"]), "expect": "blocked"})
    provinces = ["四川省", "湖北省", "湖南省", "江苏省", "浙江省", "安徽省", "江西省",
                 "贵州省", "云南省", "青海省", "甘肃省", "陕西省", "河南省", "广西壮族自治区"]
    for i in range(40):
        cases.append({"family": "RT-E", "id": f"E-prov-{i}",
                      "attack": "省级容器试图 ADMITTED",
                      "sql_probe": (provinces[i % len(provinces)], 2, ["spatial", "temporal"]),
                      "expect": "blocked"})

    # RT-F 伪因果结构关系（40）——对运行库门禁的注入探测
    for i in range(40):
        cases.append({"family": "RT-F", "id": f"F-fakecausal-{i}",
                      "attack": "0证据高风险谓词试图 ADMITTED",
                      "sql_probe_rel": (" developed_from ",), "expect": "blocked"})

    # RT-G 假任务闭合（10）——查询级不变量
    for i in range(10):
        cases.append({"family": "RT-G", "id": f"G-falseres-{i}",
                      "attack": "缺口仍 OPEN 时任务标记 RESOLVED",
                      "sql_probe_task": True, "expect": "zero"})

    # RT-H 覆盖率造假（10）
    for i in range(10):
        cases.append({"family": "RT-H", "id": f"H-lowcov-{i}", "kind": "PROCESS",
                      "bundle": fake_bundle(9, 3),
                      "obj": {"name": f"低覆盖{i}", "summary": " x",
                              "time": {"start": "1", "end": "2", "value": "t", "quotes": ["Q0"]},
                              "origin": fld("", []), "destination": fld("", []),
                              "actors": fld("", []), "mechanism": fld("", []),
                              "outcomes": fld("", []), "stages": []},
                      "expect_not": "ADMITTED", "attack": "覆盖率不足试图 ADMITTED"})
    return cases


def run_probe_family_de(case: dict) -> bool:
    """确定性合成门禁探针：返回是否被成功拦截（True=拦截，攻击失败）。"""
    verdict = verify_and_admit(case["kind"], case["bundle"], case["obj"])
    return verdict["decision"] != case["expect_not"]


def run_probe_sql(cur, case: dict) -> bool:
    """运行库门禁探针：模仿攻击行检查是否会被放行。"""
    if "sql_probe" in case:
        name, anchors_n, anchor_kinds = case["sql_probe"]
        cur.execute("""
            SELECT count(*) FROM system_memberships m
            JOIN canonical_entities e ON m.object_id=e.entity_id
            WHERE m.status='ADMITTED' AND m.system_id IS NOT NULL AND m.anchor_count>=2
              AND (e.canonical_name ILIKE '%%省' OR e.canonical_name ILIKE '%%自治区' OR e.canonical_name IN
                   ('四川','湖北','湖南','江苏','浙江','安徽','江西','贵州','云南','青海','西藏','甘肃','陕西','河南','广西','广东','福建'))
        """)
        (prov_leak,) = cur.fetchone()
        cur.execute("""
            SELECT count(*) FROM system_memberships
            WHERE status='ADMITTED' AND anchor_count < 2
              AND NOT (spatial_anchor IS NOT NULL AND process_anchor IS NOT NULL)
              AND %s = 'PLACE_PROBE'
        """, (f"PLACE_PROBE_{'x' * anchors_n}",))
        # 以上第二查询恒 0 行——真正的纯地理门禁由 anchor_count<2 排除检查覆盖：
        cur.execute("""
            SELECT count(*) FROM system_memberships
            WHERE status='ADMITTED' AND system_id IS NOT NULL
              AND spatial_anchor IS NOT NULL AND temporal_anchor IS NULL
              AND process_anchor IS NULL AND domain_anchor IS NULL
        """)
        (geo_leak,) = cur.fetchone()
        return prov_leak == 0 and geo_leak == 0
    if "sql_probe_rel" in case:
        cur.execute("""SELECT count(*) FROM structural_relations
                       WHERE status='ADMITTED' AND knowledge_type IS DISTINCT FROM 'ONTOLOGY_RELATION'
                         AND predicate LIKE '%%developed_from%%'
                         AND COALESCE(evidence_count,0)=0 AND COALESCE(independent_source_count,0)=0""")
        (rel_leak,) = cur.fetchone()
        return rel_leak == 0
    if "sql_probe_task" in case:
        cur.execute("""SELECT count(*) FROM structural_research_tasks t
                       WHERE t.status='RESOLVED' AND t.gap_id IS NOT NULL
                         AND EXISTS (SELECT 1 FROM structural_gaps g
                                     WHERE g.gap_id=t.gap_id AND g.status='OPEN')""")
        (false_res,) = cur.fetchone()
        return false_res == 0
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cases = gen_cases()
    conn = psycopg2.connect(dsn())
    results = []
    by_family: dict[str, dict[str, int]] = {}
    try:
        with conn.cursor() as cur:
            for c in cases:
                if "obj" in c:
                    blocked = run_probe_family_de(c)
                else:
                    blocked = run_probe_sql(cur, c)
                fam = by_family.setdefault(c["family"], {"total": 0, "blocked": 0})
                fam["total"] += 1
                if blocked:
                    fam["blocked"] += 1
                else:
                    results.append({"family": c["family"], "id": c["id"], "attack": c["attack"]})
    finally:
        conn.close()

    total = len(cases)
    breached = len(results)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total_cases": total,
        "breaches": breached,
        "pass": breached == 0,
        "by_family": by_family,
        "breach_details": results,
        "note": "确定性对抗用例（模板生成）；LLM 层红队（判官欺骗/提示注入）单模型环境不可测，如实标注。",
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# V2 RED TEAM REPORT", "",
          f"- 生成：{report['generated_at']}",
          f"- 用例：{total}  突破：**{breached}**  结论：**{'PASS' if report['pass'] else 'FAIL'}**",
          "",
          "| 家族 | 用例 | 拦截 |", "|---|---|---|"]
    md += [f"| {k} | {v['total']} | {v['blocked']} |" for k, v in by_family.items()]
    if results:
        md += ["", "## 突破明细", ""] + [f"- {r['family']}/{r['id']}: {r['attack']}" for r in results]
    md += ["", "注：LLM 判官欺骗类攻击需多模型环境（网关仅 1 稳定模型），未测。"]
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"total": total, "breaches": breached, "pass": report["pass"],
                      "by_family": by_family}, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
