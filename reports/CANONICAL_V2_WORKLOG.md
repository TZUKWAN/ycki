# CANONICAL_V2 执行工作日志

纪律：每任务一个 INSPECT→…→ACCEPT 闭环；状态只用 PASS/FAIL/BLOCKED/NOT_MEASURED/NOT_APPLICABLE。

## 2026-09-13 01:52 会话开始

- 起点 commit：`a757eb9`（宣称 Phase 7 完成）
- 截止：2026-09-13 08:55（到点暂停）
- 资源：主 Agent + 最多 2 个子智能体（用户本次明确授权）

### INSPECT 结果（运行库实况，ycki@docker:5433）

| 表 | 行数 | Git 来源 |
|---|---|---|
| cultural_systems | 8 (ROOT+7区域) | ❌ 无（yangtze/schema/cultural_systems.yaml 有定义但无 builder） |
| cultural_regions | 7 | ❌ 无（连 YAML 都没有） |
| cultural_domains | 93 | ❌ 无 builder（有 YAML） |
| historical_phases | 13 | ❌ 无 builder（有 YAML） |
| hydro_spatial_units | 25 | ❌ 无（无 YAML 无 SQL） |
| hydro_spatial_relations | 23 | ❌ 无 |
| hydro_place_mapping | 0 | ❌ 无 |
| system_memberships | 10004 | ❌ 无（且 schema 缺 goal #18.1 要求的锚点/派生/状态字段） |
| structural_relations | 14 | ❌ 无 |
| cultural_traditions / cultural_processes / process_stages / cultural_flows / transmission_routes / structural_gaps / structural_research_tasks | 全部 0 | ❌ 无 |

- structural_relations 14 条端点指向 canonical_entities 中的镜像实体（"XX文化系统" entity_type=Place），
  7 条 constitutes（受控本体可定义）+ 7 条 interacted_with/developed_from，**全部 evidence_count=0 且 ADMITTED → 违规**。
- 结论：**Phase 7 不得视为 PASS**。进入 Phase 7R。

### Task 7R-1 执行控制系统 + 漂移报告
- ACCEPTED：reports/CANONICAL_V2_EXECUTION_STATE.json、本文件、reports/V2_RUNTIME_GIT_DRIFT.md

### Task 7R-2 006_cultural_system_v2.sql
（进行中）

### Task 7R-3 007_structural_layer_v2.sql
（进行中）

### Task 7R-4 受控 seed YAML（hydro_spatial / cultural_regions）
（进行中）

### Task 7R-5 tools/init_canonical_v2.py
（进行中）

### Task 7R-6 Clean-room rebuild
（待做）

## 2026-09-13 02:00-04:00 推进记录

- 989be8a Phase 7R PASS：006/007 迁移 + seed YAML + builder + clean-room 0 漂移（修复 005 伪 SQL 存量 bug）
- 2394dbe 数字人文基准包（100题 + Golden Ten）
- 0fef200 Phase 10 PASS：本体验证器；领域树 §10.2 重分类（reclassify 确定性迁移挂载）
- bbb17d2 Membership 全量重建：4 锚点推导，92 ADMITTED / 1867 CANDIDATE，geo-only ADMITTED=0
- 81a5cc9 API v2 13 端点（主 agent 验收：25 测试过、零 SQL 拼接）
- a5feaa8 证据束+合成引擎：首批结构落库（9 ADMITTED，含湖广填四川/都江堰/端午竞渡/楚人南进/武汉开埠/永嘉南渡/川剧/编钟乐舞/蚕桑丝织SUPPORTED；徽商流动被硬门禁 REJECT——正确行为）
- e6eec80 缺口引擎(7检测器/527缺口) + 研究引擎(gap_id绑定) + growth v2 闭环 + validate_canonical_v2 全门禁 PASS
- Growth Cycle 1 后台运行中（真实采集 20 资源/任务）

## 2026-09-13 04:00-07:00 推进记录

- 1c475f2 文档/状态同步；7015f6a 最终报告生成器 + README/PROJECT_STATE + 解释层证据链（§45）
- 014bc3f 两阶段 Membership 准入：判官基准暴露 precision=0.25（裸地名实体无文化实质）→
  确定性预滤（Place 需过程锚 + §16.4 省级容器硬门禁）+ LLM 判官终审（带描述）→
  92 合格 → 9 ADMITTED（景德镇/苏州缂丝/荆州楚都/随县曾侯乙/成都蜀锦/安庆徽剧发源地等，
  全部可考文化实质）。基准复测 0.889（唯一分歧为盲判官看不到景德镇描述实质）。
  0.97 目标未达 → 如实记录，多模型金标受网关单稳定模型限制。
- e90d744 红队 8 家族 500 用例 0 突破（修复红队自身探针 bug 一次）；第二次 clean-room（001-008
  双次 apply 0 漂移）；burn-in 驱动器
- 406858d 结构谓词 Schema 2.0：35 谓词 §13 全字段，§14 全部 11 个高风险谓词 independent
  sources>=2（v1 缺失的 influenced 补齐）
- 故障注入单测（§102 等价）：LLM 坏 JSON falsy 处理 / 无证据 flow 拒绝 / 单来源不许 ADMITTED /
  空束 CANDIDATE。全套 pytest 30 passed。
- Burn-in 三轮（3/5/10 缺口）后台运行中

## 2026-09-13 04:00-05:00 Membership 质量深挖（诚实记录）

- burn-in 第三轮子进程使用中途保存的扩展代码（版本偏斜），暴露 Event/NaturalObject 被语义错位准入
  （事件是过程证据不是成员载体）→ 硬门禁修复（Event/语境要素/现代企业永不 ADMITTED）
- 推导扩展落地：+77 非地名成员行（武昌首义/马王堆发掘/铜绿山遗址/滕王阁/赣南采茶戏/陈尧佐等），
  ADMITTED 稳定在 23-24，全部真实载体
- 判官基准方法论结论：单模型环境下 §23 P>=0.97 不可独立测量——同模型证据丰富判官自洽不可作金标；
  信息饥饿盲判官一致率(0.52)为系统性偏低的诊断指标。多模型金标 NOT_MEASURED（网关仅 1 稳定模型）。
- 缺口闭合 reconcile 上线：3 条 RESOLVED；soak 时间盒启动（07:30 截止）

## 2026-09-13 04:50-05:10 Soak/答题引擎/守护进程

- Soak 10/10 轮完成，全程 §101 五项违规 = ZERO → SOAK_TEST PASS
- tools/dh_answer.py 上线：结构先行装配（系统/水系/分期+模式/传统/过程/流动/成员/解释/证据束）
  → 约束生成（仅可引用装配对象+EV标记）→ §87 七维确定性代理评估。首轮 100/100 mean=0.88；
  格式约束收紧后重跑中
- tools/growth_daemon.py 常驻启动：heartbeat=RUNNING_CYCLE → CULTURAL_SYSTEM_AUTONOMOUS_GROWTH=RUNNING
