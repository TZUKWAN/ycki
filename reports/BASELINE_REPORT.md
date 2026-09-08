# BASELINE REPORT — 原版 LightRAG 基线验证（T01）

> 执行日期：2026-09-06 · 执行人：YCKI 自动化流水线
> 结论：**基线全部通过（除 Reranker 无可用服务，已按降级方案禁用）**。T01 验收通过，M1 完成，可以进入 M2。

## 1. 部署形态

| 项 | 值 |
| --- | --- |
| 方式 | Docker Compose（官方镜像 `ghcr.io/hkuds/lightrag:latest`，digest `sha256:5bdbd524931b…`） |
| compose 位置 | `ycki/deploy/lightrag/docker-compose.yml`（复制自上游原版） |
| 配置 | `ycki/deploy/lightrag/.env`（含密钥，已 gitignore） |
| 代码改动 | **零**（原版镜像，未做任何修改） |
| 端口 | 9621（WebUI `/webui`、Workspace `/workspace`、Swagger `/docs`） |
| 卷 | `data/rag_storage`（工作区）、`data/inputs`（上传目录）、`data/prompts` |
| 版本 | core_version=1.5.7, api_version=0344 |
| 宿主 | Windows 10.0.26200 + Docker 29.1.2（Linux 引擎，16CPU/24GB） |

## 2. Provider 配置（用户网关，OpenAI 兼容）

| 角色 | 绑定 | 实测 |
| --- | --- | --- |
| LLM（extract/keyword/query/vlm 四角色） | `openai` → `http://218.197.140.7:3001/v1`，模型 `Qwen3.5-122B-A10B` | ✅ 连通 |
| Qwen3 思考模式 | `OPENAI_LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'`，启动日志确认四角色均已生效 | ✅ |
| Embedding | `openai` → 同网关，模型 `bge-m3`，`EMBEDDING_DIM=1024`，`EMBEDDING_SEND_DIM=false`，`EMBEDDING_USE_BASE64=false` | ✅ 连通 |
| Reranker | **网关无 rerank 模型 → `RERANK_BINDING=null` 禁用** | ⚠️ 降级 |

**重要运维发现**：网关本身对中文请求完全正常。此前用 Git Bash `curl -d` 直接发中文得到的 400 是**终端本地编码（GBK）污染请求体**所致；用 UTF-8 文件载荷（`--data-binary @file`）后中文聊天/嵌入均正常。后续所有脚本一律用 Python requests 或 UTF-8 文件载荷。

## 3. 功能验证结果（全部实测）

| # | 验收项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | Docker 启动 | ✅ | `docker compose up -d`，容器 `lightrag-lightrag-1` Up |
| 2 | WebUI 启动 | ✅ | `/webui/` → 200，标题 YCKI |
| 3 | API 正常 | ✅ | `/health` healthy；`/openapi.json` 可用 |
| 4 | LLM 正常 | ✅ | 启动日志 Role LLM Configuration 四角色就绪；抽取/问答实际调用成功 |
| 5 | Embedding 正常 | ✅ | 文档向量化成功；检索正常 |
| 6 | Reranker | ⚠️ 禁用 | 网关无 rerank 模型。降级方案：先用 `KG_CHUNK_PICK_METHOD=VECTOR` 默认通道；M6 前评估本地 vLLM 部署 `BAAI/bge-reranker-v2-m3` 或接入支持 rerank 的服务 |
| 7 | 上传 PDF | ✅ | `汉阳铁厂简介.pdf`（reportlab 生成中文 PDF）→ processed，1 chunk |
| 8 | 上传 DOCX | ✅ | `汉口开埠与长江航运.docx`（python-docx 生成）→ processed，1 chunk |
| 9 | 上传 TXT | ✅ | `武汉长江大桥.txt` → processed（用于删除测试） |
| 10 | 文档解析 | ✅ | 中文文本完整入库（含书名号、括号纪年） |
| 11 | Entity Extraction | ✅ | 34 实体，类型含 person/location/artifact/concept/organization，中文描述准确 |
| 12 | Relation Extraction | ✅ | 33 关系，description 完整句子且带 source_id/chunk 关联 |
| 13 | Knowledge Graph | ✅ | `/graphs?label=张之洞` 返回 12 节点 11 边子图 |
| 14 | Graph 查询 | ✅ | `/graph/label/list` 34 标签；`/graph/label/popular`、`/graph/entity/exists` 等路由在册 |
| 15 | RAG 回答 | ✅ | `naive/local/global/hybrid/mix` 五模式问答全部正确（张之洞/1890 奏准/1894 年 5 月投产） |
| 16 | Citation | ✅ | 回答附 `### References [1] 汉阳铁厂简介.pdf`；`/query/data` 返回 entities/relationships/chunks/references 四件套，chunk 带 `reference_id`+`chunk_id`+`file_path` |
| 17 | 删除文档 | ✅ | 删除大桥文档后：文档列表移除、图谱实体联动回落、共享实体 `龟山` 因仍被铁厂文档引用而正确保留（source_ids 机制生效） |
| 18 | 知识更新（增量导入） | ✅ | 三个文档先后入湖，实体/关系增量合并（如 `龟山` 双文档共现） |

## 4. 过程中发现的问题与处置

| 问题 | 根因 | 处置 |
| --- | --- | --- |
| curl 上传文件名乱码（GBK） | Windows curl 以本地代码页发送 multipart filename | 改用 Python requests 上传（`deploy/baseline_api.py`） |
| `GET /documents/paginated` 405 | 此版本该路由为 **POST**；删除为 `DELETE /documents/delete_document`（body: doc_ids[]） | 脚本已按 openapi.json 修正 |
| `/query/data` "error parsing the body" | 终端中文编码污染（同上） | UTF-8 文件载荷解决 |
| 首次删除使用了列表截断的 doc id | 列表展示截断为 14 字符 | 一律取完整 id 操作 |

## 5. 对 YCKI 后续阶段的关键输入（基线实测确认的扩展点）

1. **证据链骨架已存在**：`/query/data` 的 `entity/relation → source_id(chunk) → file_path` 链路正是 M3 Claim-Evidence-Provenance 的地基，无需改造即可挂接。
2. **`ENTITY_TYPE_PROMPT_FILE`**：env.example 确认支持外部 YAML 实体类型画像（`PROMPT_DIR/entity_type/`），M4 注入长江文化 16 类核心类型走此通道，**零代码侵入**。
3. **`SUMMARY_LANGUAGE=Chinese`** 生效，抽取描述为高质量中文。
4. **R chunker 默认 CJK 友好**（按 `。！？；，` 分割），适合古籍/现代汉语混排。
5. **多解析引擎路由**（`LIGHTRAG_PARSER=native/mineru/docling`）与 `MAX_*` 限流体系完整，M9 大规模灌数据时直接可用。
6. **工作区隔离**：容器内数据在 `data/rag_storage`，未来 PostgreSQL/Neo4j/MinIO 接入后按 storage backend 切换。

## 6. 性能粗测（单机基线，无rerank）

- 单文档（~600 汉字，1 chunk）抽取+入图：≈15–25s（含 LLM 往返）
- hybrid 问答端到端：≈10–20s（Qwen3.5-122B-A10B，非流式）
- 五模式连答：均无超时/限流报错

## 7. 验收结论

T01 十八项：17 通过、1 降级处置（Reranker，无可用服务端，非 LightRAG 缺陷）。
**基线报告通过，按里程碑规则解锁 M2（长江文化 Schema + Resource Layer）。**
