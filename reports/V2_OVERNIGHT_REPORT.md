# V2 OVERNIGHT ENGINEERING REPORT（2026-09-14 01:15–08:55）

基线：`2eaca50` 起算（此前 P0 反自证验收+密钥历史清洗已完成）。终态 HEAD 见文末。

## 一、评估体系重建（P0，§3）
- validate_canonical_v2 重写：每门禁带 sample_count/positive/negative/minimum/coverage；
  空样本 → NOT_MEASURED；Flow=0 → FAIL_CAPABILITY_ABSENT；G05 非法谓词对 v2 谓词表
  真实校验；G06 高风险独立来源校验；G10 溯源真实计算；禁止一切硬编码 PASS。
- 发布验收器 generate_release_validation.py：§22.2 十五硬门（G01–G15）统一
  PASS/FAIL/NOT_MEASURED/BLOCKED 语义。

## 二、DH 评估器真实化 + 评估器红队（§3.5/3.6）
- dh_eval：claim 分解 → 逐断言检查；假引用（不存在 EV）FAIL；引用格式错误 FAIL；
  断言-引文确定性蕴含（年代/朝代/字符重叠）+ LLM 严格蕴含（分块 10 对/次）；
  空间硬事实表（上中下游归属/分界）拒绝地理硬错误；状态投毒（CANDIDATE 冒充
  ADMITTED）检测；零证据装配的诚实拒答路径。
- 评估器红队 **2130 用例 / 16 攻击族**：关键族 1300/1300 全阻断，
  错误通过率 0.0%（<1% 达标）；语义族确定性泄漏 49 例由 LLM 蕴含复判 49/49 抓获。

## 三、引擎升级
1. **实体去重**（ENTITY_RESOLUTION 失败族根因）：同名+同类型簇，嵌入≥0.80 归簇
   + LLM 群裁兜底；**3,967 实体合并**、295 组保守分裂留档；引用全面改写
   （claims/events/participants/memberships/candidates/place_relations/aliases）；
   每簇 provenance_events 留痕。实体 27,630 → 21,978。
2. **Evidence Bundle v2**（§7）：lexical(trgm)/entity/event/graph/semantic/fulltext
   六通道 + 统一评分 + MMR 多样性 + 簇配额；充分度矩阵输出。
3. **研究规划器 + 来源策略**（§5/§6）：认识诊断、证据需求矩阵、三波查询
   （概览/补字段/矛盾搜索）、来源类谱 + site: 限定；collect 消费 provider 计划；
   PDF 通道（pdfminer，保留分页）；LAKE 路径设置化；resources.source_class 溯源
   （迁移 009）。
4. **增长闭环综合接入**（§9）：缺口 → 类型匹配结构综合（gap_synthesis）进入
   cultural_system_growth 主循环；研究任务查询由规划器生成；失败缺口降权。

## 四、能力突破
- **CulturalFlow 0 → 29**（含 ADMITTED 序列：川盐济楚/万里茶道/徽商沿江/沪汉粮运/
  汉冶萍煤铁/近代航运/知识传播），3 种 flow_type（COMMODITY_TRADE /
  KNOWLEDGE_DIFFUSION / BELIEF_DIFFUSION）。
- Traditions 6 → **20**（17 ADMITTED）；Processes 6 → **16**（15 ADMITTED）；
  种子库 20 → **221**（含 §10.1 强制流动 + §18 Golden Ten 组件 + 金标派生）。
- DH 真评估 **204 题 mean 0.898**（旧代理指标 0.917 系虚高；三轮修复评估器缺陷：
  蕴含分块、空证据诚实路径、引用格式前置示例）。

## 五、基准体系（全外部金标/确定性构造，如实标注单模型）
| 基准 | 规模 | 结果 | 门 |
|---|---|---|---|
| Membership 盲判（3 提示多数票） | 1012 例×9 族 | P=0.917 R=0.897 F1=0.907 | FAIL（目标 .97/.90/.93） |
| Gap 精度（抽样+注入假缺口） | 149（109 真实+40 注入） | precision 0.846 | FAIL（目标 .90） |
| 管线红队 | **2000** | 0 突破 | PASS |
| 评估器红队 | **2130** | 错误通过率 0% | PASS |
| DH 真基准 | 204 题 | mean 0.898 | NOT_MEASURED（§17 要求 300 题） |
| Golden Ten | 10 案 | 覆盖率 15–54% | FAIL |
| Burn-in 20 任务 | 12 执行 | 3 RESOLVED / 9 NO_GAIN | FAIL（目标 ≥12） |
| RC1 fresh clone | 4 步 | 编译/复现/本体/门禁 全 PASS | PASS |

诚实说明：Membership 与 Gap 为单模型判官（Qwen3.6-35B-A3B，3 提示多数票），
判官跨提示方差 ±0.1；未配置多模型金标通道（§12.2 无法满足，如实标注）。

## 六、系统运行
- PostgreSQL 一次崩溃：WAL 自动恢复，数据零丢失；容器已设 unless-stopped。
- growth daemon 换新循环常驻（120s 间隔），周期报告 76 份；熔断健康率 98.9%。
- Dashboard：/v2 主控台 + /graph 图谱页（vis-network：系统结构/区域互动/文化流动
  三视图），真实浏览器 UAT 会话 1（12 任务全 PASS）记录于 V2_COMPUTER_USE_UAT.md。

## 七、终态门禁（V2_FINAL_RELEASE_VALIDATION）
PASS：G01 复现 / G02 密钥(含历史重写后 0 明文) / G03 v1 回归 / G08 结构关系 /
      G14 双红队
FAIL：G04 Membership(0.907) / G05 Traditions(17<50) / G06 Processes(15<80) /
      G07 Flows(30✓,类型3<6) / G09 Gap(0.846) / G10 任务(2<12) /
      G12 Golden Ten / G13 UAT(未满 100 任务) / G15 增长增益率(5.3%<60%)
NOT_MEASURED：G11 DH(需≥300 题)
OVERALL = **FAIL**（§22：任何硬门未达即不发布；不以部分达标虚标）

## 八、剩余工作（按杠杆排序）
1. 采集持续供给 gt/flow 组件主题语料（每轮 ~30 分钟闭环，结构稳定 +5~10/轮）；
2. Membership/Gap 门槛需多模型金标通道（本地再部署 1 个判官模型即可启动）；
3. UAT 任务表补至 100+50 探索；DH 300 题在语料扩至 50/80 后重生成作答；
4. G12 十案组件逐案补证。
