# PHASE 0 AUDIT — 重构前现状审计基线（2026-09-08）

> 依据：实际代码 + 实际数据库结构 + 实际运行配置（非文档宣称）。本报告为重构基线。

## 1. 运行状态

| 项 | 实测 |
| --- | --- |
| python 引擎/控制台进程 | 0 个（已停止，可安全冻结） |
| 容器 | lightrag-lightrag-1 / ycki-postgres / searxng 运行中 |
| git | main@531e7b8（GitHub TZUKWAN/ycki，私有） |
| LightRAG | 1,453 docs 全 processed；镜像 `ghcr.io/hkuds/lightrag:latest`（**未 pin 版本，违规**） |

## 2. 代码级问题清单（实证）

| # | 问题 | 证据 | 严重度 |
| --- | --- | --- | --- |
| P0-1 | **`heal_failed()` 同名函数重复定义**，后者覆盖前者 | auto_growth.py L115 + L140 | 高 |
| P0-2 | **probe() 向生产知识库写伪文档**（"自增长探针…"） | auto_growth.py L68；历史遗留"调度探针*.txt/引擎预检.txt/重启探针.txt"已入库 | 高 |
| P0-3 | **无资源准入**：collect.py 抓到即入 LightRAG，域外内容（三星香港/黄金网站等垃圾结果）混入 | tools/collect.py 全链；PG recent 中 samsung.com/goldsands 等记录 | 高 |
| P0-4 | **`ingest_status` 双重语义**：同时承担下载状态与知识准入状态 | deploy/sql/001_init.sql | 高 |
| P0-5 | **LightRAG Retrieval Graph 被当正式图谱宣传**："99,533 实体/123,123 关系"自称知识图谱 | README/PROJECT_STATE/dashboard 指标卡 | 高 |
| P0-6 | **实体以 name 为身份**：LightRAG entity_name 直接合并；同名必合并、别名必分裂 | LightRAG 机制 + 图谱实测（"李冰"/"李冰父子"并存） | 高 |
| P0-7 | **关系为自由 keywords 无向边**：无受控谓词、无方向、无 domain/range | LightRAG edge 结构（keywords/description/weight） | 高 |
| P0-8 | **无 Evidence 一等对象**：关系"证据"实为模型生成的 description | LightRAG edge description；无法回指原文 quote span | 高 |
| P0-9 | **weight 混淆可信度与提及次数**；无独立来源计数 | LightRAG weight 语义 | 中 |
| P0-10 | **近重复转载未识别**：仅 sha256 全等去重，转载链计为多来源 | tools/fetcher.py checksum 机制 | 中 |
| P0-11 | **topics/query 语义丢失**：采集上下文未持久化到资源 | resources 表仅存 search_query 字符串 | 中 |
| P0-12 | **生产 prompt 在 data/（被 gitignore）**：entity_type_prompt.yml 不在版本库 | deploy/lightrag/data/prompts/ | 中 |
| P0-13 | **配置硬编码**：Windows 绝对路径、LR URL、DB DSN 散落代码 | tools/*.py 多处 | 中 |
| P0-14 | **custom_topics.json 与 collect.py themes 结构不一致** + custom_collect.lock 无 stale 清理 | dashboard/app.py vs tools/collect.py | 中 |
| P0-15 | **"全链闭合率 99.99%" 指标名失真**：实为 Retrieval Entity Source Reachability，易误读为图谱准确率 | verify_chain.py / 报告 | 中 |
| P0-16 | **无 Event 对象**：多参与者历史事件被拆成 pairwise 无谓词边 | 图谱实测（南昌起义类共现边） | 高 |
| P0-17 | **无 TimeSpan/PlaceVersion**：时间仅字符串、古今地名混一 | LightRAG 属性 | 高 |
| P0-18 | **262 条资源上传失败未解决**（GP failed=262） | PG resources 状态分布 | 中 |
| P0-19 | **伪自增长**：固定主题表无限轮询 ≠ Gap 驱动增长 | auto_growth.py 循环逻辑 | 高 |

## 3. 数据现状（冻结基线，保留不删）

| 项 | 值 |
| --- | --- |
| resources | 1,703（processed 1,417 / failed 262 / duplicate 15 / uploaded 8 / pending 1） |
| sources | 447 域名 |
| 正文 | 649 万字（湖内） |
| Retrieval Graph 快照 | 99,533 entities / 123,123 relations（legacy，保留） |
| Canonical KG | **不存在**（0 表） |

## 4. 冻结动作（Phase 1）

1. `auto_growth.py` 更名 `tools/legacy_seed_collector.py`，职责降级为种子采集器；删除 probe 写库；恢复机制改用官方 `/documents/recovery/force_reset`（非写数式）
2. `heal_failed()` 合并为单一实现（保留 busy/pending/freeze 检查、fence 等待、超时重试、结构化日志）
3. Dashboard/README/PROJECT_STATE 指标重命名：Retrieval Entities / Retrieval Association Edges
4. 数据库迁移 `002_canonical_migration.sql`：新建 Canonical 层全部表（不动旧数据）
5. 修复 262 条 failed：走新的 Resource Admission 流程重新评估，而非盲目重传

## 5. 明确不做

- 不删除 LightRAG / 不改其核心代码（继续承担 chunking/检索/候选发现）
- 不逐条修改 12.3 万 Retrieval Edge（保留为 legacy 快照）
- 不为规模指标放宽准入
