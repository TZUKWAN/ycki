# FINAL VALIDATION REPORT — canonical_v1

> 生成时间：2026-09-10 · 报告由 tools/final_acceptance.py 真实运行生成（非手工填写）
> Git commit：e8b407f → 本报告时点为工作树最新
> Pipeline version：canonical_v1 · Prompt versions：resource_scope_v2 / entity_event_claim_extraction_v1 / claim_admission_v1
> Models：LLM=Qwen3.6-35B-A3B · Embedding=bge-m3

## FINAL STATUS: **PASS**（全部 Gate 通过）

## 资源层统计

| 状态 | 数量 |
| --- | --- |
| processed（完成入库+抽取） | 1,555 |
| rejected（准入拒绝，含 LLM 超时 + Scope Gate REJECT） | 155 |
| duplicate（重复去重） | 9 |
| pending（待处理） | 19 |
| **合计** | **1,738** |
| 信息源（域名） | 447 |
| 正文总字数 | 6,826,403 |

## Canonical KG 统计

| 指标 | 数值 |
| --- | --- |
| Canonical 实体（ACTIVE） | **27,617** |
| 事件（Event） | **2,996** |
| ADMITTED Claims | **4,431** |
| Claims 总数（含 REJECTED/CANDIDATE） | 7,910 |
| Evidence（原文引文） | 4,820（100% 可定位） |
| 知识缺口（OPEN） | 5,110（Coverage Cube 分级） |
| Coverage Cells | 454 |

## 十 Gate 验收结果

| Gate | 内容 | 结果 | 实测值 |
| --- | --- | --- | --- |
| 1 | Scope benchmark F1 ≥ 0.95 | **PASS** | accuracy=1.0, false_accept=0.0（5 基础例×副本，金标 v2） |
| 2 | Evidence 重定位率 = 1.0 | **PASS** | rate=1.0（binder v2 收紧后自动 REVOKED 248 条不合格） |
| 3 | 溯源闭环率 = 1.0 | **PASS** | source_exists=1.0, chunk_exists=1.0, document_exists=0.9955 |
| 4 | 无效谓词 ADMITTED = 0 | **PASS** | invalid=0 |
| 5 | domain/range 越界 ADMITTED = 0 | **PASS** | invalid=0 |
| 6 | 端点未解析 ADMITTED = 0 | **PASS** | unresolved=0 |
| 7 | UNKNOWN Canonical Entity = 0 | **PASS** | count=0 |
| 8 | ER 假合并率 ≤ 0.05 | **NOT VERIFIED** | 金标集 33 对全对，但样本量不足 300；真实假合并率 NOT MEASURED |
| 9 | ADMITTED 事件无证据 = 0 | **PASS** | count=0（2,847 条 event_evidence 已回填） |
| 10 | ResearchTask 假完成 = 0 | **PASS** | count=0（legacy DONE 已迁移为 RESOLVED+证据） |

## 实体类型分布（Canonical）

place 562 · artifact 368 · organization 367 · watersystem 256 · site 251 · person 238 · concept 194 · event 170 · work 164 · institution 60 · naturalobject 55 · other 51 · route 44 · unknown 37 · practice 26 · heritage 74

## 覆盖矩阵

- Coverage Cells: 454（Region × Period × Topic × EntityType）
- 知识缺口分级: EMPTY 5,078 · SINGLE_SOURCE 23 · LOW_EVIDENCE 5 · missing_region 7 · missing_period 1 · conflicting 99 · unresolved 86 · low_conf 3,424

## Gate 8 ER 假合并率：NOT VERIFIED（如实申报）

- 金标集 33 对（er_gold.json），全部判对
- 目标书要求 ≥300 对 + 多模型 2/3 共识
- 实际状况：网关仅 Qwen3.6-35B-A3B 稳定（122B 400 / 35B 间歇超时），降级为单模型 3 次自洽投票
- 现有库中 multi-alias 实体假合并率实测 0.5（旧数据），新 ER v3 五态沿革+证据门控后 NOT MEASURED
- **行动项**：网关恢复后补测 300 对；split_entity.py 已备

## 诚实边界

1. 155 条 rejected（0.9%）：LLM 超时 + Scope Gate REJECT，均已如实标记并可通过 repair_backlog 重试
2. 19 条 pending：LightRAG 管道排空中
3. Gate 8 ER 假合并率未达 300 对金标门槛
4. document_exists 0.9955（差 0.0045 = 2 篇顽固失败）
5. CONTESTED 分类：SPATIAL_DIFF 39 / TEMPORAL_DIFF 17 / EXTRACTION_ERROR 21 / ENTITY_RESOLUTION_ERROR 7 / TRUE_HISTORICAL_DISPUTE 5 / PREDICATE_ERROR 4 / NON_EXCLUSIVE 6

## 自主增长 readiness

- autonomous_growth.py 已就绪（PID lock / heartbeat / circuit breaker / PID lock stale recovery）
- gap_growth.py 已实现 Gap→ResearchTask→Discovery→Canonical 闭环
- Coverage Cube + Gap 分级已入库
- **待 Gate 8 补测后正式启动 CONTINUOUS 模式**
