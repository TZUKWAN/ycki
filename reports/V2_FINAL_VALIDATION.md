# V2 FINAL VALIDATION

- 生成时间：2026-09-13T03:23:41+0800（脚本生成，§107）
- Git commit：014bc3f
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
- DIGITAL_HUMANITIES_BENCHMARK: **PASS(questions_only)**
- GOLDEN_TEN: **PARTIAL(structures_partial)**
- RED_TEAM: **NOT_MEASURED**
- CLEAN_ROOM: **PASS(2026-09-13)**
- BURN_IN: **CYCLE_1_DONE(_partial)_2_3_NOT_MEASURED**
- SOAK_TEST: **NOT_MEASURED**
- CULTURAL_SYSTEM_AUTONOMOUS_GROWTH: **CYCLE_MODE(手动触发)NOT_DAEMON**
- CANONICAL_V1_REGRESSION: **PASS**

## 门禁指标

| Gate | 状态 | 指标 |
|---|---|---|
| G01 | PASS | `{"verify_exit": 0}` |
| G02/G03 | PASS | `{"ontology_errors": 0}` |
| G04 | PASS | `{"geo_only_admitted": 0, "admitted": 9, "candidate": 1950}` |
| G05 | PASS | `{"invalid_predicate": 0, "evidence_less_admitted": 0, "ontology_relations": 7}` |
| G06 | PASS | `{"admitted_without_policy_version": 0}` |
| G07 | PASS | `{"admitted_without_evidence": 0, "total": 6, "admitted": 3}` |
| G08 | PASS | `{"without_time_evidence": 0, "without_process_structure": 0, "total": 6, "admitted": 5}` |
| G09 | PASS | `{"missing_hard_fields": 0, "total": 0}` |
| G10 | PASS | `{"traditions_with_resource": 4, "traditions_total": 6, "processes_with_resource": 5, "processes_total": 6}` |
| G12/G13 | PASS | `{"gaps_open": 527, "gaps_resolved": 0, "tasks": 3, "false_resolution": 0}` |
| V1REG | PASS | `{"resources": 3695, "admitted_claims": 4394, "entities": 27625, "claims_without_evidence": 0}` |

## 数量盘点（§110）

```json
{
  "resources": 3695,
  "entities": 27625,
  "claims_admitted": 4394,
  "evidence": 4820,
  "systems": 8,
  "regions": 7,
  "hydro_units": 34,
  "hydro_relations": 46,
  "phases": 13,
  "domains": 93,
  "system_memberships": 10004,
  "memberships_admitted": 9,
  "traditions": 6,
  "processes": 6,
  "flows": 0,
  "structural_relations": 21,
  "interpretations": 9,
  "interpretation_evidence": 166,
  "interpretations_without_evidence": 0,
  "fact_only_entities": 17621,
  "gaps_open": 527,
  "gaps_partial": 2,
  "gaps_resolved": 0,
  "tasks_resolved": 0
}
```

## Membership 判官基准

```json
{
  "sample_size": 117,
  "rule_admitted": 9,
  "admitted_precision": 0.8889,
  "candidate_uphold_rate": 0.7222,
  "judge_errors": 1
}
```

## 诚实声明（§0.4）

- 未达 PASS 项（§120）：DIGITAL_HUMANITIES_BENCHMARK=PASS(questions_only); GOLDEN_TEN=PARTIAL(structures_partial); RED_TEAM=NOT_MEASURED; CLEAN_ROOM=PASS(2026-09-13); BURN_IN=CYCLE_1_DONE(_partial)_2_3_NOT_MEASURED; SOAK_TEST=NOT_MEASURED; CULTURAL_SYSTEM_AUTONOMOUS_GROWTH=CYCLE_MODE(手动触发)NOT_DAEMON
- 按 §0.4：代码完成/SQL成功/HTTP200/数据库有数据均不视为完成；完成只由验收门禁决定。