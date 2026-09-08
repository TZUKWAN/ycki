# COLLECTION REPORT — 长江文化数据库采集与验证（批1–6，持续滚动更新）

> 首版：2026-09-06（批1）· 批2–6 增补：2026-09-06 · 全部数字为系统实测，无任何模拟成分
> 系统：LightRAG(9621) + PostgreSQL/PostGIS(5433) + SearXNG(8080) + 采集管线，全部运行中

## 0. 批次进度总表（实时）

| 批次 | 主题数 | 检索词 | 状态 |
| --- | --- | --- | --- |
| batch1（十主题基准） | 10 | 71 | ✅ FINAL |
| batch2（补齐主题轴：饮食/教育/科技/移民/中外交流/宗教/民族/艺术/建筑/商业 + 支流/考古/红色/名城深化） | 14 | 81 | ✅ FINAL |
| batch3（当代生态与发展/古镇名村/名人与贬谪文学/战争军事/文献方志/当代水利/曲艺/口岸） | 8 | 51 | ✅ FINAL |
| batch4（历史名人/茶文化/水神信仰与船工/名山/工业遗产/现代桥港/国家文化公园） | 7 | 47 | ✅ FINAL |
| batch5（戏曲剧种/书院文教/老字号手工业/古代陂塘/府州古城/江河典故/近现代补充） | 7 | ~45 | ✅ FINAL |
| batch6（石窟大佛与世遗/红色桥渡/悬棺崖墓/会馆/水文化题刻/矶岸老街/陵寝） | 7 | ~25 | ✅ FINAL |
| batch7（名篇名址/故居学人/方言民俗/峡谷津渡/工业内迁与西南文教/支流补全/江鲜渔文化/文博） | 10 | ~48 | ✅ FINAL |
| batch8（江河文学名篇/源区与青藏/湖湘名士/赣鄱人文/巴蜀学术/下游市镇/近现代工业/当代文博） | 8 | ~44 | ✅ FINAL |

## 0.1 最终总量（batch8 FINAL + 队列 100% 排空后全库终检，2026-09-07）

| 指标 | 数值 |
| --- | --- |
| 注册资源（PG resources） | **1,432** 条（processed 1,417 + duplicate 15=顽固超时文档拆分重灌原件） |
| 信息源（PG sources） | **341** 域名（S=108，A=25，S/A 合计 133） |
| 正文总量 | **5,610,559** 字符 |
| LightRAG 文档 | **1,444 篇全部 processed，failed=0，pending=0**（100% 排空） |
| 知识图谱 | **99,533 实体 / 123,123 关系 / 4,683 chunks** |
| 实体类型 | person 19,678 · work 12,453 · place 12,035 · organization 11,342 · site 8,887 · concept 6,331 · artifact 6,197 · event 4,917 · watersystem 1,465 · heritage 773 等 16 类 |
| 抽取模型 | 前期 Qwen3.5-122B-A10B（网关后期不稳）→ **2026-09-07 切换 Qwen3.6-35B-A3B**（亚秒级响应，全部积压清零，用户指定） |
| 全链闭合率 | **99,519/99,533 = 99.99%**（未闭合 14 条引用全部来自 7 篇基线测试/探针文档，已知可解释）；chunk/doc 引用缺失 0 |

### 主题覆盖（截至 batch6，27+ 主题组）
水系与水利（含全部主要支流湖泊）· 考古与早期文明 · 历史文化 · 红色文化（含将军县/起义/会战）· 工业文化与开埠 · 文学文化（含贬谪文学）· 交通航运 · 城市文化（含古城老街口岸）· 非遗与民俗 · 名胜与生态 · 饮食 · 教育 · 科技 · 移民与人口流动 · 中外交流 · 宗教 · 民族 · 艺术（戏曲画派）· 建筑 · 商业（商帮会馆）· 当代生态与发展 · 文献方志 · 茶文化 · 水神信仰与船工 · 石窟大佛 · 水文化题刻 · 陵寝世遗

## 1. 结果总览（批1 基准实测，细节仍有效）

| 指标 | 数值 |
| --- | --- |
| 注册资源（PG resources） | **305** 条（含 14 条冒烟批） |
| 信息源（PG sources） | **107** 个域名，其中 S/A 级 **22** 个 |
| 正文总量 | **1,542,413** 字符（湖内 316 个正文对象 + 189 原始 HTML + 127 原始 API 响应） |
| 覆盖检索词 | 71 个（十主题 × 6–8 问） |
| LightRAG 文档 | 312 篇（含基线测试 7 篇），**失败 0** |
| 知识图谱 | **11,765 实体 / 约 1.2 万关系**（报告时刻，仍在增长） |
| 队列状态（报告时刻） | processed 96 · 排队/在处理 ~216 · failed 0 —— 持续自主消化中 |

### 主题覆盖（十主题全部到齐）
水系与水利、考古与早期文明、历史文化、红色文化、工业文化与开埠、文学文化、交通航运、城市文化、非遗与民俗、名胜与生态。

### 权威级分布（resources×sources 实测）
A=3、B=137、C=35、S=19、UNKNOWN=111。
S 级来源实例：www.gov.cn、www.cjw.gov.cn（长江水利委员会）、www.cq.gov.cn、3g.wuhan.gov.cn、jdz.gov.cn（景德镇）、www.emeishan.gov.cn、wgly.hangzhou.gov.cn 等。

### 域名 TOP（实测）
zh.wikipedia.org 127 · www.sohu.com 23 · hanyuguoxue.com 8 · gushiwen.cn 7 · hgcha.com 7 · ihchina.cn 6（中国非物质文化遗产网）· news.qq.com 5 · shidianguji.com 5

## 2. 采集管线（真实实现，代码位置）

| 组件 | 文件 | 说明 |
| --- | --- | --- |
| SearchProvider #1 | `adapters/wikipedia_provider.py` | 维基百科官方 MediaWiki API（search+extracts），UA 合规、429 退避 |
| SearchProvider #2 | `adapters/searxng_provider.py` | 本机 SearXNG，`engines=bing,sogou`（实测可用引擎） |
| 抓取器 | `tools/fetcher.py` | 轻量 HTTP + trafilatura 正文抽取 + 质量守卫（<300 字/词表 dump 拒绝）+ BLOCKED_DOMAINS 前置跳过 |
| 注册表 | `tools/registry.py` | PG sources/resources、URL 规范化、raw+text 双校验和去重、权威分级规则 |
| 编排器 | `tools/collect.py` | 搜索→抓取→入湖→注册→LightRAG 入库，断点续跑（canonical_url/text_checksum 双去重） |
| 对账 | `tools/reconcile.py` | LightRAG 文档状态 → PG resources 真实回写 |
| 建库脚本 | `deploy/sql/001_init.sql` | sources/resources/collection_jobs + PostGIS/pg_trgm + 统计视图 |

## 3. 数据质量与关联核验（全部实测通过）

### 3.1 实体类型分布（长江文化本体生效证明）
place 562 · artifact 368 · organization 367 · **watersystem 256** · **site 251** · person 238 · concept 194 · event 170 · work 164 · institution 60 · naturalobject 55 · route 44 · practice 26 · heritage 74 …
14 类领域类型全部在用；Other/Unknown ≈ 2.3%。功能验证：李冰→person、都江堰/岷江→watersystem。

### 3.2 全链关联核验（Knowledge→Chunk→Document→Resource→Source）——batch6 FINAL 后复测
- 实体 **26,316** 中 **26,301（99.94%）可闭合回溯**到 PG 资源及其来源 URL
- chunk 引用缺失 **0**、doc 引用缺失 **0**
- 剩余 54 条引用来自 7 篇基线测试/探针文档（有意不入湖，已知可解释）
- 复核命令：`python tools/verify_chain.py`（随队列消化数字持续增长）

### 3.3 跨主题抽查询证（10 问，hybrid 模式）
- 回答准确率抽检：汉阳铁厂（张之洞/1890 奏准/1894 投产/1908 合并汉冶萍）、屈原（战国/《离骚》）、十年禁渔（2020-01-01/332 保护区）、都江堰（李冰/三大主体工程）等均正确
- **引用回查 39/40 成功**：每条引用可反查 PG 得到真实 URL+权威级（唯一未映射为基线测试文档）
- 诚实拒答验证：卢作孚专题尚未处理完成时，系统如实回答"无法回答"而非编造 —— 符合"禁止把模型输出当数据库真相"原则

## 4. 过程中发现并修复的真实问题（工程留痕）

| # | 问题 | 修复 |
| --- | --- | --- |
| 1 | 百度百科/知乎对一切 UA 返回 403（硬封锁），冒烟测试失败率虚高 | 前置跳过（BLOCKED_DOMAINS），计入 skipped 而非 failed；维基 API 顶上百科深度 |
| 2 | 带端口域名 `host:10443` 生成 Windows 非法目录名 | `lake_safe()` 域名安全化 |
| 3 | 维基 API 429 限速 | Retry-After 退避 + 调用间隔 2s |
| 4 | 容器重启后管道不自动恢复（busy=False 挂空） | 小探针文档触发调度器清扫 backlog（写入 ADR-016） |
| 5 | 对账用 UUID 覆盖 file_source 映射键，引用回查一度 0/40 | 新增 `lightrag_file_source` 列双键并存 + 存量回填 49 行 → 回查恢复 39/40 |
| 6 | GraphML 属性为纯文本 key（非 JSON）、多 chunk 分隔符为 `<SEP>` | 解析器按真实结构重写 |
| 7 | 抽取偶发越类型实体（如把"单刀赴会"当类型）与输出截断 | 白名单正确拒绝（设计行为）；`OPENAI_LLM_MAX_TOKENS` 提至 8000 |

## 5. 诚实边界（当前限制，后续批次改进）

1. 队列仍在消化（报告时刻 ~216 篇在途，0 失败），最终实体数将高于本报告——用 `python tools/reconcile.py` 与 `/documents/status_counts` 随时查看。
2. 批1 为 HTML 轻量抓取：JS 渲染页（部分政府/媒体站）被质量守卫拒绝，后续批次引入 Playwright fallback（方案 §17 已规划）。
3. 百度百科（内容最全的百科源）因反爬封锁暂不可达，未绕过（合规原则 §19）；以维基+政府/媒体源替代。
4. authority UNKNOWN=111 为无法规则判定的长尾站点，保留人工/LLM 分级待做（T06.2）。
5. Claim-Evidence 层（M3）尚未启动：当前图谱为 LightRAG 检索层 + PG 资源层，论证链是下一步建设重点。

## 6. 如何使用与运维

```bash
# 服务
docker ps   # lightrag-lightrag-1(:9621), ycki-postgres(:5433), searxng(:8080)
# WebUI: http://localhost:9621/webui/   (X-API-Key 见 deploy/lightrag/.env)

# 增量采集（断点续跑，天然去重）
python tools/collect.py --batch batch2 --topics yangtze/topics_batch2.json --max-total 300

# 对账 + 核验 + 抽检
python tools/reconcile.py
python tools/verify_chain.py
python tools/verify_queries.py

# 管道挂空时（重启后）
# POST /documents/text 传一条小探针即可（ADR-016）
```
