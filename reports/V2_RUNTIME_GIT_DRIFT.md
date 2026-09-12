# V2_RUNTIME_GIT_DRIFT — 运行库 vs Git 复现性漂移报告

- 审计时间：2026-09-13 01:52 (+0800)
- Git HEAD：`a757eb9`（working tree clean）
- 运行库：PostgreSQL 16.4，容器 ycki-postgres，库 `ycki`

## 1. 结论

**当前 Phase 7 FAIL：运行库中的 canonical_v2 对象无法从 Git 重建。**

所有 16 张 v2 表的 DDL、约束、以及全部受控 backbone 数据（8 系统 / 7 区域 / 93 领域 /
13 分期 / 25 水系单元 / 23 水系关系）均无 Git 来源：没有 migration、没有 seed YAML（部分
缺失）、没有确定性 builder。数据由本地临时脚本写入后脚本即被丢弃，属于不可复现状态。

## 2. DB object ↔ Git source 对照

| DB object | 行数 | DDL 来源 | 数据生成者 | 算法版本 | seed | committed | 幂等 | 可复现 |
|---|---|---|---|---|---|---|---|---|
| cultural_systems | 8 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | cultural_systems.yaml(部分) | 否 | 否 | **FAIL** |
| cultural_regions | 7 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | ❌ 无 | 否 | 否 | **FAIL** |
| cultural_domains | 93 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | cultural_domains.yaml | 否 | 否 | **FAIL** |
| historical_phases | 13 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | historical_phases.yaml | 否 | 否 | **FAIL** |
| hydro_spatial_units | 25 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | ❌ 无 | 否 | 否 | **FAIL** |
| hydro_spatial_relations | 23 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | ❌ 无 | 否 | 否 | **FAIL** |
| hydro_place_mapping | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| system_memberships | 10004 | ❌ 无 | ❌ 临时脚本(丢失) | 未知(rule版本未记录) | ❌ 无 | 否 | 否 | **FAIL** |
| structural_relations | 14 | ❌ 无 | ❌ 临时脚本(丢失) | 未知 | ❌ 无 | 否 | 否 | **FAIL** |
| cultural_traditions | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| cultural_processes | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| process_stages | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| cultural_flows | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| transmission_routes | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| structural_gaps | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |
| structural_research_tasks | 0 | ❌ 无 | — | — | — | 否 | — | **FAIL** |

任何"表在哪里定义？谁 INSERT？算法版本？seed 在哪？"四问均无法回答 → 按目标 §4.2 判 FAIL。

## 3. 语义层违规（漂移审计连带发现）

1. **structural_relations 14 条全部 `status=ADMITTED` 且 `evidence_count=0`**
   - 7 条 `constitutes`：区域文化系统 → 长江文化。端点是 canonical_entities 中的镜像实体
     （entity_type=Place，名为"XX文化系统"），非受控 cultural_systems 表 → 类型混用。
   - 7 条 `interacted_with` / `developed_from`：高风险谓词，0 独立来源却 ADMITTED，
     违反 evidence policy（目标 §14、§26、§27）。
   - 处置：007 迁移中降级为 CANDIDATE 并标注 `knowledge_type`；`constitutes` 类改由受控
     本体定义（ONTOLOGY_RELATION），事实层镜像实体上的旧边降级为 SUPERSEDED。
2. **system_memberships 缺锚点结构**：无 status / anchor_count / derivation_method /
   spatial_temporal_domain_process 锚字段，10,004 条无法证明非 geo-only（§18–§23）。
3. **hydro_place_mapping 0 行**：水系↔行政区无显式映射（§16.4）。
4. **缺目标要求的对象**：macro_evolution_patterns、historical_phase_patterns、
   structural_relation_evidence、tradition_variants、tradition_evidence、
   process_participants、process_routes、process_evidence、cultural_landscapes、
   institutional_lineages、human_environment_interactions、interpretations、
   interpretation_evidence、structural_admissions（§5.1）。

## 4. 修复方案（Phase 7R）

| 步骤 | 交付物 | 验收 |
|---|---|---|
| 006 | deploy/sql/006_cultural_system_v2.sql：16 张运行表幂等重建（IF NOT EXISTS + DO 块加约束） | 干净库执行 exit=0，重复执行不破坏 |
| 007 | deploy/sql/007_structural_layer_v2.sql：§5.1 缺失对象 + membership/结构关系结构升级 + 证据违规数据降级 | 同上 |
| seed | yangtze/schema/hydro_spatial.yaml、cultural_regions.yaml（自运行库导出，人工复核水系事实） | 与 DB EXPECTED==ACTUAL |
| builder | tools/init_canonical_v2.py --dry-run/--apply/--verify/--manifest-hash | 幂等、事务化、manifest hash 稳定 |
| clean-room | 新建空库 ycki_cleanroom：001→007→builder→verify | drift=0, missing=0, unexpected=0, dup=0 |
| 降级 | interacted_with/developed_from 0 证据边 → CANDIDATE | ADMITTED evidence-less = 0 |

## 5. 运行库 DDL 快照来源

`pg_dump -s -t <16 tables>` 于审计时刻取得，重建后由 clean-room 验证取代本快照。
