# YANGTZE CULTURAL SYSTEM MODEL V2

> 本文档是 canonical_v2 的理论基础。所有代码实现必须服从本文档定义。
> 不是工程文档——是领域模型定义。

---

## 一、长江文化的定义

> **长江文化，是以长江干流、支流、湖泊及其关联流域空间为基本自然地理依托，
> 在长期的人地互动、生产生活、人口迁徙、族群交往、政治整合、商贸交通、
> 知识传播和文明交流过程中持续生成，
> 由不同历史时期和不同区域文化共同构成，
> 并通过长江水系及社会网络不断传播、交融、重组的
> 多层次、开放性、连续性文化体系。
> 它既包括史前文化、地域文化和中华优秀传统文化，
> 也包括近现代革命文化、工业与城市文化以及当代社会主义先进文化，
> 是中华文明形成、发展和多元一体格局的重要组成部分。**

---

## 二、定义到数据模型的逐项映射

| 定义要素 | 数据模型对象 | 说明 |
|---|---|---|
| 长江干流/支流/湖泊/流域 | HydroSpatialUnit (Basin/MainStem/Tributary/Lake/Delta...) | 自然地理底座，非行政区 |
| 人地互动 | HumanEnvironmentInteraction | 水→人→文化的关系 |
| 生产生活 | ProductionSystem / LivelihoodPattern | 稻作、渔猎、航运、手工业 |
| 人口迁徙 | MigrationProcess / CulturalFlow(POPULATION) | 永嘉南渡/安史之乱南迁/湖广填四川/闯关东 |
| 族群交往 | EthnicInteraction | 土家/苗/彝/羌/藏等与汉的互动 |
| 政治整合 | PoliticalIntegrationProcess | 秦统一/郡县制/科举/改土归流 |
| 商贸交通 | TradeRoute / TransportNetwork / CulturalFlow(GOODS) | 长江航运/茶马古道/徽商/盐运 |
| 知识传播 | KnowledgeTransmissionProcess /书院/科举/刻书 | 岳麓书院/东林书院/江南贡院 |
| 文明交流 | CivilizationalExchange / EXTERNAL_CONTEXT | 佛教传入/西学东渐/中外条约 |
| 持续生成 | CulturalFormationProcess | 文化不是静态而是持续生成 |
| 不同历史时期 | HistoricalPhase（层级化，非统一朝代表） | 各区域有自己的局部阶段 |
| 不同区域文化 | RegionalCulturalSystem（羌藏/巴蜀/荆楚/湖湘/赣皖/吴越/滇黔） | 非普通 Topic/Place |
| 传播 | CulturalFlow + TransmissionRoute | 流动方向/载体/机制 |
| 交融 | FusionProcess / hybridized_with | 交融不是同化 |
| 重组 | ReconfigurationProcess / reconfigured_into | 文化要素在新语境中重组 |
| 多层次 | Hierarchical System Structure | 系统→子系统→领域→传统 |
| 开放性 | EXTERNAL_CIVILIZATION_CONTEXT | 外部文明通过 Context Link 接入 |
| 连续性 | CulturalContinuity (DIRECT/TRANSFORMED/REVIVED/INSTITUTIONAL/MEMORY) | 连续≠不变，转型也是连续 |
| 史前文化 | PrehistoricYangtzeCivilization | 稻作/聚落/城址/玉器/礼仪 |
| 地域文化 | RegionalCulturalSystem | 羌藏/巴蜀/荆楚/湖湘/赣皖/吴越/滇黔 |
| 中华优秀传统文化 | TraditionalCulturalSystem | 哲学/文学/艺术/科技 |
| 革命文化 | RevolutionaryCulture | 红色文化/辛亥/长征/抗战 |
| 工业与城市文化 | IndustrialCulture / UrbanCulture | 洋务运动/民族工业/通商口岸 |
| 社会主义先进文化 | ContemporarySocialistCulture | 长江经济带/生态文明/文化公园 |
| 中华文明多元一体 | ChineseCivilization (根节点) | 长江文化 contributed_to → 中华文明 |

---

## 三、系统层结构：六层异质时空图

### Layer 1: 自然地理—水系基础层

```
HydroSpatialUnit
├── Basin（流域）
├── MainStem（干流）
├── RiverSection（河段）
├── Tributary（支流）
├── Lake（湖泊）
├── Wetland（湿地）
├── Delta（三角洲）
├── Plain（平原）
├── MountainRegion（山区）
├── Valley（谷地）
├── SubBasin（子流域）
└── WaterTransportCorridor（水运通道）
```

关系：tributary_of / flows_into / part_of_basin / upstream_of / downstream_of /
      passes_through / hydrologically_connects / adjacent_basin

**行政区不是最高空间逻辑。**
AdministrativeSpatialLayer 仅作为交叉映射层。

### Layer 2: 区域文化系统层

每个 RegionalCulturalSystem 包含：
- spatial_extent（空间范围）
- hydro_basis（水系基础）
- historical_phases（历史阶段——有自己的局部阶段，非统一朝代表）
- core_traditions（核心传统）
- representative_entities（代表人物/器物/遗址）
- production_patterns（生产模式）
- belief_systems（信仰体系）
- knowledge_traditions（知识传统）
- artistic_traditions（艺术传统）
- interaction_regions（互动区域）
- evolution_summary（演进概述）

层级：subsystem_of / developed_within / overlaps_with / interacts_with

### Layer 3: 历史演进层

HistoricalPhase 可层级化，不同系统有自己的局部阶段。
MacroPhase 四类：MULTI_ORIGIN / REGIONAL_DEVELOPMENT / BASIN_INTERACTION / CONTINUOUS_INTEGRATION

### Layer 4: 文化内容系统层

CulturalDomain 层级：
```
水文化
├── 治水文化
├── 水利工程文化
├── 航运文化
├── 渡口码头文化
├── 渔业文化
├── 江河信仰
└── 滨水城市生活
```

### Layer 5: 文化载体层

Canonical_v1 的实体保留。
新增 SystemMembership：object → system → role(CORE/REPRESENTATIVE/CARRIER/...)

### Layer 6: 文化过程与流动层

CulturalProcess（高阶对象，含阶段/原因/结果/参与者/路线/机制/影响）
CulturalFlow（POPULATION/GOODS/TECHNOLOGY/KNOWLEDGE/INSTITUTION/RELIGION/ART/...）
TransmissionRoute（RiverRoute/CanalRoute/AncientRoad/MigrationRoute/TradeRoute/...）

---

## 四、受控结构谓词

Canonical System Layer 使用以下谓词（替代 associated_with）：

```
构成类: constitutes / subsystem_of / belongs_to_cultural_system /
        manifestation_of / representative_of
起源类: originated_in / emerged_from / developed_from / inherited_from /
        continued_as
转型类: transformed_into / reconfigured_into / revived_as / localized_as /
        institutionalized_as / heritagized_as / modernized_as
传播类: spread_to / spread_along / transmitted_via / diffused_into
互动类: interacted_with / exchanged_with / conflicted_with / absorbed_from /
        integrated_with / fused_with / hybridized_with / differentiated_from
条件类: enabled_by / constrained_by / mediated_by
贡献类: contributed_to / integrated_into
```

associated_with 不得作为 System Layer 正式核心关系。

---

## 五、SystemMembership（结构归属）

每个进入 System Layer 的对象必须回答：
**"我在长江文化体系中的结构位置是什么？"**

```yaml
object_id: ← Canonical Entity UUID
system_id: ← 所属 CulturalSystem / RegionalCulturalSystem / CulturalDomain
membership_role: CORE_CONSTITUENT / REPRESENTATIVE / CARRIER / ORIGIN_NODE /
                 TRANSMISSION_NODE / INTERACTION_NODE / TRANSFORMATION_NODE /
                 MEMORY_NODE / EXTERNAL_CONTEXT
region: ← 所属区域文化
period: ← 所属历史阶段
domain: ← 所属文化领域
strength: 0.0-1.0
confidence: 0.0-1.0
evidence_id: ← 支撑证据
```

---

## 六、对象进入 System Layer 的条件

必须至少有**四类锚点中的两个**：

| 锚点 | 说明 | 来源 |
|---|---|---|
| Spatial Anchor | 与某 HydroSpatialUnit / Place 有关联 | Claim.place_entity_id |
| Temporal Anchor | 有 TimeSpan 关联某 HistoricalPhase | claims.timespan_id |
| Cultural Domain Anchor | 属于某 CulturalDomain | scope topic_labels |
| Process/System Anchor | 参与某 CulturalProcess / 属于某 Tradition | cultural_process_members |

只有 `name + type` 的实体留在 Canonical Fact Layer，不进入 System Layer。

---

## 七、Knowledge Type 区分

```
FACT                    ← 有直接原文证据的事实
SCHOLARLY_INTERPRETATION ← 学术解释（"水运促进江南商业文化"）
STRUCTURAL_INFERENCE     ← 从图结构推断（"A 和 B 共现频繁 → 可能有关联"）
SYSTEM_HYPOTHESIS        ← 系统层假设（待验证）
```

不混为事实。Interpretation 对象单独建模。

---

## 八、结构性知识缺口（不是 Coverage 空格）

不生成 `湖北 × 先秦 × Person = 0` 这种空格子。

而是检测结构缺陷：

```
ORPHAN_ENTITY               有事实但无系统归属
MISSING_SYSTEM_MEMBERSHIP   有 claims 但没挂到任何 CulturalSystem
MISSING_PARENT_SYSTEM       子系统存在但父系统缺失
MISSING_SUBSYSTEM           父系统存在但子系统缺失
MISSING_HISTORICAL_PHASE    某时期完全无数据
BROKEN_EVOLUTION_CHAIN      Tradition A → B 之间缺失中间环节
MISSING_PROCESS             有结果但无过程（汉阳铁厂→但缺洋务运动/近代工业化 context）
MISSING_PROCESS_STAGE       过程存在但缺关键阶段
MISSING_PROCESS_CAUSE       有结果但无原因
MISSING_ACTOR_ROLE          有事件但缺参与者角色
MISSING_FLOW                有交流但缺流动对象
MISSING_TRANSMISSION_ROUTE  有传播但缺路线
MISSING_CROSS_REGION_LINK   两个区域有互动证据但未建立联系
MISSING_CROSS_PERIOD_LINK   跨时期的连续性未表达
MISSING_HYDRO_LINK          有文化但缺水系联系
MISSING_HUMAN_ENVIRONMENT_LINK  有人文但缺人地互动
MISSING_REGIONAL_VARIANT    传统存在但缺地方变体
CONFLICTING_INTERPRETATION  学术解释冲突
STRUCTURAL_DISCONTINUITY    演化链断裂
SINGLE_SOURCE_STRUCTURE     结构关系仅单一来源
```

---

## 九、宏观演化框架

```
多源发生 → 区域发展 → 流域互动 → 持续整合
MULTI_ORIGIN → REGIONAL_DEVELOPMENT → BASIN_INTERACTION → CONTINUOUS_INTEGRATION
```

不是严格年代分期。是演化机制层。一个 HistoricalPhase 可同时参与某个 MacroPhase。

---

## 十、核心示例

### 石家河文化的结构性缺口

```
已有：时间 / 遗址 / 器物 / 长江中游空间
缺少：与屈家岭文化的演化关系
     与稻作/水利系统的联系
     与其他文明中心的交流证据
→ STRUCTURAL_DISCONTINUITY
```

### 汉阳铁厂的结构缺口

```
已有：张之洞 / 1890 / 武汉 / 工业实体
缺少：与洋务运动的联系
     与汉冶萍体系的联系
     与长江航运的联系
     与原料流动的联系
     与技术输入的联系
     与武汉近代工业化的联系
→ MISSING_PROCESS + MISSING_NETWORK
```

这才应该触发 ResearchTask。

---

## 十一、实现状态（2026-09-13，由工具生成校准）

| 层 | 状态 | 交付物 |
|---|---|---|
| 复现性（Phase 7R） | PASS | 006/007/008 migration + 6 个受控 seed YAML + tools/init_canonical_v2.py，clean-room 0 漂移 |
| 受控本体 | PASS | 8 系统 / 7 区域 / 93 领域（§10.2 重分类后）/ 13 分期 / 4 演化模式（多对多）/ 34 水系单元 / 46 拓扑关系 |
| 结构谓词 | PARTIAL | v1_3 谓词表在用；Schema 2.0（§13 全字段）待升级 |
| Membership | PASS（结构门禁）/ PARTIAL（覆盖） | 4 锚点确定性重建，ADMITTED 92 / CANDIDATE 1867，geo-only ADMITTED=0 |
| 结构关系 | PASS（门禁） | 7 条 ONTOLOGY 豁免 + 21 条 0 证据边降级 CANDIDATE |
| 证据束/合成 | 运行中 | extensions/v2/：束→合成→字段级核验→准入，首批 9 ADMITTED |
| 缺口引擎 | 运行中 | 7 类检测器，527 OPEN 缺口驱动研究任务 |
| 研究引擎 | 运行中 | gap→task（gap_id 绑定）→查询→采集溯源→缺口复测 |
| Growth v2 | 首轮运行 | tools/cultural_system_growth.py，熔断 HEALTHY |
| API v2 | PASS | 13 端点 /yangtze/v2/*，25 测试通过 |
| 数字人文基准 | PASS | 100 题 + Golden Ten 定义（yangtze/benchmarks/） |
| Burn-in / Soak / Red Team | NOT_MEASURED | 时间预算未覆盖，见 reports/V2_FINAL_VALIDATION.md |

数字以当日 `python tools/validate_canonical_v2.py` 输出为准（§107 禁止手写统计长期残留）。
