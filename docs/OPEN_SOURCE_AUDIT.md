# OPEN_SOURCE_AUDIT — 开源项目代码级审计与技术选择报告（T00 最终交付物）

> 审计日期：2026-09-06 · 方法：6 路并行代码审计（只读代理，逐文件核证，非文档转述）
> 仓库快照：LightRAG main@440d25b0（完整历史）；其余为浅克隆（审计时最新）
> 铁律执行：所有结论以**真实代码**为准，与方案文档冲突处已标注修正

---

## 1. 能力矩阵（●原生完备 ◐部分/需配置 ✗无）

| 能力 | LightRAG | KAG | Graphiti | GPT-Researcher | ScrapeGraphAI | Neo4j Builder |
| --- | --- | --- | --- | --- | --- | --- |
| 文档导入 | ● 多引擎(native/docx深解析/docling/mineru)+sidecar+断点恢复 | ◐ 需 SPG server 在线加载 schema | ✗ episode 非文档范型 | ◐ langchain loaders | ◐ 本地文件 | ● 完整上传 UI |
| 网页搜索 | ✗ | ✗ | ✗ | ● 21 retrievers(含 bocha/openalex/arxiv) | ◐ SearchGraph(DDG/Serper) | ✗ |
| 爬虫 | ✗ | ✗ | ✗ | ● bs/selenium+质量守卫(CJK感知) | ● 默认 Playwright+反检测 | ◐ requests+bs |
| KG 构建 | ● OpenIE 自动抽取+合并 | ● schema 约束+KnowledgeUnit | ● episode→实体/事实边 | ✗ | ✗(结构化抽取非图) | ● LLMGraphTransformer |
| Schema 约束 | ◐ ENTITY_TYPE_PROMPT_FILE YAML 注入(零代码) | ● prompt 注入+代码兜底双层 | ◐ 自定义类型 | ✗ | ◐ Pydantic schema→输出 | ● allowedNodes/Rels+三来源 schema 生成 |
| 增量更新 | ● filename+content_hash 双通道去重+图合并 | ◐ aligner 合并 | ● 增量 ER+事实失效 | ✗ | ✗ | ◐ 分批处理+断点 |
| 时序 | ✗ | ◐ 四元组条件属性 | ● bi-temporal 四字段+失效管线 | ✗ | ✗ | ✗ |
| GraphRAG | ● local/global/hybrid/mix/naive | ● 逻辑形式 4 算子推理 | ◐ 16 检索配方 | ✗ | ✗ | ◐ chat_bot+图查询 |
| Citation | ● reference_id+file_path 全链 | ◐ source 边回链 chunk | ◐ episodes 溯源列表 | ◐ [Source:URL] 仅靠 prompt 约束 | ✗ | ◐ HAS_ENTITY 建模可溯源 |
| WebUI | ● React19 管理端+workspace 双入口，12 语言 | ◐ OpenSPG 控制台(外部) | ✗ | ◐ nextjs 前端 | ✗ | ● React 完整摄取 UI |
| API | ● REST 完整 + Ollama 兼容 + Swagger | ◐ REST 全走 SPG | ● FastAPI+MCP server | ● FastAPI+WebSocket | ◐ 以库为主 | ● REST+SSE |
| 多模态 | ● VLM 分析阶段+图片/公式/表格 sidecar | ✗ | ✗ | ◐ 图片生成(非分析) | ✗ | ◐ 仅 YouTube 字幕 |
| 可扩展性 | ● 配置面+回调面+存储注册表 | ◐ 绑定 OpenSPG | ◐ 四驱动抽象重 | ● retriever/scraper 插件契约 | ◐ 绑定 langchain 全家桶 | ◐ 绑定 langchain+NDL 组件 |

**License**：LightRAG=MIT · KAG=Apache-2.0 · Graphiti=Apache-2.0 · GPT-Researcher=**LICENSE 文件为 Apache-2.0（pyproject 元数据误写 MIT，以 LICENSE 为准）** · ScrapeGraphAI=MIT · Neo4j Builder=Apache-2.0

**维护状态**：LightRAG 极活跃（审计前一天仍有多 PR 合并，PR#3832+）；Graphiti 极活跃（Zep 商业维护，最后提交 2026-09-04）；GPT-Researcher 活跃（v3.6.1，2026-08-23）；Neo4j Builder 活跃（2026-09-01 push，5.2k stars）；ScrapeGraphAI 活跃（v2.2.2，2026-08-27）；**KAG 维护明显放缓**（2025-07 后月均 <5 commits，0.8.0 未到 1.0）。

---

## 2. 主仓库确认：LightRAG（无重大技术障碍，维持选型）

完整审计见 §7.1。与方案假设的三处修正：

1. **规模修正**：核心三文件 6800–7800 行/个（pipeline/lightrag/operate），document_routes 7057 行——不是轻量原型。**深度 fork 修改核心文件的维护成本极高**，扩展必须优先走"配置面（env/addon_params/ENTITY_TYPE_PROMPT_FILE）+ 回调面（chunking_func）+ 外挂路由"。
2. **能力上调**：文档解析（原生 DOCX 深解析含标题/表格/公式/图片、docling/mineru 外部引擎、sidecar 中间格式）、多模态（VLM 分析阶段内建，**RAG-Anything 不在仓库内、也不需要引入**）、认证（API Key+JWT+bcrypt+限流）远超方案预期。
3. **API 修正**：server 暴露的是 **Ollama 兼容**（/api/chat 等）而非 OpenAI 兼容 server；无 /v1/chat/completions。

**基线实测佐证**（T01，`reports/BASELINE_REPORT.md`）：五模式问答全对、/query/data 返回 entities/relationships/chunks/references 四件套（含 reference_id+chunk_id+file_path）、删除联动清图、中文抽取质量高（SUMMARY_LANGUAGE=Chinese）。

### 对 YCKI 最关键的两个确认

- **领域 Schema 零代码注入**：`ENTITY_TYPE_PROMPT_FILE`（YAML，`lightrag/addon_params.py` L49 → `prompt.py:resolve_entity_extraction_prompt_profile` L803）可整体替换实体类型指南+抽取示例 → **M4 长江文化 16 类实体类型走此通道，不改任何上游文件**。
- **Claim/Evidence 无一等对象**：数据模型固定 entity(字段：entity_name/entity_type/description/source_id/file_path/timestamp)、relation(src/tgt/keywords/description/weight/source_id/file_path/timestamp)。**Claim/Evidence/Provenance/知识准入必须外挂**（自有 PostgreSQL 表 + 自有 REST 路由 + 用 source_id/chunk_id 与宿主图谱对齐）——这正是 YCKI 的核心增量价值所在。

---

## 3. 六项目技术选择：直接复用 / 借鉴重写 / 自建

### 3.1 直接复用（不改或仅配置）

| 能力 | 来源 | 说明 |
| --- | --- | --- |
| 摄取/抽取/检索/问答/引用/删除/增量 | LightRAG | 宿主全包，已基线验证 |
| 领域实体类型注入 | LightRAG `ENTITY_TYPE_PROMPT_FILE` | 纯 YAML 配置 |
| 存储 | LightRAG 注册表（Json/NetworkX 起步 → Neo4j/PG/Redis/Milvus/Qdrant/OS 可平滑切换） | 避开两个陈旧注册项：`AGEStorage`、`ChromaVectorDBStorage`（模块已不存在/移 deprecated，选中即 ImportError） |

### 3.2 借鉴重写（拿设计，不拿依赖）

| YCKI 模块 | 借鉴源 | 具体机制（已核证文件） |
| --- | --- | --- |
| **Claim 时序生命周期（M3 核心）** | Graphiti | ① 四时间字段 `valid_at/invalid_at/created_at/expired_at`（`graphiti_core/edges.py` L263-285）+ `reference_time` 升级为三重时间（文献形成时间/所述事件时间/摄取时间）；② 失效管线"**LLM 提名矛盾 + 确定性时序裁决 + 只打标记永不删除**"（`edge_operations.py` resolve_extracted_edges L325 / resolve_edge_contradictions L538-573）；③ 时间抽取纪律 prompt（禁造日期/锚定参考时间/不可解析置 null，`prompts/extract_edges.py` L242-270）——相对时间解析替换为**中国纪年转换器**（年号/干支/民国→ISO，LLM 只识别不换算） |
| **实体消歧漏斗（M4）** | Graphiti + KAG | 顺序反转：**规范名对照表（确定性，人名字号/古今地名）优先 → 归一化+MinHash 次之（`dedup_helpers.py` L88-131）→ LLM 兜底**；IS_DUPLICATE_OF 边模式（`edge_operations.py` L850） |
| **KnowledgeUnit 知识点中间层（M3/M5 可选增强）** | KAG | chunk 不直接拆三元组，先抽"知识点"（五类知识标签+领域本体链+核心实体+关联问 `relatedQuery` 反转成 `relatedTo` 边）（`kag/builder/component/extractor/knowledge_unit_extractor.py`）；双层 schema 约束=prompt 注入+代码校验兜底（不在 schema 落 Others，`knowledge_unit_extractor.py` L145-149） |
| **Discovery Engine 检索器抽象（M7）** | GPT-Researcher | `BaseRetriever` 契约：`search(max_results)` + `requires_scraping` 声明（`retrievers/base.py`，<100 行可原样重写）；21 个后端实现作参考（含 bocha/openalex/semantic_scholar/arxiv——正合方案 §19 学术 Adapter） |
| **Deep Research 状态机（M8）** | GPT-Researcher | breadth/depth/concurrency 递归研究算法、`{query, researchGoal}` 搜索规划、**learnings+citations（结论↔出处强绑定）** 产出格式（`skills/deep_research.py`）——直接作为 LightRAG 入库单元（自带 provenance）；注意上游 L409-417 有 NameError 缺陷，移植时修复 |
| **爬取质量守卫（M7）** | GPT-Researcher | 反爬页检测、**CJK 感知词表 dump 检测**、PDF 二进制重试、SSRF 校验（`scraper/scraper.py` L40-106、`utils/url_security.py`）——独立函数级移植，与框架无耦合 |
| **网页结构化抽取（M7 Web Acquisition）** | ScrapeGraphAI | 三节点流水线 Fetch→Parse→GenerateAnswer（`graphs/smart_scraper_graph.py` L97-128）+ "Pydantic schema→format_instructions 注入 prompt→容错 JSON 解析"闭环（`nodes/generate_answer_node.py` L138-161 + TolerantJsonOutputParser）——用 LightRAG 已有 openai 客户端+pydantic+httpx 复刻，**约 300–500 行** |
| **摄取任务 UX（M10 WebUI）** | Neo4j Builder | 文件表格+状态机+SSE 实时进度+断点续跑（START_FROM_LAST_PROCESSED_POSITION）+取消标志（`backend/src/main.py`）；"先定 schema 再抽取"三来源工作流+SchemaViz；按文档范围的受限子图查看器（label 勾选过滤+逐点展开）——LightRAG WebUI (React19+sigma.js) 内复刻 |
| **as-of-time 查询（M6 Temporal 通道）** | Graphiti | SearchFilters 时间过滤编译为 Cypher 的模式（`search_filters.py` L149-205）；YCKI 封装为一级 `as_of` 算子（valid_at<=t AND (invalid_at IS NULL OR invalid_at>t)） |
| **PPR 图文融合检索（M6 可选增强）** | KAG | 实体锚点 Personalized PageRank 传播到 chunk、与向量分数按 pagerank_weight 混合（`kag/common/tools/algorithm_tool/chunk_retriever/ppr_chunk_retriever.py`）——networkx 即可复刻 |
| **受限逻辑形式规划（M6 Query Router 参考）** | KAG | planner 输出限制为 Retrieval/Math/Deduce/Output 四算子 Step/Action 序列（`kag/solver/prompt/logic_form_plan.py` L12-66）——比自由 ReAct 可控可审计 |

### 3.3 自建（六个项目都没有，YCKI 真正的核心增量）

1. **Source Registry**（13 类信息源、S/A/B/C/UNKNOWN 权威级、crawl/rights policy）
2. **Raw Resource Lake**（checksum 去重、四权分离版权模型、parser_version 溯源）
3. **Claim-Evidence-Provenance 三层对象 + 知识准入状态机**（10 状态；Graphiti 只提供时序机制，无审核状态机——`pending→reviewed→canonical` 审核环节是 YCKI 必要扩展）
4. **Knowledge Gap Detection（9 类缺口）→ Research → 更新闭环**
5. **Evidence Package 组织器**（Claims/Evidence/Sources/GraphPaths/时空上下文/Conflicts，替代裸 chunk 注入）
6. **中国纪年转换器 + 长江流域时空体系**（上中下游/支流/湖泊/古今行政区沿革）
7. **Prompt/抽取结果版本化登记**（model/prompt_version/pipeline_version 元数据）

### 3.4 明确不引入（避免依赖地狱，逐项过七问后否决）

| 项目 | 否决理由 |
| --- | --- |
| ScrapeGraphAI 作为 pip 依赖 | langchain 全家桶 7 包 + playwright + 浏览器二进制 + requires-python>=3.12 + SaaS 遥测；而其精华（三节点+schema 注入+容错解析）MIT 许可仅数百行 |
| KAG / OpenSPG server | schema/搜索/图 API/PageRank 全走 REST 服务端，extractor 构造期即需在线 SPG server；维护已放缓；只抄设计与 prompt |
| Graphiti 作为运行时 | 四驱动抽象+全流程 LLM 依赖重；无审核状态机；Apache-2.0 允许只移植字段模型与裁决算法 |
| GPT-Researcher 报告生成层 | prompt-stuffing 式写文章，LightRAG query 层可替代≈100%；multi_agents LangGraph 与单工作流原则冲突 |
| Neo4j Builder 代码栈 | langchain+LLMGraphTransformer+NDL 私有组件，与 LightRAG 不同源；BYO-DB 安全模型不适配；只借 UX |
| RAG-Anything | LightRAG 仓库内已原生含多模态解析+VLM 分析，无引入必要（审计确认仓库无代码依赖） |

---

## 4. 修正记录（方案假设 vs 真实代码）

| 方案原假设 | 实际情况 | 影响 |
| --- | --- | --- |
| LightRAG 文档解析"是否用 docling/textract 待确认" | 自研 parser 注册表：native(docx 深解析/md/pdf/txt) + 外部 docling/mineru 引擎 + sidecar 格式；**不用 textract** | T09 直接用注册表路由 |
| LightRAG 支持 OpenAI 兼容 server | 仅 Ollama 兼容（/api/chat|generate） | 未来对外暴露需自建适配层 |
| "多模态利用 RAG-Anything 现有能力" | RAG-Anything 是独立仓库，LightRAG 原生多模态已覆盖 | V1 不引入 |
| KAG "kg-builder 模块化可局部复用" | 绑定 SPG server 深重，仅 prompt/算法可移植 | 已反映在 §3.2/3.4 |
| GPT-Researcher License=MIT | LICENSE 文件=Apache-2.0（元数据误写 MIT） | 按 Apache-2.0 对待，派生代码保留署名 |

---

## 5. 各项目审计要点存档

### 5.1 LightRAG（宿主）— 详见 §2 与 `reports/BASELINE_REPORT.md`
- 路由组：`lightrag/api/routers/{document,query,graph,ollama_api,ui_customization}_routes.py`；认证 `api/auth.py`（API Key + JWT/bcrypt/guest + WHITELIST_PATHS）
- 摄取链：upload→`apipeline_enqueue_documents`(pipeline.py L664, MD5 id, filename+content_hash 去重 L979-1030)→`apipeline_process_enqueue_documents`(L1644, PARSING→ANALYZING→PROCESSING)
- 抽取：`operate.py:extract_entities`(L3941)，gleaning 可控，实体 6 字段/关系 7 字段；JSON 模式 `ENTITY_EXTRACTION_USE_JSON`
- 查询：`kg_query`(L4588)/`naive_query`(L6592)；QueryParam 含 top_k/chunk_top_k/token 预算/hl/ll_keywords/rerank 开关
- 存储：base.py 三大基类+DocStatus；注册表 `kg/__init__.py:STORAGES`；默认 JsonKV/NanoVectorDB/NetworkX/JsonDocStatus
- WebUI：React19+Bun+Vite，`@react-sigma`+graphology，i18next 12 语言（含 zh.json）；双入口 /webui + /workspace；UI 内容包定制（UserDefinedUI.md）
- 扩展点结论：深度定制被迫修改 operate.py/prompt.py/document_routes.py/base.py（均 6-7K 行，高风险）→ **YCKI 策略：配置+回调+外挂路由，核心文件尽量零改动**

### 5.2 KAG（借鉴设计与 prompt）
- 双层架构：`kag/`(框架) + `knext/`(SPG 客户端)；0.8.0，Apache-2.0，维护放缓
- KnowledgeUnit 五类知识标签+本体链+关联问；三元组四元组含 condition
- 索引注册表带实测成本元数据（kag_hybrid_index 10 万字≈463 万 tokens/1425s）
- 检索 DSL：`kg_cs -> kag_merger <- kg_fr`（约束检索/融合/自由检索+PPR）

### 5.3 Graphiti（时序机制移植首选）
- graphiti-core v0.30.1，Apache-2.0，极活跃；30.6k stars
- EntityEdge 四时间字段（`edges.py` L263-285）；"LLM 提名+代码裁决"失效分层
- 三级实体消歧：余弦 0.6 → MinHash/Jaccard → LLM
- 检索：cosine/bm25/bfs × rrf/mmr/cross_encoder，16 配方；时间过滤编译为 Cypher
- 驱动：Neo4j/FalkorDB/Kuzu(已弃)/Neptune；OpenAI 兼容 endpoint 原生支持（openai_generic_client.py L98）

### 5.4 GPT-Researcher（Discovery/Research 骨架）
- v3.6.1，Apache-2.0（LICENSE 为准）；架构 agent→skills→actions→retrievers/scraper/llm_provider 分层干净
- retriever 契约干净（requires_scraping 解决 snippet/全文歧义，PR#2079）
- deep research：breadth/depth 递归+learnings+citations+followUp；上游 NameError 缺陷待修复后移植
- 中文适配：bocha retriever、CJK 感知内容守卫、dashscope provider 先例

### 5.5 ScrapeGraphAI（结构化抽取设计）
- v2.2.2，MIT，活跃；核心链路小而精，外围重（langchain×7+playwright）
- 借鉴三件套：Fetch→Parse→GenerateAnswer；Pydantic→format_instructions→TolerantJsonOutputParser；分块并行+merge+“找不到填 NA”约定

### 5.6 Neo4j LLM Graph Builder（UX 借鉴）
- Apache-2.0，活跃（5.2k stars）；FastAPI(backend/score.py)+React18+Vite(Neo4j NDL/NVL 组件)
- 摄取面板：状态机+SSE 进度+断点续跑+取消；schema 三来源+SchemaViz；受限子图查看器
- 图模型参照：Chunk-HAS_ENTITY->Entity、Chunk-PART_OF->Document、FIRST_CHUNK/NEXT_CHUNK 链+chunk 向量索引

---

## 6. 结论

1. **主仓库维持 LightRAG，无更换理由**（§2 三处修正均为"能力比预期强/假设偏差"，非障碍）。
2. YCKI 建设重心确认为：**外挂知识层**（Source/Resource/Claim/Evidence/Provenance/Admission/Gap）+ **配置注入领域 schema** + **借鉴四项目的成熟机制重写**（时序失效/消歧漏斗/retriever 契约/deep-research 算法/结构化抽取/schema 约束双层）。
3. 对上游策略：**pin commit（当前 440d25b0）+ 尽量零核心改动**；扩展走 `yangtze/ extensions/ adapters/ plugins/` + `ENTITY_TYPE_PROMPT_FILE` + 外挂 FastAPI 路由。
