# DECISIONS — 技术决策记录（ADR）

> 每条决策记录：背景/决策/理由/代价/替代方案/是否可逆。新增决策追加在末尾，编号递增。

## ADR-001 主底座选择 LightRAG（2026-09-06）

- **背景**：需要宿主平台提供 ingestion/抽取/双索引/GraphRAG/WebUI/API 全套能力，禁止自研框架。
- **决策**：以 HKUDS/LightRAG（main@440d25b0）为宿主，fork 维护，扩展层放 `yangtze/ extensions/ adapters/ plugins/`。
- **理由**：六个候选中唯一同时原生具备 文档摄取+KG 自动构建+混合检索+WebUI+REST API+多存储后端 的单项目；MIT 许可；社区活跃（2026-09 仍有合并）。
- **代价**：受其数据结构约束；部分定制需侵入式改造（记录到 UPSTREAM_PATCHES.md）。
- **替代**：KAG（部署重、依赖 SPG 全家桶）、Neo4j Builder（偏 UI、抽取弱）、Graphiti（非文档摄取向）——均只借鉴。
- **可逆性**：中。扩展层与核心解耦设计，必要时可换宿主。

## ADR-002 双图模式（2026-09-06）

- **决策**：保留 LightRAG 原生 Entity/Relation 图作为 Retrieval Graph；新增经 schema/ER/证据/准入的 Canonical Knowledge Graph。
- **理由**：见方案 §33–34。避免强迫全量高精度；保持 upstream 可合并性。

## ADR-003 LLM/Embedding Provider（2026-09-06）

- **决策**：全部走 OpenAI 兼容协议接入用户网关 `http://218.197.140.7:3001/v1`；LLM=`Qwen3.5-122B-A10B`，Embedding=`bge-m3`（同端点）。密钥仅存 `config/.env`（已 gitignore）。
- **验证**：2026-09-06 实测 `/v1/models` 返回 200，含上述模型。
- **注意**：网关无 rerank 模型 → T01.6 确认后决定 reranker 本地（如 bge-reranker）或暂禁。

## ADR-004 存储四件套（2026-09-06）

- **决策**：V1 = LightRAG 内置存储 + PostgreSQL/PostGIS + Neo4j + MinIO；不提前引入 Qdrant/Milvus/OpenSearch。
- **理由**：Complexity on Demand（方案 §48–49）。

## ADR-005 研究工作流为单状态机（2026-09-06）

- **决策**：Deep Research 用单工作流状态机 + 持久化任务对象实现；禁止多智能体形式化拆分。

## ADR-006 借鉴不拼装（2026-09-06）

- **决策**：KAG/Graphiti/GPT-Researcher/ScrapeGraphAI/Neo4j Builder 一律不作为运行时依赖整体引入；按机制借鉴重写或局部复用，逐项过"七问"（为何需要/用哪模块/接口/替换成本/维护成本/License/可否独立移除）后记入本文件。
- **例外通道**：若审计证明某库某模块可低成本独立引入且收益显著，单开 ADR 论证。

## ADR-007 Git 策略（2026-09-06）

- **决策**：fork 内 `upstream` 远程指向 HKUDS/LightRAG；对原生文件的每一处修改登记 `docs/UPSTREAM_PATCHES.md`；扩展能力一律新增文件/目录，不改签名。

## ADR-008 领域 Schema 注入走 ENTITY_TYPE_PROMPT_FILE（2026-09-06，审计后）

- **背景**：审计确认 LightRAG 支持 `ENTITY_TYPE_PROMPT_FILE` YAML 整体替换实体类型指南+抽取示例（`addon_params.py` L49 → `prompt.py:resolve_entity_extraction_prompt_profile` L803）。
- **决策**：T04 长江文化 16 类实体类型与抽取示例**纯配置注入，不改 operate.py/prompt.py**。
- **代价**：受 YAML 画像能力边界限制（gleaning、示例数量）；若未来需要 JSON 结构化输出的强 schema，再评估 `ENTITY_EXTRACTION_USE_JSON` + 代码兜底（借鉴 KAG 双层约束）。

## ADR-009 Claim/Evidence 外挂存储 + 外挂路由（2026-09-06，审计后）

- **背景**：LightRAG 数据模型固定为 entity(6 字段)/relation(7 字段)，无 Claim/Evidence 一等对象；核心文件 6-7K 行不宜改。
- **决策**：Claim/Evidence/Provenance/Admission/Registry 存 YCKI 自有 PostgreSQL（M2 建），REST 经独立 FastAPI 服务（`/yangtze/*`），用 LightRAG 的 `source_id`(chunk)/`doc id`/`file_path` 与宿主图谱对齐（T01 已实测 `/query/data` 提供该链路）。
- **替代否决**：把 Claim 塞进 entity_type 走 YAML（表达力不足）；直接改 operate.py 增加记录类型（维护成本不可接受）。

## ADR-010 机制移植清单（2026-09-06，审计后）

- **决策**：以下机制按 `OPEN_SOURCE_AUDIT.md` §3.2 借鉴重写（均 Apache-2.0/MIT，保留署名）：Graphiti 四时间字段+失效裁决（Claim 生命周期）、Graphiti+KAG 消歧漏斗（规范名表优先）、KAG 双层 schema 约束与 PPR 检索、GPT-Researcher retriever 契约+deep-research 算法（修复上游 NameError）+爬取质量守卫（CJK 感知）、ScrapeGraphAI 三节点+schema 注入+容错解析（自实现 300–500 行）、Neo4j Builder 摄取面板 UX（SSE 进度/断点/取消）。
- **不引入**：ScrapeGraphAI 依赖、KAG/OpenSPG server、Graphiti 运行时、GPT-Researcher 报告层与 multi_agents、Neo4j Builder 代码栈、RAG-Anything（宿主原生多模态已覆盖）。

## ADR-011 上游跟随策略（2026-09-06，审计后）

- **决策**：LightRAG 上游日更活跃（PR#3832+），基线 pin 至 `main@440d25b0` + Docker 镜像 digest `sha256:5bdbd524931b…`；升级节奏由我们控制（vendor 分支小步跟版），每次升级重跑基线脚本 `deploy/baseline_api.py` 回归。
- **注意**：注册表陈旧项 `AGEStorage`/`ChromaVectorDBStorage` 不可选（模块缺失，选中即 ImportError）；server 无 OpenAI 兼容端点（仅 Ollama 兼容），对外 API 需求走 YCKI 自有网关。

## ADR-012 Reranker 降级与恢复路径（2026-09-06，T01）

- **决策**：基线阶段 `RERANK_BINDING=null`；M6 前恢复方案优先级：① 用户网关增加 rerank 模型（零改动，RERANK_BINDING=cohere 指向 /rerank）；② 本地 vLLM 部署 `BAAI/bge-reranker-v2-m3`（env.example 有完整示例）。在此之前查询依赖 `KG_CHUNK_PICK_METHOD=VECTOR` 默认通道。

## ADR-013 数据采集双源：维基百科官方 API + 本机 SearXNG（2026-09-06，M2）

- **决策**：SearchProvider 首批两个真实实现：① `WikipediaProvider`（zh.wikipedia.org MediaWiki API，search+extracts，遵循 UA 政策与限速退避）；② `SearxngProvider`（本机 SearXNG 127.0.0.1:8080，`engines=bing,sogou`，其余引擎实测被 CAPTCHA/不可用）。
- **实测依据**（2026-09-06）：baike.baidu.com、zhihu.com 等对一切 UA 返回 403（硬封锁）→ 列入 BLOCKED_DOMAINS 前置跳过（计入 skipped，不算失败）；sogou 搜索结果的 `/link?url=` 跳转页多数无静态正文 → 被质量守卫正确拒绝。

## ADR-014 维基百科按 B 级参考源归类（2026-09-06，M2）

- **决策**：zh.wikipedia.org/britannica.com 归 `GeneralWebsite / authority_level=B`（社区编辑但编辑流程规范的专业参考站），区别于一般 UGC（C 级）。权威级仅作证据信息之一（方案 §14）。

## ADR-015 Raw Lake 以本地目录承载，MinIO 后移（2026-09-06，M2）

- **决策**：批1 湖存储用 `ycki/data/lake/{raw,text}/<domain>/<res_id>.{html,txt,json}` 本地目录（对象键语义与 S3 一致），PG 登记路径与校验和。MinIO 延后到规模需要时接入（方案 §49 Complexity on Demand），迁移=按登记路径批量上传。

## ADR-016 运维：LightRAG 重启后需探针触发管道（2026-09-06，M2 实测）

- **现象**：docker restart 后 doc_status 中 PENDING/PARSING 积压不会被自动调度（busy=False，日志空闲）。
- **处置**：POST `/documents/text` 上传任意小探针文档即可触发调度器清扫 backlog。已写入采集运维手册与 BASELINE 补充。

## ADR-017 领域本体注入实证（2026-09-06，T04 完成）

- **决策**：`entity_type_prompt.yml`（14 领域类型+中文抽取示例，`yangtze_entity_types_v1`）经 `ENTITY_TYPE_PROMPT_FILE` 注入。**功能验证**：李冰→person、都江堰/岷江→watersystem；批1 实测类型分布 watersystem 256、site 249 等 14 类全部在用，Other/Unknown 仅 ~3%。

## ADR-018 免密本机访问（2026-09-07，用户要求）

- **决策**：LightRAG 绑定改 `HOST=127.0.0.1`（compose 端口发布随之仅限本机），移除 `LIGHTRAG_API_KEY`。WebUI/API 免密，外部网络不可达，符合 env.example 的本机安全模型。
- **影响**：`tools/*.py` 中 X-API-Key 头被服务端忽略，脚本无需改动。

## ADR-019 持续自增长系统（2026-09-07，用户要求"一直跑自动增长"）

- **决策**：双击 `启动长江文化知识库.bat` → 拉起 Docker Desktop/三容器/健康检查/管道探针 → 运行 `auto_growth.py` 常驻循环：轮换执行全部 `yangtze/topics_batch*.json`（每表每轮 ≤40 新增，断点续跑+双去重）→ 重排失败 → PG 对账 → 休眠 30 分钟进下一轮。
- **自愈**：每轮自动 `reprocess_failed`；顽固超时文档用 `tools/split_reinsert.py` 拆分重灌（零丢失）。
- **扩容方式**：新增 `yangtze/topics_batchN.json` 即被引擎自动纳入轮换。
