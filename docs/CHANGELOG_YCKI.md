# CHANGELOG_YCKI — YCKI 扩展变更日志

> 只记录 YCKI 自有代码/文档变更；对 LightRAG 原生文件的修改另见 UPSTREAM_PATCHES.md。

## 2026-09-06 — 项目立项与 T00 启动

- 建立项目骨架：`ycki/{upstream,docs,yangtze,extensions,adapters,plugins,config,reports}`
- 克隆 6 个上游仓库（LightRAG 完整历史 main@440d25b0；其余浅克隆）
- 建立 9 个治理文档 + MASTER_TASK_LIST（T00–T31 全任务树）
- 写入用户 API 配置 `config/.env`（gitignore 保护）；实测网关可用模型：Qwen3.5-122B-A10B、bge-m3 等
- 派出 6 路代码审计代理（LightRAG 深度 + 5 参考项目）

## 2026-09-06 — T01 基线达成（M1 完成）

- Docker Desktop 启动，拉取官方镜像 `ghcr.io/hkuds/lightrag:latest`（1.5.7）
- 建立基线部署 `deploy/lightrag/`（compose + .env，含密钥已 gitignore）；代码零改动
- API 连通性验证：LLM=Qwen3.5-122B-A10B ✅（enable_thinking=false 生效）、Embedding=bge-m3@1024 ✅；定位并记录"Git Bash 终端中文编码污染请求体"运维坑
- 基线 18 项验证：17 通过、1 降级（Reranker 无服务端）→ `reports/BASELINE_REPORT.md`
- 新增工具：`deploy/make_test_docs.py`（中文 PDF/DOCX 生成）、`deploy/baseline_api.py`（基线 API 脚本）
- 发现本机已有 SearXNG 容器（127.0.0.1:8080），登记为 M7 SearchProvider 候选

## 2026-09-06 — T00 审计闭环（M0 完成）

- 6 路代码审计全部回收（LightRAG very-thorough + KAG/Graphiti/GPT-Researcher/ScrapeGraphAI/Neo4jBuilder）
- 交付 `docs/OPEN_SOURCE_AUDIT.md`：能力矩阵（13 能力×6 项目）、复用/借鉴/自建三清单、4 条方案修正记录、6 项目要点存档
- 架构文档升级 v0.2：确认五级挂载策略（配置面/回调面/外挂面/注册面/禁区）
- 新增 ADR-008~012（schema 纯配置注入、Claim 外挂存储、机制移植清单、上游跟随策略、Reranker 降级路径）
- MASTER_TASK_LIST：T00（16/16）、T01（14/14）全部勾销

## 2026-09-06 — M2 长江文化数据库批1建成（真实工程交付）

- T03：PostgreSQL/PostGIS 建库（ycki-postgres :5433）；MinIO 后移（ADR-015）
- T04：entity_type_prompt.yml 注入并实测生效（ADR-017）
- 真实采集管线：adapters/{searxng,wikipedia}_provider + tools/{fetcher,registry,collect,reconcile,verify_chain,verify_queries}
- 批1：305 资源/107 源/154 万字/71 检索词/十主题；S+A级源 22 个
- 图谱 11,765 实体；全链核验 99.86% 闭合、chunk/doc 引用零缺失；引用回查 39/40
- 修复 7 项真实问题（封锁域/Windows 非法目录/429/管道挂空/映射键覆盖/GraphML 解析/<SEP> 分隔）
- 报告：reports/COLLECTION_REPORT_BATCH1.md；新 ADR-013~017

## 2026-09-06 — 批2–6 持续采集（用户指令：不停）

- 六批 FINAL：batch2(14主题/81词) batch3(8/51) batch4(7/47) batch5(7/~45) batch6(7/~25)
- 累计：1,172 资源 / 297 源（S+A=102）/ 4,919,844 字符 / 湖 100MB
- 图谱 26,316 实体 / 30,167 关系；全链核验 99.94% 闭合（chunk/doc 引用零缺失）
- 首例失败=峨眉山 chunk 网关超时（480s），官方 reprocess_failed 重排，如实留痕
- 报告更新至批2–6：reports/COLLECTION_REPORT_BATCH1.md §0/§0.1

## 2026-09-07 — 批7/8 + 队列 100% 排空 + 模型切换（数据库建成）

- batch7（10主题/48词）、batch8（8主题/44词）FINAL；主题轴 27+ 组全覆盖
- 队历事件：宿主机重启 → Docker/容器恢复（ADR-016 探针法）；421 文件大作业自然完成
- 40 条 lightrag_upload 失败根因=大作业 manual_freeze 栅栏挡路 → 栅栏解除后全部补传成功（tools/fix_upload_failures.py）
- 15 篇顽固网关超时文档 → 按段落对半拆分重灌零丢失（tools/split_reinsert.py）
- **主模型切换 Qwen3.5-122B-A10B → Qwen3.6-35B-A3B**（用户指定；亚秒级、零超时；嵌入保持 bge-m3 不变）
- 终态：LightRAG 1,444 篇全 processed（failed=0）；PG 1,432 资源（failed=0）；图谱 99,533 实体/123,123 关系；全链闭合 99.99%；跨主题十问引用回查 38/40

## 2026-09-08 — 免密本机访问 + 持续自增长系统交付

- LightRAG 改 127.0.0.1 本机监听并移除 API Key（免密验证通过，数据完好 1,453 篇）
- 交付双击脚本：启动长江文化知识库.bat（拉 Docker→容器→健康检查→探针→自增长引擎→开 WebUI）、停止长江文化知识库.bat
- 自增长引擎 auto_growth.py：10 主题表轮换采集/自愈/对账循环（batch9 城市全覆盖、batch10 酒茶非遗已入库轮换）
- 修复引擎 ROOT 路径 bug；批9 冒烟 +7 条真实入库

## 2026-09-08 — 可视化控制台 + 自定义词条采集（响应"看不到增长/不能自设搜索条件"）

- 新增 dashboard/（FastAPI :9622）：资源/实体/关系/信息源/字数/队列/失败 七卡片实时总览、近14天每日新增柱状图、最新入库30条（带原文链接与状态）、引擎运行状态与暂停/恢复
- 自定义搜索词条：控制台粘贴词条 → 写入 yangtze/custom_topics.json → 一键"立即采集"（tools/collect.py custom 批次，锁防重入）→ 引擎每轮也会自动消化待办词条
- auto_growth.py 升级：心跳写 data/engine_state.json（控制台判活）、支持 data/engine_pause.flag 暂停、每轮优先消化自定义词条
- 启动.bat 同步升级：自动拉起控制台并打开 :9622 与 WebUI
- 端到端实测：添加"铜绿山古铜矿遗址/荆州博物馆"词条 → 立即采集 → 新资源入库（1,683→1,686）
