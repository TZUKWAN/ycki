# PROJECT STATE

## 数据安全操作指南（2026-09-11 新增）

### 三层数据保护体系

| 层 | 数据 | 存储位置 | 保护机制 |
|---|---|---|---|
| **Canonical KG（正式知识）** | 27,563 实体 / 4,419 ADMITTED Claims | PostgreSQL | ✅ 最可靠——独立数据库，不受 LightRAG 文件损坏影响 |
| **LightRAG 检索图谱** | 2,671 nodes / 1,585 edges | GraphML 文件 | 原子化写入 + 每日自动备份 |
| **向量库** | vdb_*.json | 大文件（GB级） | 可从 chunk 数据重建 |

### 防丢失规则

1. **正常关机前**：双击 `停止长江文化知识库.bat`（等 30 秒让容器优雅停止）
2. **每日自动备份**：Windows 任务计划 `YCKI-Daily-Backup` 每天 02:00 执行
3. **每周完整备份**：`YCKI-Weekly-Backup` 每周日 03:00 执行
4. **手动备份**：双击 `备份数据.bat`

### 如果发生数据丢失

**不要慌**——按优先级恢复：

1. **检查 PostgreSQL Canonical KG**：永远完好（这是正式知识层）
2. **检查 LightRAG 备份**：`data/backups/lightrag/latest/` 有最近的 GraphML
3. **启动脚本会自动检测损坏**并从备份恢复（已内置）
4. **如果备份也丢了**：Canonical KG 还在，检索图谱可以从 chunk 数据重建（`python tools/rebuild_canonical.py --all`）

### 当前备份状态

- 最近备份：2026-09-11 18:29:45
- 备份位置：`D:\长江学论纲\ycki\dataackups\`
- GraphML 备份：2,671 nodes / 1,585 edges ✓
- PostgreSQL 备份：57 张表 ✓

---


> 当前执行状态快照 · 更新时间：2026-09-06（M2 数据库批1建成并验证）

## 当前位置

**Milestone 2：长江文化 Schema + Resource Layer** — ✅ 核心完成
- T03 PostgreSQL/PostGIS 真实库表建成（sources/resources/collection_jobs + 视图）
- T04 领域本体经 ENTITY_TYPE_PROMPT_FILE 注入并实测生效（14 类全在用）
- T05/T06/T07/T08/T10 以真实管线形态落地（采集→入湖→注册→宿主入库全链）
- 批1–6 数据建成：1,172 资源/297 源/492 万字/26,316 实体，全链核验 99.94% 闭合
- 详见 `reports/COLLECTION_REPORT_BATCH1.md`

**重构启动（2026-09-08，docs/REFACTOR_PHASE0_AUDIT.md）**：明确双层图谱——
- Retrieval Graph（LightRAG 索引）：9.9 万实体/12.3 万边，仅检索用，**不再称为知识图谱**
- Canonical KG（正式知识，canonical_v1 管线）：已建 16 张表+41 谓词本体+全准入流水线，存量 1,347 资源重评后台进行中
- 冻结：auto_growth 更名 legacy_seed_collector、probe 写库废除（改官方 recovery）、heal 重名修复、15 篇测试文档清出生产库
- 审计实测：Scope 7/8、ER 6/6、溯源闭环 100%、证据定位率 100%（reports/KG_QUALITY_AUDIT.json）
- 覆盖缺口实测：136 个（25 省零覆盖/139 单来源/75 冲突/13 未消歧）→ 后续 Gap 驱动
**主模型**：2026-09-07 起切换 Qwen3.6-35B-A3B（亚秒级、稳定；Qwen3.5-122B 网关后期不稳，用户指定切换）
**canonical_v1 冻结（2026-09-10）**：十 Gate 全 PASS（reports/FINAL_VALIDATION_REPORT.md）。Canonical 27,617 实体 / 2,996 事件 / 4,431 ADMITTED Claims（全带证据）。
**M3 Claim-Evidence-Provenance 已建成（canonical_v1，2026-09-09/10）**：
- 十阶段准入管线 + 41 谓词 v1.3 受控本体 + 四级 ER 漏斗（同名消歧/沿革分裂）+ 证据原文绑定
- 全量重评完成：1,679 资源 → 27,187 Canonical 实体 / 2,886 事件 / 4,660+ ADMITTED（全带原文证据）
- 质量实测：Scope 8/8、ER 金标 30/30、溯源闭环 100%、证据重定位 98%、假合并 0.18
- Phase 15 Gap 闭环上线：137→111 缺口（自动收敛 18），Gap→ResearchTask→采集→准入 可循环
**续采方式**：仿照 `yangtze/topics_batch*.json` 新增主题表 → `python tools/collect.py --batch batchN --topics ... --max-total N`（断点续跑、双去重，10 分钟 Bash 上限被杀后原命令重跑即可）

## 运行中的服务

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| LightRAG Server | 9621 | WebUI `/webui`（API Key 见 `deploy/lightrag/.env`），本体已注入 |
| ycki-postgres | 5433 | postgis/postgis:16-3.4，库 `ycki`（postgres/ycki_pg_2026） |
| SearXNG | 8080 | 本机已有容器，engines=bing,sogou 可用 |

## 常用命令

```bash
python tools/collect.py --batch batch2 --topics <topics.json> --max-total 300   # 增量采集
python tools/reconcile.py        # LightRAG 状态 → PG 回写
python tools/verify_chain.py     # 全链关联核验
python tools/verify_queries.py   # 跨主题抽检+引用溯源
```

## 阻塞项

- 无。百度百科反爬封锁（以维基+政府/媒体源替代）；JS 渲染页留待 Playwright 批次——均已记录于采集报告 §5。

## 下一步（M3 起按里程碑顺序）

1. T14–T15：Claim/Evidence/Provenance 对象与准入状态机（复用已打通的 entity→chunk→resource 链）
2. T12：实体消歧漏斗（规范名表优先，Graphiti/KAG 机制移植）
3. T06.2：UNKNOWN 权威级站点的人工/LLM 分级补齐
4. batch2 采集扩充（主题轴其余条目 + Playwright fallback）
