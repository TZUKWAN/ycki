# V2 FINAL RELEASE VALIDATION

- 生成：2026-09-14T07:16:11+0800
- HEAD：`dabfc6162e82`（§29：报告 commit 必须等于当前 HEAD）
- **OVERALL：FAIL**

## 硬门（§22.2）

- G01_REPRODUCIBILITY: **PASS** `{"verify_exit": 0}`
- G02_SECRET_CONFIG: **PASS** `{"hits": [], "count": 0}`
- G03_CANONICAL_V1_REGRESSION: **PASS** `{"claims_admitted": 4537}`
- G04_MEMBERSHIP: **FAIL** `{"precision": 0.9167, "recall": 0.8974, "f1": 0.9069, "cases": 1012, "protocol": "external deterministic gold + single-model blind judge x3 paraphrased prompts majority vote (Qwen3.6-35B-A3B); 非多模型金标", "note": "单模型判官+多数票`
- G05_TRADITION: **FAIL** `{"admitted": 17, "target": 50, "integrity": "PASS"}`
- G06_PROCESS: **FAIL** `{"admitted": 15, "target": 80, "integrity": "PASS"}`
- G07_FLOW: **FAIL** `{"flows": 16, "flow_types": 1, "target": 30}`
- G08_STRUCTURAL_RELATION: **PASS** `{"admitted": 7}`
- G09_GAP_QUALITY: **FAIL** `{"gap_precision": 0.8456, "total": 149, "protocol": "stratified real gaps + deterministic injected fakes; single-model 2-neutral-paraphrase majority judge (如实标注：判官跨提示方差±0.1，结果为诊断值)", "note": "单模型判官跨提示方差±0.1（多次运行 0.79~0.8`
- G10_RESEARCH_TASK: **FAIL** `{"resolved": 2, "target": "12/20 burn-in"}`
- G11_DIGITAL_HUMANITIES: **NOT_MEASURED** `{"answered": 204, "need": ">=300 questions answered"}`
- G12_GOLDEN_TEN: **FAIL** `{"passed": 0, "total": 10}`
- G13_COMPUTER_USE_UAT: **FAIL** `{"sessions": 2, "note": "任务表未满 100 条前不得 PASS"}`
- G14_RED_TEAM: **PASS** `{"evaluator_red_team": {"cases": 2130, "gate": "PASS", "error_pass_rate": 0.0}, "pipeline_red_team": {"cases": 2000, "breaches": 0}, "note": ""}`
- G15_GROWTH_50CYCLE: **FAIL** `{"cycles_available": 94, "cycles_with_structural_gain": 4, "gain_rate": 0.043, "target_rate": 0.6, "circuit_healthy_rate": 0.989}`

## 数量

```json
{
 "resources": 4348,
 "sources": 968,
 "source_domains": 962,
 "entities": 21978,
 "claims_admitted": 4537,
 "evidence": 4979,
 "traditions_admitted": 17,
 "processes_admitted": 15,
 "flows_total": 16,
 "flow_types": 1,
 "structural_relations": 7,
 "interpretations": 9,
 "gaps_open": 449,
 "tasks_resolved": 2
}
```