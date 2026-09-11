# -*- coding: utf-8 -*-
"""动态搜索策略引擎 —— 长江文化全覆盖检索词生成。

三层搜索策略：
  Layer 1 确定性模板：省份×城市×主题×时期×人物类型（覆盖面广）
  Layer 2 文化专题轴：荆楚/巴蜀/吴越/湖湘/徽州/赣鄱/滇黔/青藏 等文化圈
  Layer 3 LLM 联想扩展：根据当前 Coverage 缺口动态生成精准检索词

使用方式：
  from extensions.search.strategy import SearchStrategy
  s = SearchStrategy()
  queries = s.generate_for_gap("湖北", "先秦", "考古", "Site")
  queries = s.generate_blind_spots()      # 自动发现盲区
"""
from __future__ import annotations

# =====================================================================
# 长江流域省份（用户指定 13 个核心 + 支流延伸）
# =====================================================================
YANGTZE_PROVINCES = [
    "西藏", "青海", "贵州", "云南", "四川", "重庆",
    "湖北", "湖南", "江西", "安徽", "江苏", "上海", "浙江",
]

# 各省主要城市（搜索粒度到地级市）
PROVINCE_CITIES = {
    "青海": ["玉树", "格尔木"],
    "西藏": ["那曲", "昌都"],
    "云南": ["昆明", "昭通", "丽江", "迪庆"],
    "四川": ["成都", "宜宾", "泸州", "攀枝花", "乐山", "南充", "达州", "甘孜"],
    "重庆": ["重庆主城", "万州", "涪陵", "黔江", "巫山", "奉节"],
    "湖北": ["武汉", "宜昌", "荆州", "襄阳", "黄冈", "黄石", "十堰", "恩施", "随州", "孝感"],
    "湖南": ["长沙", "岳阳", "常德", "益阳", "株洲", "湘潭", "衡阳", "湘西", "怀化"],
    "江西": ["南昌", "九江", "景德镇", "赣州", "吉安", "上饶", "宜春"],
    "安徽": ["安庆", "池州", "铜陵", "芜湖", "马鞍山", "宣城", "黄山", "合肥"],
    "江苏": ["南京", "镇江", "扬州", "泰州", "常州", "无锡", "苏州", "南通"],
    "上海": ["上海"],
    "浙江": ["杭州", "湖州", "嘉兴", "绍兴", "宁波", "舟山"],
    "贵州": ["贵阳", "遵义", "铜仁", "毕节"],
}

# =====================================================================
# 文化圈层（不是省份，是文化认同圈）
# =====================================================================
CULTURAL_REGIONS = {
    "青藏文化": ["格萨尔史诗", "唐卡艺术", "藏传佛教", "茶马古道源头", "三江源生态"],
    "滇黔文化": ["夜郎古国", "彝族十月太阳历", "傩戏面具", "苗绣", "遵义会议", "茅台酒酿制"],
    "巴蜀文化": ["三星堆", "金沙遗址", "都江堰", "蜀锦", "川剧变脸", "湖广填四川",
               "杜甫草堂", "武侯祠", "剑门蜀道", "川菜", "自贡盐业", "蜀绣"],
    "荆楚文化": ["楚辞", "编钟", "屈原", "纪南城", "荆州古城", "髹漆工艺",
               "楚国青铜器", "楚文化考古", "武昌起义", "辛亥革命", "汉剧", "湖北评书"],
    "湖湘文化": ["岳麓书院", "曾国藩", "左宗棠", "马王堆", "湘绣", "花鼓戏",
               "韶山", "岳阳楼", "洞庭湖", "湘军", "浏阳花炮"],
    "徽州文化": ["徽商", "徽派建筑", "徽剧", "新安理学", "徽墨歙砚", "西递宏村",
               "胡适", "陶行知", "徽州宗族", "黄山"],
    "赣鄱文化": ["景德镇", "滕王阁", "白鹿洞书院", "王安石", "汤显祖", "八大山人",
               "鄱阳湖生态", "赣剧", "庐山", "井冈山"],
    "吴越文化": ["吴文化", "越文化", "苏州园林", "昆曲", "评弹", "太湖流域",
               "良渚文化", "河姆渡", "大运河江南段", "丝绸之府", "南宋临安"],
    "江南文化": ["江南水乡", "江南园林", "江南丝竹", "江南贡院", "江南制造总局",
               "南朝石刻", "六朝古都", "东晋衣冠南渡", "大运河", "明孝陵"],
    "江淮文化": ["淮扬菜", "扬州八怪", "瘦西湖", "镇江金山寺", "南通博物苑",
               "张謇实业", "淮剧", "扬剧"],
    "海派文化": ["上海开埠", "外滩建筑", "石库门", "海派绘画", "申报馆",
               "上海租界", "江南制造总局", "商务印书馆"],
}

# =====================================================================
# 主题轴（超越简单分类的深层主题）
# =====================================================================
DEEP_TOPICS = {
    "水系与水利": ["长江防洪史", "荆江大堤", "长江航道治理", "长江流域灌溉史",
                 "长江水患与治水人物", "长江流域湖泊变迁"],
    "考古文明": ["长江流域新石器遗址", "长江流域青铜器", "楚文化考古",
               "长江流域古墓葬", "长江流域简牍出土", "长江流域陶瓷考古"],
    "历史事件": ["赤壁之战", "武昌起义", "武汉会战", "渡江战役", "宜昌大撤退",
               "湖口之战", "采石之战", " Napoleon无关略过"],
    "非遗与民俗": ["长江流域传统戏剧", "长江流域民间音乐", "长江流域传统技艺",
                "长江流域庙会", "长江流域传统节庆", "长江流域民间信仰"],
    "文学艺术": ["长江诗词", "长江题材绘画", "长江题材音乐", "长江流域书院",
               "长江流域刻书业", "长江流域报刊史"],
    "红色文化": ["长江流域革命遗址", "长江流域红色人物", "长江流域抗战史",
               "长江流域解放战争", "长江流域土地改革"],
    "工业遗产": ["长江流域近代工业", "长江流域民族企业", "长江流域工厂搬迁",
               "长江流域铁路史", "长江流域航运史", "长江流域矿业史"],
    "对外交流": ["长江口岸通商", "长江流域租界", "长江流域教会", "长江流域留学史",
               "长江流域外侨", "长江流域外贸史"],
    "生态与环保": ["长江十年禁渔", "长江江豚保护", "长江流域湿地", "长江源头保护",
                "长江流域水土保持", "长江流域污染治理"],
    "当代发展": ["长江经济带", "长三角一体化", "成渝双城经济圈", "长江国家文化公园",
               "长江文化传承发展", "长江流域乡村振兴"],
    "宗教信仰": ["长江流域道教", "长江流域佛教", "长江流域民间信仰",
               "武当山道教", "九华山佛教", "龙虎山道教"],
    "建筑与城市": ["长江流域古城", "长江流域民居", "长江流域园林",
                 "长江流域桥梁", "长江流域码头", "长江流域会馆"],
    "饮食文化": ["长江流域菜系", "长江流域茶文化", "长江流域酒文化",
               "长江流域食材", "长江流域饮食习俗"],
    "科技教育": ["长江流域古代科技", "长江流域近代教育", "长江流域科学机构",
               "长江流域发明创造", "长江流域医学史"],
}

# =====================================================================
# 历史时期（标准 Period vocabulary）
# =====================================================================
PERIODS = ["先秦", "秦汉", "魏晋南北朝", "隋唐", "宋元", "明清",
           "晚清", "民国", "新中国成立后", "改革开放以来", "新时代"]

# =====================================================================
# 人物类型（不只是政治家）
# =====================================================================
PERSON_TYPES = ["政治家", "军事家", "文学家", "诗人", "画家", "书法家",
                "科学家", "医学家", "工程师", "教育家", "思想家", "宗教领袖",
                "工匠大师", "非遗传承人", "企业家", "革命家", "考古学家"]


class SearchStrategy:
    """动态搜索策略引擎。"""

    def __init__(self):
        self.all_queries: set[str] = set()

    def _add(self, q: str) -> str:
        q = q.strip()
        if q and len(q) >= 4 and q not in self.all_queries:
            self.all_queries.add(q)
            return q
        return ""

    # ---- Layer 1: 省份 × 城市 × 主题 ----
    def province_city_topic(self, province: str, topic: str) -> list[str]:
        """某省 + 某主题的搜索词。"""
        qs = []
        cities = PROVINCE_CITIES.get(province, [])
        qs.append(f"{province} 长江文化 {topic}")
        for city in cities[:4]:  # 每省最多取 4 城
            qs.append(f"{city} {topic}")
        return [self._add(q) for q in qs if self._add(q)]

    # ---- Layer 2: 文化圈层 ----
    def cultural_region(self, region_name: str) -> list[str]:
        """文化圈层搜索：每个子主题独立一条。"""
        seeds = CULTURAL_REGIONS.get(region_name, [])
        qs = [f"{region_name} {seed}" for seed in seeds]
        qs.append(f"{region_name} 文化特征 概述")
        return [self._add(q) for q in qs if self._add(q)]

    # ---- Layer 3: 深度主题 × 地理 ----
    def deep_topic_geo(self, topic_key: str, province: str = "") -> list[str]:
        """深度主题 + 可选地理限定。"""
        seeds = DEEP_TOPICS.get(topic_key, [])
        if province:
            return [self._add(f"{province} {seed}") for seed in seeds if self._add(f"{province} {seed}")]
        return [self._add(q) for q in seeds if self._add(q)]

    # ---- Layer 4: 人物类型 × 时期 ----
    def person_type_period(self, ptype: str, period: str) -> list[str]:
        qs = [f"{period} {ptype}", f"长江流域 {period} {ptype}"]
        return [self._add(q) for q in qs if self._add(q)]

    # ---- 主入口：为某省生成全维度搜索 ----
    def generate_province_full(self, province: str) -> list[str]:
        """为一个省生成全维度搜索词（约 80-120 条）。"""
        self.all_queries.clear()
        # 主题 × 地理
        for topic in DEEP_TOPICS:
            self.deep_topic_geo(topic, province)
        # 文化圈
        for region in CULTURAL_REGIONS:
            if any(c in province for c in PROVINCE_CITIES.get(province, [])[:1]):
                self.cultural_region(region)
        # 人物
        for pt in PERSON_TYPES[:8]:
            self.person_type_period(pt, "")
        # 城市
        for city in PROVINCE_CITIES.get(province, []):
            self._add(f"{city} 历史文化")
            self._add(f"{city} 非遗")
        return list(self.all_queries)

    # ---- 主入口：为文化圈生成搜索 ----
    def generate_cultural_region(self, region: str) -> list[str]:
        """为一个文化圈生成全维度搜索词。"""
        self.all_queries.clear()
        return self.cultural_region(region)

    # ---- 主入口：Coverage 缺口驱动 ----
    def generate_for_gap(self, region: str, period: str, topic: str,
                         etype: str) -> list[str]:
        """为特定 Coverage 缺口生成精准检索词（LLM + 模板混合）。"""
        qs = []

        # 模板层
        qs.append(f"{region} {period} {topic}")
        if etype == "Person":
            qs.append(f"{region} {period} 历史人物")
            qs.append(f"{region} {period} 名人")
        elif etype == "Event":
            qs.append(f"{region} {period} 历史事件")
            qs.append(f"{region} {period} 战争")
        elif etype == "Site":
            qs.append(f"{region} 遗址 古迹")
        elif etype == "WaterSystem":
            qs.append(f"{region} 河流 水系")

        # 文化圈层
        for region_name, seeds in CULTURAL_REGIONS.items():
            if region in region_name or any(s for s in seeds if region in s):
                qs.extend([f"{region_name} {period} {topic}"])

        return [q.strip() for q in qs if q.strip() and len(q.strip()) >= 4]

    # ---- 盲区发现 ----
    def generate_blind_spots(self, covered_regions: set[str],
                             covered_topics: set[str]) -> list[str]:
        """发现覆盖盲区并生成搜索词。"""
        qs = []
        # 未覆盖省份
        for p in YANGTZE_PROVINCES:
            if p not in covered_regions:
                qs.append(f"{p} 长江文化 概述")
                qs.append(f"{p} 历史文化名城")
        # 未覆盖主题
        for t in DEEP_TOPICS:
            if t not in covered_topics:
                qs.extend(DEEP_TOPICS[t][:2])
        return [self._add(q) for q in qs if self._add(q)]


def generate_all_batches() -> list[dict]:
    """生成全部搜索批次（供 collect.py 消费）。返回 themes 列表。"""
    themes = []
    s = SearchStrategy()

    # 1. 每省全维度
    for p in YANGTZE_PROVINCES:
        qs = s.generate_province_full(p)
        if qs:
            themes.append({"topic": f"策略:{p}全维度", "queries": qs})

    # 2. 每个文化圈
    for region, seeds in CULTURAL_REGIONS.items():
        qs = [f"{region} {seed}" for seed in seeds]
        qs.append(f"{region} 文化概述")
        themes.append({"topic": f"文化圈:{region}", "queries": qs})

    return themes


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    s = SearchStrategy()
    # 演示
    qs = s.generate_province_full("湖北")
    print(f"湖北全维度: {len(qs)} 条")
    for q in qs[:10]:
        print(f"  {q}")
    qs2 = s.cultural_region("荆楚文化")
    print(f"荆楚文化: {len(qs2)} 条")
    qs3 = s.deep_topic_geo("工业遗产", "武汉")
    print(f"武汉工业遗产: {qs3}")
