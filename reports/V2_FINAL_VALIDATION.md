# V2 FINAL VALIDATION

- 生成时间：2026-09-14T01:23:12+0800（脚本生成，§107）
- Git commit：df6844f
- **FINAL STATUS：FAIL**（§111/§120 规则）

## 阶段状态

- REPRODUCIBILITY: **PASS**
- ONTOLOGY: **PASS**
- HYDRO_SPATIAL: **PASS**
- SYSTEM_MEMBERSHIP: **NOT_MEASURED**
- STRUCTURAL_RELATION: **PASS**
- TRADITION: **PASS**
- PROCESS: **PASS**
- FLOW: **FAIL_CAPABILITY_ABSENT**
- INTERPRETATION: **PASS**
- STRUCTURAL_GAP_ENGINE: **NOT_MEASURED**
- RESEARCH_ENGINE: **NOT_MEASURED**
- DIGITAL_HUMANITIES_BENCHMARK: **FAIL_PROXY_ONLY(mean=0.917,needs_real_benchmark)**
- GOLDEN_TEN: **PARTIAL(admitted=9/20,flows=0)**
- RED_TEAM: **PASS**
- CLEAN_ROOM: **PASS(report 2026-09-13 03:29)**
- BURN_IN: **PARTIAL_GAIN(cycles=3)**
- SOAK_TEST: **PASS**
- CULTURAL_SYSTEM_AUTONOMOUS_GROWTH: **RUNNING(daemon cycle 43)**
- CANONICAL_V1_REGRESSION: **PASS**

## 门禁指标

| Gate | 状态 | 指标 |
|---|---|---|
| G01 | PASS | `{"verify_exit": 0}` |
| G02/G03 | PASS | `{"ontology_errors": 0}` |
| G04 | NOT_MEASURED | `{"geo_only_admitted": 0, "admitted": 23, "candidate": 2014, "benchmark_diagnostic": {"sample_size": 131, "admitted_precision": 0.5217}}` |
| G05 | PASS | `{"invalid_predicate": 0, "evidence_less_admitted": 0, "ontology_relations": 7}` |
| G06 | PASS | `{"high_risk_predicates": 11, "violations_detail": {}, "admitted_without_policy_version": 0}` |
| G07 | PASS | `{"admitted_without_evidence": 0, "key_field_missing": 0, "total": 6}` |
| G08 | PASS | `{"without_time_evidence": 0, "without_process_structure": 0, "total": 6}` |
| G09 | FAIL_CAPABILITY_ABSENT | `{"missing_hard_fields": 0, "missing_evidence": 0, "total": 0}` |
| G10 | PASS | `{"traditions_traced": "4/4", "processes_traced": "5/5", "flows_total": 0}` |
| G12/G13 | NOT_MEASURED | `{"gaps_open": 532, "gaps_resolved": 3, "tasks": 10, "tasks_resolved": 0, "false_resolution": 0}` |
| V1REG | PASS | `{"resources": 4042, "admitted_claims": 4482, "entities": 27630, "claims_without_evidence": 0}` |

## 数量盘点（§110）

```json
{
  "resources": 4042,
  "entities": 27630,
  "claims_admitted": 4482,
  "evidence": 4923,
  "systems": 8,
  "regions": 7,
  "hydro_units": 34,
  "hydro_relations": 46,
  "phases": 13,
  "domains": 93,
  "system_memberships": 10082,
  "memberships_admitted": 23,
  "traditions": 6,
  "processes": 6,
  "flows": 0,
  "structural_relations": 21,
  "interpretations": 9,
  "interpretation_evidence": 166,
  "interpretations_without_evidence": 0,
  "fact_only_entities": 17567,
  "gaps_open": 532,
  "gaps_partial": 4,
  "gaps_resolved": 3,
  "tasks_resolved": 0
}
```

## Membership 判官基准

```json
{
  "sample_size": 131,
  "rule_admitted": 23,
  "admitted_precision": 0.5217,
  "candidate_uphold_rate": 0.7963,
  "judge_errors": 1,
  "interpretation": "单模型受限：同模型证据丰富判官=准入终审（自洽不可作金标）；本 precision 为信息饥饿盲判官一致率（诊断指标，系统性低于准入判官）；多模型金标 P/R/F1 因网关仅 1 稳定模型而 NOT_MEASURED"
}
```

## 诚实声明（§0.4）

- 未达 PASS 项（§120）：SYSTEM_MEMBERSHIP=NOT_MEASURED; FLOW=FAIL_CAPABILITY_ABSENT; STRUCTURAL_GAP_ENGINE=NOT_MEASURED; RESEARCH_ENGINE=NOT_MEASURED; DIGITAL_HUMANITIES_BENCHMARK=FAIL_PROXY_ONLY(mean=0.917,needs_real_benchmark); GOLDEN_TEN=PARTIAL(admitted=9/20,flows=0); CLEAN_ROOM=PASS(report 2026-09-13 03:29); BURN_IN=PARTIAL_GAIN(cycles=3); CULTURAL_SYSTEM_AUTONOMOUS_GROWTH=RUNNING(daemon cycle 43)
- 按 §0.4：代码完成/SQL成功/HTTP200/数据库有数据均不视为完成；完成只由验收门禁决定。