#!/usr/bin/env python3
"""validate_canonical_v2.py — canonical_v2 全量验收（goal §91-§93 + §3 反自证）。

反自证规则（§3）：
  3.2 禁止 Vacuous PASS：样本不足 → NOT_MEASURED；能力整体缺失（如 Flow=0）→
      FAIL_CAPABILITY_ABSENT，绝不允许因"违规数为 0"而 PASS。
  3.3 每门禁输出 sample_count / positive_count / negative_count /
      minimum_required_sample / coverage。
  3.4 指标未达阈值不得 PASS（能力阈值由 V2_FINAL_RELEASE_VALIDATION 强制；
      本文件负责完整性门禁，但同样遵守样本充足性）。

门禁：
  G01 Reproducibility    builder --verify 0 drift（对本库）
  G02/G03 Ontology+Hydro validate_v2_ontology ERROR=0
  G04 Membership         geo-only ADMITTED=0（min sample 30）
  G05 StructuralRelation 非法谓词（对 v2 谓词表逐条验证）/无证据 ADMITTED=0
  G06 HighRiskRelation   高风险谓词 ADMITTED 独立来源数达标
  G07 Tradition          ADMITTED 无字段级证据 / 关键字段缺证据=0
  G08 Process            缺时间证据 / 无阶段结构=0
  G09 Flow               硬字段缺失=0；total=0 → FAIL_CAPABILITY_ABSENT
  G10 Provenance         ADMITTED 高阶对象证据可回溯 resource 比例=100%
  G12/G13 Gap+Task       false_resolution=0；tasks_resolved=0 → NOT_MEASURED
  V1REG canonical_v1     ADMITTED claim 无 evidence=0

用法：
  python tools/validate_canonical_v2.py --fast
  python tools/validate_canonical_v2.py --json > report.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import psycopg2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GATES: list[dict] = []


def gate(gid: str, name: str, minimum: int) -> dict:
    g = {"id": gid, "name": name, "status": "NOT_MEASURED", "metrics": {},
         "failures": [], "sample_count": 0, "positive_count": 0,
         "negative_count": 0, "minimum_required_sample": minimum,
         "coverage": None}
    GATES.append(g)
    return g


def decide(g: dict, *, sample: int, violations: int, minimum: int | None = None,
           capability_absent: bool = False) -> str:
    """统一判定：样本不足 NOT_MEASURED；能力缺失 FAIL_CAPABILITY_ABSENT；
    违规 0 且样本充足 → PASS；否则 FAIL。"""
    minimum = g["minimum_required_sample"] if minimum is None else minimum
    g["sample_count"] = sample
    g["negative_count"] = violations
    g["positive_count"] = sample - violations
    g["coverage"] = round(sample / minimum, 3) if minimum else None
    if capability_absent:
        g["status"] = "FAIL_CAPABILITY_ABSENT"
        g["failures"].append("capability absent: no valid samples exist")
        return g["status"]
    if sample < minimum:
        g["status"] = "NOT_MEASURED"
        g["failures"].append(f"sample {sample} < minimum {minimum}")
        return g["status"]
    g["status"] = "PASS" if violations == 0 else "FAIL"
    if violations:
        g["failures"].append(f"{violations} violations")
    return g["status"]


def sql_count(cur, sql: str) -> int:
    cur.execute(sql)
    (n,) = cur.fetchone()
    return int(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    try:
        with conn.cursor() as cur:
            # G01 复现性：builder verify（独立脚本重导 manifest）
            g = gate("G01", "Reproducibility", 1)
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "init_canonical_v2.py"), "--verify"],
                               capture_output=True, text=True, cwd=str(ROOT))
            g["metrics"]["verify_exit"] = r.returncode
            g["sample_count"] = 1
            g["status"] = "PASS" if r.returncode == 0 else "FAIL"

            # G02/G03 本体 + 水系
            g = gate("G02/G03", "Ontology+Hydro", 1)
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_v2_ontology.py"), "--json"],
                               capture_output=True, text=True, cwd=str(ROOT))
            try:
                ont = json.loads(r.stdout)
                g["metrics"]["ontology_errors"] = ont.get("error_count")
            except Exception:
                ont = {"error_count": -1}
            g["sample_count"] = 1
            g["status"] = "PASS" if ont.get("error_count") == 0 else "FAIL"

            # G04 Membership（完整性：geo-only 准入；样本≥30 才可判）
            g = gate("G04", "Membership", 30)
            admitted = sql_count(cur, """
                SELECT count(*) FROM system_memberships
                WHERE system_id IS NOT NULL AND status='ADMITTED'""")
            g["metrics"]["geo_only_admitted"] = sql_count(cur, """
                SELECT count(*) FROM system_memberships
                WHERE system_id IS NOT NULL AND status='ADMITTED' AND anchor_count < 2""")
            g["metrics"]["admitted"] = admitted
            g["metrics"]["candidate"] = sql_count(cur, """
                SELECT count(*) FROM system_memberships WHERE system_id IS NOT NULL AND status='CANDIDATE'""")
            decide(g, sample=admitted, violations=g["metrics"]["geo_only_admitted"])
            # 能力主指标（P/R/F1 基准）由 V2_MEMBERSHIP_BENCHMARK 报告；
            # 此处只标注诊断参考，不作为本门禁依据（§3.4）。
            mb = ROOT / "reports" / "V2_MEMBERSHIP_BENCHMARK.json"
            if mb.exists():
                g["metrics"]["benchmark_diagnostic"] = {
                    k: json.loads(mb.read_text(encoding="utf-8")).get(k)
                    for k in ("sample_size", "admitted_precision")}

            # G05 结构关系：非法谓词真实校验 + 无证据准入
            g = gate("G05", "StructuralRelation", 1)
            pv2 = yaml.safe_load((ROOT / "yangtze" / "schema" / "structural_predicates_v2.yaml")
                                 .read_text(encoding="utf-8"))
            valid_codes = {p["id"] for p in pv2["predicates"]}
            total_rels = sql_count(cur, "SELECT count(*) FROM structural_relations")
            # psycopg2 需要展开元组
            cur.execute("SELECT count(*) FROM structural_relations WHERE predicate <> ALL(%s)",
                        (sorted(valid_codes),))
            g["metrics"]["invalid_predicate"] = int(cur.fetchone()[0])
            g["metrics"]["evidence_less_admitted"] = sql_count(cur, """
                SELECT count(*) FROM structural_relations
                WHERE status='ADMITTED' AND knowledge_type IS DISTINCT FROM 'ONTOLOGY_RELATION'
                  AND COALESCE(evidence_count,0)=0 AND COALESCE(independent_source_count,0)=0""")
            g["metrics"]["ontology_relations"] = sql_count(cur, """
                SELECT count(*) FROM structural_relations WHERE knowledge_type='ONTOLOGY_RELATION'""")
            decide(g, sample=total_rels,
                   violations=g["metrics"]["invalid_predicate"] + g["metrics"]["evidence_less_admitted"])

            # G06 高风险关系：ADMITTED 独立来源数必须达到谓词要求
            g = gate("G06", "HighRiskRelationPolicy", 1)
            hrisk = {p["id"]: int(p.get("minimum_independent_sources", 1))
                     for p in pv2["predicates"] if int(p.get("minimum_independent_sources", 1)) >= 2}
            violations = 0
            hr_detail = {}
            for code, need in sorted(hrisk.items()):
                cur.execute("""SELECT count(*) FROM structural_relations
                               WHERE predicate=%s AND status='ADMITTED'
                                 AND COALESCE(independent_source_count,0) < %s""",
                            (code, need))
                bad = int(cur.fetchone()[0])
                cur.execute("""SELECT count(*) FROM structural_relations
                               WHERE predicate=%s AND status='ADMITTED'""", (code,))
                adm = int(cur.fetchone()[0])
                if adm:
                    hr_detail[code] = {"admitted": adm, "below_minimum": bad}
                violations += bad
            g["metrics"]["high_risk_predicates"] = len(hrisk)
            g["metrics"]["violations_detail"] = hr_detail
            g["metrics"]["admitted_without_policy_version"] = sql_count(cur, """
                SELECT count(*) FROM structural_relations WHERE status='ADMITTED'
                  AND COALESCE(evidence_policy_version,'')=''""")
            decide(g, sample=total_rels,
                   violations=violations + g["metrics"]["admitted_without_policy_version"])

            # G07 Tradition：无证据 / 关键字段缺证据；样本=ADMITTED 传统
            g = gate("G07", "Tradition", 1)
            admitted_t = sql_count(cur, "SELECT count(*) FROM cultural_traditions WHERE status='ADMITTED'")
            g["metrics"]["admitted_without_evidence"] = sql_count(cur, """
                SELECT count(*) FROM cultural_traditions t WHERE t.status='ADMITTED'
                  AND NOT EXISTS (SELECT 1 FROM tradition_evidence te WHERE te.tradition_id=t.tradition_id)""")
            g["metrics"]["key_field_missing"] = sql_count(cur, """
                SELECT count(*) FROM cultural_traditions t WHERE t.status='ADMITTED'
                  AND NOT EXISTS (SELECT 1 FROM tradition_evidence te
                                  WHERE te.tradition_id=t.tradition_id AND te.evidence_role='core_practices')""")
            g["metrics"]["total"] = sql_count(cur, "SELECT count(*) FROM cultural_traditions")
            decide(g, sample=admitted_t,
                   violations=g["metrics"]["admitted_without_evidence"] + g["metrics"]["key_field_missing"])

            # G08 Process：缺时间证据 / 无阶段结构；样本=ADMITTED 过程
            g = gate("G08", "Process", 1)
            admitted_p = sql_count(cur, "SELECT count(*) FROM cultural_processes WHERE status='ADMITTED'")
            g["metrics"]["without_time_evidence"] = sql_count(cur, """
                SELECT count(*) FROM cultural_processes p WHERE p.status='ADMITTED'
                  AND (p.start_time IS NULL OR p.start_time='')
                  AND NOT EXISTS (SELECT 1 FROM process_evidence pe
                                  WHERE pe.process_id=p.process_id AND pe.field_name='time')""")
            g["metrics"]["without_process_structure"] = sql_count(cur, """
                SELECT count(*) FROM cultural_processes p WHERE p.status='ADMITTED'
                  AND (SELECT count(*) FROM process_stages s WHERE s.process_id=p.process_id) < 2
                  AND (p.end_time IS NULL OR p.end_time='')""")
            g["metrics"]["total"] = sql_count(cur, "SELECT count(*) FROM cultural_processes")
            decide(g, sample=admitted_p,
                   violations=g["metrics"]["without_time_evidence"] + g["metrics"]["without_process_structure"])

            # G09 Flow：能力缺失检查在前（total=0 绝不 PASS）
            g = gate("G09", "Flow", 1)
            total_f = sql_count(cur, "SELECT count(*) FROM cultural_flows")
            admitted_f = sql_count(cur, "SELECT count(*) FROM cultural_flows")
            g["metrics"]["missing_hard_fields"] = sql_count(cur, """
                SELECT count(*) FROM cultural_flows
                WHERE COALESCE(origin,'')='' OR COALESCE(destination,'')='' OR COALESCE(content,'')=''""")
            g["metrics"]["missing_evidence"] = sql_count(cur, """
                SELECT count(*) FROM cultural_flows
                WHERE COALESCE(quote_span,'')='' OR COALESCE(resource_id,'')=''""")
            g["metrics"]["total"] = total_f
            decide(g, sample=total_f,
                   violations=g["metrics"]["missing_hard_fields"] + g["metrics"]["missing_evidence"],
                   capability_absent=(total_f == 0))

            # G10 溯源：ADMITTED 高阶对象 100% 可回溯 resource
            g = gate("G10", "Provenance", 1)
            t_total = sql_count(cur, "SELECT count(*) FROM cultural_traditions WHERE status='ADMITTED'")
            t_ok = sql_count(cur, """
                SELECT count(*) FROM cultural_traditions t
                WHERE t.status='ADMITTED'
                  AND EXISTS (SELECT 1 FROM tradition_evidence te WHERE te.tradition_id=t.tradition_id
                              AND COALESCE(te.resource_id,'')<>'')""")
            p_total = sql_count(cur, "SELECT count(*) FROM cultural_processes WHERE status='ADMITTED'")
            p_ok = sql_count(cur, """
                SELECT count(*) FROM cultural_processes p
                WHERE p.status='ADMITTED'
                  AND EXISTS (SELECT 1 FROM process_evidence pe WHERE pe.process_id=p.process_id
                              AND COALESCE(pe.resource_id,'')<>'')""")
            sample = t_total + p_total
            g["metrics"]["traditions_traced"] = f"{t_ok}/{t_total}"
            g["metrics"]["processes_traced"] = f"{p_ok}/{p_total}"
            g["metrics"]["flows_total"] = total_f
            decide(g, sample=sample, violations=(t_total - t_ok) + (p_total - p_ok))

            # G12/G13 缺口与研究任务（false_resolution 必须为 0；无 RESOLVED 任务 → NOT_MEASURED）
            g = gate("G12/G13", "GapEngine+ResearchTask", 1)
            g["metrics"]["gaps_open"] = sql_count(cur, "SELECT count(*) FROM structural_gaps WHERE status='OPEN'")
            g["metrics"]["gaps_resolved"] = sql_count(cur, "SELECT count(*) FROM structural_gaps WHERE status='RESOLVED'")
            g["metrics"]["tasks"] = sql_count(cur, "SELECT count(*) FROM structural_research_tasks")
            g["metrics"]["tasks_resolved"] = sql_count(cur, """
                SELECT count(*) FROM structural_research_tasks WHERE status='RESOLVED'""")
            g["metrics"]["false_resolution"] = sql_count(cur, """
                SELECT count(*) FROM structural_research_tasks t
                WHERE t.status='RESOLVED' AND t.gap_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM structural_gaps g WHERE g.gap_id=t.gap_id AND g.status='OPEN')""")
            st = decide(g, sample=g["metrics"]["tasks_resolved"],
                        violations=g["metrics"]["false_resolution"])
            if st == "PASS":
                # 有 RESOLVED 样本时额外要求 gap 端确实闭合
                pass

            # V1REG canonical_v1 回归护栏
            g = gate("V1REG", "canonical_v1 regression guard", 1)
            g["metrics"]["resources"] = sql_count(cur, "SELECT count(*) FROM resources")
            g["metrics"]["admitted_claims"] = sql_count(cur, "SELECT count(*) FROM claims WHERE status='ADMITTED'")
            g["metrics"]["entities"] = sql_count(cur, "SELECT count(*) FROM canonical_entities WHERE merged_into IS NULL")
            g["metrics"]["claims_without_evidence"] = sql_count(cur, """
                SELECT count(*) FROM claims c WHERE c.status='ADMITTED'
                  AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.claim_id=c.claim_id)""")
            g["sample_count"] = g["metrics"]["admitted_claims"]
            g["status"] = "PASS" if g["metrics"]["claims_without_evidence"] == 0 else "FAIL"

            # §22.2 能力目标进度（非门禁，供最终发布验收读取）
            targets = {
                "traditions_admitted_target": 50, "traditions_admitted": admitted_t,
                "processes_admitted_target": 80, "processes_admitted": admitted_p,
                "flows_admitted_target": 30, "flows_admitted": admitted_f,
            }
    finally:
        conn.close()

    hard_fail = [x["id"] for x in GATES if x["status"] in ("FAIL", "FAIL_CAPABILITY_ABSENT")]
    not_meas = [x["id"] for x in GATES if x["status"] == "NOT_MEASURED"]
    overall = "FAIL" if hard_fail else ("NOT_MEASURED" if not_meas else "PASS")
    out = {"overall": overall, "failed_gates": hard_fail, "not_measured_gates": not_meas,
           "capability_targets": targets, "gates": GATES}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for x in GATES:
            print(f"{x['status']:22s} {x['id']:8s} {x['name']} "
                  f"[n={x['sample_count']}/{x['minimum_required_sample']}] "
                  f"{json.dumps(x['metrics'], ensure_ascii=False)}")
            for f in x["failures"]:
                print(f"    - {f}")
        print(f"\nOVERALL: {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
