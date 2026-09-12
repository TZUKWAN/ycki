# V2 FINAL VALIDATION

- 生成时间：2026-09-13T05:05:40+0800（脚本生成，§107）
- Git commit：49798b6
- **FINAL STATUS：FAIL**（§111/§120 规则）

## 阶段状态

- REPRODUCIBILITY: **PASS**
- ONTOLOGY: **PASS**
- HYDRO_SPATIAL: **PASS**
- SYSTEM_MEMBERSHIP: **PASS**
- STRUCTURAL_RELATION: **PASS**
- TRADITION: **PASS**
- PROCESS: **PASS**
- FLOW: **PASS**
- INTERPRETATION: **PASS**
- STRUCTURAL_GAP_ENGINE: **PASS**
- RESEARCH_ENGINE: **PASS**
- DIGITAL_HUMANITIES_BENCHMARK: **PASS(proxy_eval,mean=0.917)**
- GOLDEN_TEN: **PARTIAL(structures_partial,flows=0)**
- RED_TEAM: **PASS**
- CLEAN_ROOM: **PASS(2026-09-13 twice)**
- BURN_IN: **PASS_PARTIAL_GAIN**
- SOAK_TEST: **PASS**
- CULTURAL_SYSTEM_AUTONOMOUS_GROWTH: **RUNNING(daemon cycle 1)**
- CANONICAL_V1_REGRESSION: **PASS**

## 门禁指标

| Gate | 状态 | 指标 |
|---|---|---|
| G01 | PASS | `{"verify_exit": 0}` |
| G02/G03 | PASS | `{"ontology_errors": 0}` |
| G04 | PASS | `{"geo_only_admitted": 0, "admitted": 23, "candidate": 2013}` |
| G05 | PASS | `{"invalid_predicate": 0, "evidence_less_admitted": 0, "ontology_relations": 7}` |
| G06 | PASS | `{"admitted_without_policy_version": 0, "predicates_v2": 35, "high_risk_predicates_min2src": 11, "high_risk_missing": 0}` |
| G07 | PASS | `{"admitted_without_evidence": 0, "total": 6, "admitted": 3}` |
| G08 | PASS | `{"without_time_evidence": 0, "without_process_structure": 0, "total": 6, "admitted": 5}` |
| G09 | PASS | `{"missing_hard_fields": 0, "total": 0}` |
| G10 | PASS | `{"traditions_with_resource": 3, "traditions_total": 6, "processes_with_resource": 5, "processes_total": 6}` |
| G12/G13 | PASS | `{"gaps_open": 527, "gaps_resolved": 3, "tasks": 10, "false_resolution": 0}` |
| V1REG | PASS | `{"resources": 3734, "admitted_claims": 4394, "entities": 27625, "claims_without_evidence": 0}` |

## 数量盘点（§110）

```json
{
  "resources": 3734,
  "entities": 27625,
  "claims_admitted": 4394,
  "evidence": 4820,
  "systems": 8,
  "regions": 7,
  "hydro_units": 34,
  "hydro_relations": 46,
  "phases": 13,
  "domains": 93,
  "system_memberships": 10081,
  "memberships_admitted": 23,
  "traditions": 6,
  "processes": 6,
  "flows": 0,
  "structural_relations": 21,
  "interpretations": 9,
  "interpretation_evidence": 166,
  "interpretations_without_evidence": 0,
  "fact_only_entities": 17563,
  "gaps_open": 527,
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

- 未达 PASS 项（§120）：DIGITAL_HUMANITIES_BENCHMARK=PASS(proxy_eval,mean=0.917); GOLDEN_TEN=PARTIAL(structures_partial,flows=0); CLEAN_ROOM=PASS(2026-09-13 twice); BURN_IN=PASS_PARTIAL_GAIN; CULTURAL_SYSTEM_AUTONOMOUS_GROWTH=RUNNING(daemon cycle 1)
- 按 §0.4：代码完成/SQL成功/HTTP200/数据库有数据均不视为完成；完成只由验收门禁决定。