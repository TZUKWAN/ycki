# -*- coding: utf-8 -*-
"""YCKI 版本化 Prompt 模板（Phase 16/55）。

规则：修改任何模板必须递增版本号，且在 docs/CHANGELOG_YCKI.md 登记。
所有管线输出必须记录 prompt_version + model + pipeline_version。
"""

PROMPTS: dict[str, str] = {}

# ------------------------------------------------------------------ resource_scope_v1
PROMPTS["resource_scope_v1"] = """你是长江文化知识库的资源准入评审员。判断下面这篇资源与"长江文化"的关系。

## 判定标准（严格执行）
- CORE：内容本身构成长江文化研究对象。指长江流域（青藏高原至长江口；干流与支流：金沙江/雅砻江/岷江/沱江/嘉陵江/乌江/汉江/湘江/资江/沅江/澧水/赣江/青弋江/黄浦江等；流域湖泊：洞庭湖/鄱阳湖/太湖/巢湖等）的地理、历史、水利、城市、人物、事件、文物、非遗、文学、经济、生态等。
- CONTEXT：对象本身在长江流域之外或非长江主题，但与某个明确的长江文化核心事实存在直接、明确、必要的关系（如：北京的机构参与了武汉长江大桥设计）。注意：只是"顺带提到长江"不算 CONTEXT。
- REJECT：与长江文化无直接结构性关系（如：北京胡同、故宫一般史、颐和园、山西晋商、东北抗联一般史、与长江无关的一般性内容）。
- 不允许仅因"文中偶然出现长江字样"判 CORE；不允许机械地域黑名单——域外对象若有明确长江关系应判 CONTEXT。
- 硬负例锚（必须 REJECT）：北京故宫/颐和园/长城/胡同/晋商票号/东北抗联/黄河流域对象——它们与长江流域无地理或文化结构关系。
- few-shot：①"故宫博物院藏明清文物"→REJECT ②"颐和园造园艺术"→REJECT ③"北京的桥梁专家组赴武汉参与长江大桥建设"→CONTEXT ④"湘江战役中红军强渡湘江"→CORE（湘江经洞庭湖入长江）。
- 判 REJECT 时从严：对象不在长江流域、且文中无明确长江结构性联系，一律 REJECT。

## 需要评估的资源
标题：{title}
来源域名：{domain}
来源类型：{source_type}
采集上下文（发现主题）：{discovery_topic}
检索词：{search_query}
正文（截断）：
{text}

## 输出（严格 JSON，无其他文字）
{{"scope_role":"CORE|CONTEXT|REJECT",
"yangtze_relevance":0.0到1.0,
"topic_relevance":0.0到1.0,
"spatial_relevance":0.0到1.0,
"cultural_relevance":0.0到1.0,
"geo_scope":"流域内-上游|流域内-中游|流域内-下游|流域内-河口|支流-XX|全流域|流域外",
"geo_evidence":"判断地域依据的原文短语",
"topic_labels":["最多4个主题标签，如 水利工程/历史文化/红色文化"],
"relevance_reason":"50字内判定理由，引用原文关键短语"}}"""

# ------------------------------------------------------------------ chunk_scope_v1
PROMPTS["chunk_scope_v1"] = """对下列文档片段逐一判断其与长江文化的相关性（标准：CORE=本身是长江文化内容；CONTEXT=域外但与长江核心事实有直接明确关系；REJECT=无关）。

文档标题：{title}
资源级判定：{scope_role}

片段列表：
{chunks}

输出严格 JSON 数组，每个片段一项（index 必须与输入一致）：
[{{"index":0,"relevance":"CORE|CONTEXT|REJECT","reason":"20字内理由"}}]"""

# --------------------------------------------------- entity_event_claim_extraction_v1
PROMPTS["entity_event_claim_extraction_v1"] = """你是长江文化知识抽取引擎。从下面通过准入的文本片段中抽取：实体、事件、受控谓词主张（claim）。

## 实体类型（只能用这些）
Person(人物) EthnicGroup(民族) Place(地点) Organization(组织) Institution(文化机构) Event(事件) Work(作品) Artifact(器物) Heritage(文化遗产) Site(遗址遗迹) Practice(民俗实践) Concept(概念思想) WaterSystem(水系与水利工程) Route(线路通道) NaturalObject(自然对象) EthnicGroup(民族)

## 受控谓词（predicate 只能用这些，注意方向 domain→range）
born_at(Person→Place) died_at(Person→Place) participated_in(Person/Organization→Event) founded(Person/Organization→Organization/Institution/Site) authored(Person→Work) served_at(Person→Organization/Institution) led(Person→Organization/Event) located_within(*→Place) part_of(*→Place/*) historical_name_of(Place→Place) successor_of/predecessor_of(Place/Organization→Place/Organization) tributary_of(WaterSystem→WaterSystem) flows_through(WaterSystem→Place) originates_at(WaterSystem→Place) empties_into(WaterSystem→WaterSystem/Place) belongs_to_basin(*→WaterSystem) impounds(WaterSystem/Artifact→WaterSystem) authored_by(Work→Person) describes(Work→Place/Event/Person) happened_at(Event→Place) has_participant(Event→Person/Organization) involved_organization(Event→Organization) caused(Event→Event) influenced(*→*) associated_with(*→*，兜底，必须有明确原文)

## 硬性规则
1. 每条 claim 必须给出 quote_span：原文中能直接支撑该主张的连续文字（10~60字，逐字摘抄，不得改写）。
2. 找不到原文依据的推断（"可能有关联"）一律不输出。
3. 多参与者历史事件优先输出为 event（带 time/place/participants），不要拆成两两共现。
4. 时间尽量给出 ISO 或中文纪年原文；朝代/时期写入 period。
5. 实体名使用文中规范称谓。民族类实体用 EthnicGroup 类型。
6. 以下谓词的 claim 必须给 time：founded/participated_in/served_at/born_at/died_at/successor_of/predecessor_of/historical_name_of/led/studied_at/taught_at/created_during；纯地理事实（located_within/tributary_of/flows_through 等）无需 time。

## 文本（来自：{title}）
{chunks}

## 输出严格 JSON
{{"entities":[{{"name":"...","type":"Person|...","description":"30字内"}}],
"events":[{{"name":"...","event_type":"战争|工程|起义|通商|文化|政治|灾害|其他","time":"...","period":"朝代或时期","place":"...","participants":["人名"],"organizations":["机构名"],"description":"50字内","quote_span":"原文摘抄"}}],
"claims":[{{"subject":"实体名","predicate":"受控谓词","object":"实体名","time":"可空","place":"可空","quote_span":"原文摘抄"}}]}}"""

# ------------------------------------------------------------------ entity_resolution_v1
PROMPTS["entity_resolution_v1"] = """判断两个长江文化实体候选是否指同一对象。

候选A：{name_a}（类型 {type_a}）描述：{desc_a}
候选B：{name_b}（类型 {type_b}）描述：{desc_b}

规则：同人异名（毛泽东/毛润之）→ same；同名需核对时代与地域，不确定 → unsure；不同对象 → different；古今地名（江宁/南京）→ same，并注明关系类型。

输出严格 JSON：{{"verdict":"same|different|unsure","reason":"30字内","relation":"若same且为古今地名，填 historical_name_of 或 successor_of，否则 null"}}"""

# ------------------------------------------------------------------ claim_admission_v1（规则引擎无 prompt，占位版本号）
PROMPTS["claim_admission_v1"] = "rule-engine (no LLM)"
PROMPTS["gap_detection_v1"] = "rule-engine coverage matrix (no LLM)"
