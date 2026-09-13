# V2 FINAL RELEASE VALIDATION

- 生成：2026-09-14T04:41:47+0800
- HEAD：`e67190b30b1b`（§29：报告 commit 必须等于当前 HEAD）
- **OVERALL：FAIL**

## 硬门（§22.2）

- G01_REPRODUCIBILITY: **PASS** `{"verify_exit": 0}`
- G02_SECRET_CONFIG: **FAIL** `{"hits": [{"file": "HEAD:tools/generate_release_validation.py", "kind": "lightrag-key"}, {"file": "HEAD:tools/generate_release_validation.py", "kind": "pg-password"}], "count": 2}`
- G03_CANONICAL_V1_REGRESSION: **PASS** `{"claims_admitted": 4510}`
- G04_MEMBERSHIP: **FAIL** `{"precision": 0.9167, "recall": 0.8974, "f1": 0.9069, "cases": 1012, "protocol": "external deterministic gold + single-model blind judge x3 paraphrased prompts majority vote (Qwen3.6-35B-A3B); 非多模型金标", "note": "单模型判官+多数票`
- G05_TRADITION: **FAIL** `{"admitted": 7, "target": 50, "integrity": "PASS"}`
- G06_PROCESS: **FAIL** `{"admitted": 7, "target": 80, "integrity": "PASS"}`
- G07_FLOW: **FAIL** `{"flows": 5, "flow_types": 1, "target": 30}`
- G08_STRUCTURAL_RELATION: **PASS** `{"admitted": 7}`
- G09_GAP_QUALITY: **FAIL** `{"gap_precision": 0.8456, "total": 149, "protocol": "stratified real gaps + deterministic injected fakes; single-model 2-neutral-paraphrase majority judge (如实标注：判官跨提示方差±0.1，结果为诊断值)", "note": "单模型判官跨提示方差±0.1（多次运行 0.79~0.8`
- G10_RESEARCH_TASK: **NOT_MEASURED** `{"resolved": 0, "target": "12/20 burn-in"}`
- G11_DIGITAL_HUMANITIES: **NOT_MEASURED** `{"answered": 100, "need": ">=300 questions answered"}`
- G12_GOLDEN_TEN: **FAIL** `{"passed": 0, "total": 10}`
- G13_COMPUTER_USE_UAT: **FAIL** `{"sessions": 2, "note": "任务表未满 100 条前不得 PASS"}`
- G14_RED_TEAM: **PASS** `{"evaluator_red_team": {"cases": 2130, "gate": "PASS", "error_pass_rate": 0.0}, "pipeline_red_team": {"cases": 2000, "breaches": 0}, "note": ""}`
- G15_GROWTH_50CYCLE: **FAIL** `{"cycles_available": 69, "cycles_with_gain(计数法:结构总数>19)": 10, "note": "结构增量按报告快照计算，需 ≥60% 有真实增益"}`

## 数量

```json
{
 "resources": 4171,
 "sources": 894,
 "source_domains": 889,
 "entities": 21978,
 "claims_admitted": 4510,
 "evidence": 4952,
 "traditions_admitted": 7,
 "processes_admitted": 7,
 "flows_total": 5,
 "flow_types": 1,
 "structural_relations": 7,
 "interpretations": 9,
 "gaps_open": 436,
 "tasks_resolved": 0
}
```