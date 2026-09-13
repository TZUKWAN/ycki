#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""membership_gold.py — Membership 外部金标构造（§12.1）。

金标来源：教科书级确定性事实（非模型自评）：
  TRUE_POSITIVE        长江文化体系内对象 → 指定区域系统
  HARD_NEGATIVE        现代基础设施/现代企业（一律 REJECT）
  CROSS_REGION         确凿跨区对象 → 多重成员标签
  EXTERNAL_CONTEXT     黄河/珠江/边墙外对象 → REJECT
  MULTI_MEMBERSHIP     同上跨区，多系统并标
  HISTORICAL_REGION    历史政区与文化的对应
  GENERIC_ENTITY       无文化实指的通用词 → REJECT
  BORDER               学术界确有归属争议 → CANDIDATE（不得 ADMIT）

真实对象条目均为可验证的公开常识；负例由确定性模板构造。
输出 yangtze/schema/membership_gold_v2.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "yangtze" / "schema" / "membership_gold_v2.json"


BS, JC, HX, KW, WY, DQ, QC = ("巴蜀文化系统", "荆楚文化系统", "湖湘文化系统",
                      "赣皖文化系统", "吴越文化系统", "滇黔文化系统", "羌藏文化系统")

P2: list[tuple[str, str, str]] = [
    # 巴蜀续
    ("三星堆青铜神树", "Artifact", BS), ("金沙太阳神鸟", "Artifact", BS), ("都江堰放水节", "CulturalTradition", BS),
    ("洛带古镇", "Place", BS), ("黄龙溪古镇", "Place", BS), ("上里古镇", "Place", BS),
    ("剑门关", "Place", BS), ("明月峡栈道", "Place", BS), ("川江号子", "CulturalTradition", BS),
        ("大足石刻", "Place", BS), ("钓鱼城遗址", "Place", BS), ("湖广会馆", "Place", BS),
    ("湖广填四川", "Process", BS), ("麻城孝感乡传说", "CulturalTradition", BS), ("川江航运", "Process", BS),
    ("重庆湖广会馆", "Place", BS), ("合川涞滩二佛寺", "Place", BS), ("蜀锦", "CulturalTradition", BS),
    ("川派盆景", "CulturalTradition", BS), ("绵竹年画", "CulturalTradition", BS), ("自贡扎染", "CulturalTradition", BS),
    ("泸州老窖酿制技艺", "CulturalTradition", BS), ("郫县豆瓣制作技艺", "CulturalTradition", BS),
    # 荆楚续
    ("屈原故里", "Place", JC), ("神农架", "Place", JC), ("武落钟离山", "Place", JC),
    ("楚皇城遗址", "Place", JC), ("木兰传说", "CulturalTradition", JC),
    ("汉剧", "CulturalTradition", JC), ("楚剧", "CulturalTradition", JC), ("湖北评书", "CulturalTradition", JC),
    ("潜江草把龙", "CulturalTradition", JC), ("孝感雕花剪纸", "CulturalTradition", JC),
    ("蕲春李时珍", "Person", JC), ("毕昇", "Person", JC), ("陆羽", "Person", JC),
    ("米芾", "Person", JC), ("公安三袁", "Person", JC), ("竟陵派", "CulturalDomain", JC),
    ("襄阳古隆中", "Place", JC), ("当阳关陵", "Place", JC), ("玉泉寺", "Place", JC),
    ("京汉铁路", "Process", JC), ("粤汉铁路", "Process", JC),
    ("芦汉铁路", "Process", JC), ("自强学堂", "Organization", JC), ("武汉大学早期建筑", "Place", JC),
    # 湖湘续
    ("炎帝陵", "Place", HX), ("舜帝陵", "Place", HX), ("九嶷山", "Place", HX),
    ("南岳衡山", "Place", HX), ("紫鹊界梯田", "Place", HX), ("老司城遗址", "Place", HX),
    ("洪江古商城", "Place", HX), ("黔城芙蓉楼", "Place", HX), ("花鼓戏", "CulturalTradition", HX),
    ("湘昆", "CulturalTradition", HX), ("祁剧", "CulturalTradition", HX), ("长沙弹词", "CulturalTradition", HX),
    ("土家族摆手舞", "CulturalTradition", HX), ("苗族银饰锻造技艺", "CulturalTradition", HX),
    ("浏阳文庙祭孔音乐", "CulturalTradition", HX), ("船山学派", "CulturalDomain", HX),
    ("时务学堂", "Organization", HX), ("城南书院", "Place", HX), ("屈贾之乡", "Place", HX),
    ("贾谊故居", "Place", HX), ("曾国藩", "Person", HX), ("左宗棠", "Person", HX),
    ("魏源", "Person", HX), ("谭嗣同", "Person", HX), ("黄兴", "Person", HX),
    # 赣皖续
    ("庐山白鹿洞", "Place", KW), ("井冈山", "Place", KW), ("滕阁秋风", "Place", KW),
    ("绳金塔庙会", "CulturalTradition", KW), ("景德镇手工制瓷技艺", "CulturalTradition", KW),
    ("婺源徽剧", "CulturalTradition", KW), ("弋阳腔", "CulturalTradition", KW), ("赣剧", "CulturalTradition", KW),
    ("九江租界旧址", "Place", KW), ("白鹿洞书院学规", "Artifact", KW), ("铅山连四纸", "CulturalTradition", KW),
    ("歙砚制作技艺", "CulturalTradition", KW), ("徽州三雕", "CulturalTradition", KW), ("屯溪老街", "Place", KW),
    ("呈坎村", "Place", KW), ("唐模村", "Place", KW), ("棠樾牌坊群", "Place", KW),
    ("潜口民宅", "Place", KW), ("罗东舒祠", "Place", KW), ("胡氏宗祠", "Place", KW),
    ("朱熹", "Person", KW), ("戴震", "Person", KW), ("胡适", "Person", KW), ("陶渊明", "Person", KW),
    ("汤显祖", "Person", KW), ("文天祥", "Person", KW), ("欧阳修", "Person", KW),
    ("王安石", "Person", KW), ("曾巩", "Person", KW),
    # 吴越续
    ("崧泽遗址", "Place", WY), ("马家浜遗址", "Place", WY), ("草鞋山遗址", "Place", WY),
    ("广富林遗址", "Place", WY), ("福泉山遗址", "Place", WY), ("寺墩遗址", "Place", WY),
    ("虎丘塔", "Place", WY), ("保圣寺罗汉塑像", "Artifact", WY), ("沧浪亭", "Place", WY),
    ("狮子林", "Place", WY), ("留园", "Place", WY), ("网师园", "Place", WY),
    ("环秀山庄", "Place", WY), ("艺圃", "Place", WY), ("耦园", "Place", WY),
    ("退思园", "Place", WY), ("寄畅园", "Place", WY), ("个园", "Place", WY),
    ("何园", "Place", WY), ("小盘谷", "Place", WY), ("扬州盐商住宅", "Place", WY),
    ("甘泉山汉墓", "Place", WY), ("南朝陵墓石刻", "Artifact", WY), ("栖霞寺舍利塔", "Artifact", WY),
    ("苏州评弹", "CulturalTradition", WY), ("锡剧", "CulturalTradition", WY), ("扬剧", "CulturalTradition", WY),
    ("淮剧", "CulturalTradition", WY), ("沪剧", "CulturalTradition", WY), ("滑稽戏", "CulturalTradition", WY),
    ("金陵派竹刻", "CulturalTradition", WY), ("嘉定竹刻", "CulturalTradition", WY), ("桃花坞年画", "CulturalTradition", WY),
    ("金山农民画", "CulturalTradition", WY),
    ("宋锦织造技艺", "CulturalTradition", WY), ("缂丝织造技艺", "CulturalTradition", WY),
    ("南京金箔锻制技艺", "CulturalTradition", WY), ("明式家具制作技艺", "CulturalTradition", WY),
    ("香山帮传统建筑营造技艺", "CulturalTradition", WY), ("苏州御窑金砖制作技艺", "CulturalTradition", WY),
    ("王羲之", "Person", WY), ("顾恺之", "Person", WY), ("米芾拜石传说", "CulturalTradition", WY),
    ("唐寅", "Person", WY), ("文徵明", "Person", WY), ("祝允明", "Person", WY),
    ("徐霞客", "Person", WY), ("冯梦龙", "Person", WY), ("金圣叹", "Person", WY),
    ("曹雪芹金陵旧踪", "CulturalDomain", WY), ("吴敬梓", "Person", WY), ("袁枚随园", "Place", WY),
]

P3_CROSS: list[tuple[str, str]] = [
    ("端午节", "CulturalTradition"), ("中秋节", "CulturalTradition"), ("采茶戏", "CulturalTradition"),
    ("傩戏", "CulturalTradition"), ("龙舟制作技艺", "CulturalTradition"), ("长江号子", "CulturalTradition"),
    ("茶馆文化", "CulturalDomain"), ("码头文化", "CulturalDomain"), ("稻作文化", "CulturalDomain"),
    ("蚕桑丝织技艺", "CulturalTradition"), ("宣纸制作技艺", "CulturalTradition"), ("中医本草文化", "CulturalDomain"),
    ("书院讲学制度", "CulturalDomain"), ("会馆制度", "CulturalDomain"), ("漕运制度", "Process"),
]


# 真实文化对象（对象, 类型, 正确系统）。描述留给判官从名称+类型+常识判断；
# 提供简短描述以贴近真实 membership 判定输入。
P: list[tuple[str, str, str]] = [
    # 巴蜀
    ("都江堰", "Place", BS), ("三星堆遗址", "Place", BS), ("金沙遗址", "Place", BS),
    ("川剧", "CulturalTradition", BS), ("蜀绣", "CulturalTradition", BS),
    ("武侯祠", "Place", BS), ("杜甫草堂", "Place", BS), ("青城山", "Place", BS),
    ("峨眉山", "Place", BS), ("乐山大佛", "Place", BS), ("自贡盐业历史博物馆", "Organization", BS),
    ("川菜", "CulturalDomain", BS), ("茶马古道川藏线", "Process", BS), ("石宝寨", "Place", BS),
    ("阆中古城", "Place", BS), ("李庄古镇", "Place", BS), ("蜀道", "Process", BS),
    ("变脸", "CulturalTradition", BS), ("竹枝词", "CulturalTradition", BS), ("巴渝舞", "CulturalTradition", BS),
    ("白帝城", "Place", BS), ("张飞庙", "Place", BS), ("丰都鬼城", "Place", BS),
    # 荆楚
    ("曾侯乙编钟", "Artifact", JC), ("黄鹤楼", "Place", JC), ("荆州古城", "Place", JC),
    ("楚纪南城遗址", "Place", JC), ("屈原", "Person", JC), ("端午竞渡", "CulturalTradition", JC),
    ("武当山", "Place", JC), ("明显陵", "Place", JC), ("归元寺", "Place", JC),
    ("汉阳铁厂", "Organization", JC), ("江汉关", "Place", JC), ("编钟乐舞", "CulturalTradition", JC),
    ("楚辞", "CulturalDomain", JC), ("汉绣", "CulturalTradition", JC), ("知音传说", "CulturalTradition", JC),
    ("古琴台", "Place", JC), ("晴川阁", "Place", JC), ("宜昌大撤退", "Event", JC),
    ("武昌起义", "Event", JC), ("汉口开埠", "Event", JC), ("炎帝神农传说", "CulturalTradition", JC),
    # 湖湘
    ("岳麓书院", "Place", HX), ("马王堆汉墓", "Place", HX), ("岳阳楼", "Place", HX),
    ("凤凰古城", "Place", HX), ("湘绣", "CulturalTradition", HX), ("湘剧", "CulturalTradition", HX),
    ("湖湘学派", "CulturalDomain", HX), ("王夫之", "Person", HX), ("周敦颐", "Person", HX),
    ("张栻", "Person", HX), ("胡宏", "Person", HX), ("里耶秦简", "Artifact", HX),
    ("炭河里遗址", "Place", HX), ("铜官窑遗址", "Place", HX), ("汨罗江", "Place", HX),
    ("洞庭湖", "Place", HX), ("湘西赶尸传说", "CulturalTradition", HX), ("女书", "CulturalTradition", HX),
    ("浏阳花炮", "CulturalTradition", HX), ("湘军", "Organization", HX),
    # 赣皖
    ("景德镇御窑厂", "Place", KW), ("滕王阁", "Place", KW), ("白鹿洞书院", "Place", KW),
    ("庐山", "Place", KW), ("徽商", "Organization", KW), ("徽派建筑", "CulturalDomain", KW),
    ("西递宏村", "Place", KW), ("歙县", "Place", KW), ("黟县", "Place", KW),
    ("徽剧", "CulturalTradition", KW), ("文房四宝徽墨宣纸", "Artifact", KW), ("景德镇瓷器", "Artifact", KW),
    ("鄱阳湖", "Place", KW), ("绳金塔", "Place", KW), ("傩舞", "CulturalTradition", KW),
    ("鹅湖书院", "Place", KW), ("渔梁坝", "Place", KW), ("许国石坊", "Artifact", KW),
    # 吴越
    ("良渚古城遗址", "Place", WY), ("河姆渡遗址", "Place", WY), ("西湖", "Place", WY),
    ("灵隐寺", "Place", WY), ("苏州园林", "CulturalDomain", WY), ("拙政园", "Place", WY),
    ("昆曲", "CulturalTradition", WY), ("越剧", "CulturalTradition", WY), ("评弹", "CulturalTradition", WY),
    ("南京云锦", "CulturalTradition", WY), ("苏绣", "CulturalTradition", WY), ("宜兴紫砂", "CulturalTradition", WY),
    ("乌镇", "Place", WY), ("周庄", "Place", WY), ("同里", "Place", WY),
    ("寒山寺", "Place", WY), ("大明寺", "Place", WY), ("瘦西湖", "Place", WY),
    ("中山陵", "Place", WY), ("明孝陵", "Place", WY), ("夫差开凿邗沟", "Event", WY),
    ("江南贡院", "Place", WY), ("龙井茶制作技艺", "CulturalTradition", WY), ("金陵刻经处", "Organization", WY),
    # 跨区真实对象（多重成员）
    ("长江三峡", "Place", None), ("大运河江南段", "Process", None), 
]

# 硬负例：现代基础设施/企业（用户明示 P+R 类不是长江文化）
MODERN_NEG_TEMPLATES = [
    "{city}市第一人民医院", "{city}装饰建材城", "{city}二手车交易市场",
    "{city}机动车驾校", "{city}连锁便利店仓库",
    "{city}建材五金市场", "{city}汽修连锁店", "{city}健身中心",
    "{city}网约车服务站", "{city}外卖配送站",
    "{city}轨道交通{num}号线", "{city}停车换乘枢纽", "{city}长江大桥收费站",
    "{city}自来水厂", "{city}污水处理厂", "{city}新能源汽车充电站",
    "{city}快递分拣中心", "{city}数据中心", "{city}美食广场",
]
CITIES = ["武汉", "南京", "重庆", "上海", "宜昌", "安庆", "九江", "岳阳", "芜湖", "镇江",
          "泸州", "万州", "黄石", "鄂州", "荆州", "常熟", "南通", "泰州", "马鞍山", "铜陵"]

# 外部语境负例
EXTERNAL_NEG = [
    ("龙门石窟", "Place"), ("云冈石窟", "Place"), ("平遥古城", "Place"), ("乔家大院", "Place"),
    ("殷墟", "Place"), ("赵州桥", "Artifact"), ("避暑山庄", "Place"), ("清东陵", "Place"),
    ("珠江夜游", "CulturalDomain"), ("开平碉楼", "Place"), ("哈尔滨冰雪大世界", "CulturalDomain"),
    ("敦煌莫高窟", "Place"), ("嘉峪关", "Place"), ("秦始皇兵马俑", "Artifact"),
    ("大唐不夜城", "Place"), ("开封清明上河园", "Place"), ("曲阜孔庙", "Place"),
    ("泰山", "Place"), ("趵突泉", "Place"), ("蓬莱阁", "Place"),
    ("杨柳青木版年画", "CulturalTradition"), ("黄河壶口瀑布", "Place"), ("哈尔滨中央大街", "Place"), ("沈阳故宫", "Place"),
    ("长白山天池", "Place"), ("青海湖", "Place"), ("拉萨布达拉宫", "Place"),
]

# 通用实体（无文化实指）
GENERIC_NEG = [
    ("长江水利委员会", "Organization"), ("长江存储科技有限责任公司", "Organization"),
    ("长江电力股份有限公司", "Organization"), ("长江航道局", "Organization"),
    ("长江大学", "Organization"), ("长江证券", "Organization"),
    ("长江索道", "Place"), ("长江之家小区", "Place"), ("长江大酒店", "Organization"),
    ("长江村村委会", "Organization"),
]

# 边界案例（学界确有争议 → 只应给 CANDIDATE）
BORDER = [
    ("扬州", "Place"), ("信阳", "Place"), ("南阳", "Place"), ("汉中", "Place"),
    ("赣州", "Place"), ("安庆", "Place"), ("九江", "Place"), ("湖州", "Place"),
]



P4: list[tuple[str, str, str]] = [
    ("格萨尔王传", "CulturalDomain", QC), ("德格印经院", "Organization", QC),
    ("泸定桥", "Place", QC), ("桃坪羌寨", "Place", QC), ("康定情歌", "CulturalTradition", QC),
    ("遵义会议会址", "Place", DQ), ("甲秀楼", "Place", DQ), ("黔灵山弘福寺", "Place", DQ), ("青羊宫", "Place", BS), ("文殊院", "Place", BS), ("宝光寺", "Place", BS),
    ("望江楼公园", "Place", BS), ("望丛祠", "Place", BS), ("二王庙", "Place", BS),
    ("七曲山大庙", "Place", BS), ("报恩寺", "Place", BS), ("奉节诗城文化", "CulturalDomain", BS), ("白鹤梁题刻", "Artifact", BS), ("石柱土家啰儿调", "CulturalTradition", BS),
    ("川北薅草锣鼓", "CulturalTradition", BS), ("羌年", "CulturalTradition", BS),
    ("彝族火把节", "CulturalTradition", BS), ("蜀派古琴", "CulturalTradition", BS), ("成都漆艺", "CulturalTradition", BS),
    ("银花丝", "CulturalTradition", BS), ("瓷胎竹编", "CulturalTradition", BS), ("梁平木版年画", "CulturalTradition", BS),
    ("铜梁龙舞", "CulturalTradition", BS), ("酉阳古歌", "CulturalTradition", BS), ("走马镇民间故事", "CulturalTradition", BS),
    ("巴山背二歌", "CulturalTradition", BS), ("川北皮影", "CulturalTradition", BS), ("资阳河川剧艺术", "CulturalTradition", BS),
    ("李冰", "Person", BS), ("扬雄", "Person", BS), ("司马相如", "Person", BS), ("陈子昂", "Person", BS),
    ("苏轼", "Person", BS), ("苏洵", "Person", BS), ("苏辙", "Person", BS), ("李白蜀中行迹", "CulturalDomain", BS),
    ("杜甫两川诗", "CulturalDomain", BS), ("陆游蜀中诗", "CulturalDomain", BS), ("黄庭坚涪州谪居", "CulturalDomain", BS),
    ("杜甫草堂修复史", "Process", BS), ("都江堰清明放水大典", "CulturalTradition", BS),
    ("屈家岭遗址", "Place", JC), ("石家河遗址", "Place", JC), ("雕龙碑遗址", "Place", JC),
    ("盘龙城遗址", "Place", JC), ("铜绿山古铜矿遗址", "Place", JC), ("唐崖土司城遗址", "Place", JC),
    ("唐户遗址", "Place", JC), ("楚墓马山一号", "Place", JC), ("包山楚简", "Artifact", JC),
    ("郭店楚简", "Artifact", JC), ("曾侯乙尊盘", "Artifact", JC), ("虎座鸟架鼓", "Artifact", JC),
    ("楚式漆器髹饰技艺", "CulturalTradition", JC), ("汉绣", "CulturalTradition", JC), ("黄梅挑花", "CulturalTradition", JC),
    ("红安绣活", "CulturalTradition", JC), ("阳新布贴", "CulturalTradition", JC), ("大冶刺绣", "CulturalTradition", JC),
    ("汉川善书", "CulturalTradition", JC), ("湖北大鼓", "CulturalTradition", JC), ("恩施扬琴", "CulturalTradition", JC),
    ("利川灯歌", "CulturalTradition", JC), ("宜昌丝竹", "CulturalTradition", JC), ("枝江民间吹打乐", "CulturalTradition", JC),
    ("老河口丝弦", "CulturalTradition", JC), ("马家窑文化", "CulturalDomain", BS),
    ("炎帝神农故里", "Place", JC), ("随州大洪山", "Place", JC), ("九宫山", "Place", JC),
    ("陆羽茶文化", "CulturalDomain", JC), ("茶圣故里", "Place", JC), ("张居正故居", "Place", JC),
    ("襄阳米公祠", "Place", JC), ("习家池", "Place", JC), ("水镜庄", "Place", JC),
    ("炎帝诞辰祭祀", "CulturalTradition", HX), ("舜帝祭典", "CulturalTradition", HX), ("抬阁", "CulturalTradition", HX),
    ("安仁赶分社", "CulturalTradition", HX), ("资兴瑶族盘王节", "CulturalTradition", HX), ("侗锦织造技艺", "CulturalTradition", HX),
    ("苗族古歌", "CulturalTradition", HX), ("侗族大歌", "CulturalTradition", HX), ("土家族织锦技艺", "CulturalTradition", HX),
    ("蓝印花布印染技艺", "CulturalTradition", HX), ("滩头木版年画", "CulturalTradition", HX), ("湘潭纸影戏", "CulturalTradition", HX),
    ("邵阳布袋戏", "CulturalTradition", HX), ("目连戏", "CulturalTradition", HX), ("昆曲湘昆流派", "CulturalTradition", HX),
    ("岳州窑", "Place", HX), ("长沙窑", "Place", HX), ("醴陵釉下五彩瓷", "CulturalTradition", HX),
    ("湖湘祠堂", "CulturalDomain", HX), ("理学家祠", "CulturalDomain", HX), ("船山学社", "Organization", HX),
    ("南昌八一起义", "Event", KW), ("滕王阁诗会", "CulturalTradition", KW), ("西山万寿宫庙会", "CulturalTradition", KW),
    ("文港毛笔", "CulturalTradition", KW), ("李渡烧酒酿造技艺", "CulturalTradition", KW), ("景德镇水碓营造技艺", "CulturalTradition", KW),
    ("婺源三雕", "CulturalTradition", KW), ("婺源徽墨", "CulturalTradition", KW), ("歙县鱼灯", "CulturalTradition", KW),
    ("休宁板桥泉源", "CulturalDomain", KW), ("祁门红茶制作技艺", "CulturalTradition", KW), ("黄山毛峰制作技艺", "CulturalTradition", KW),
    ("太平猴魁制作技艺", "CulturalTradition", KW), ("徽州祠祭", "CulturalTradition", KW), ("安苗节", "CulturalTradition", KW),
    ("胡开文墨庄", "Organization", KW), ("张小泉剪刀", "CulturalTradition", WY), ("王星记扇", "CulturalTradition", WY),
    ("西湖绸伞", "CulturalTradition", WY), ("杭罗织造技艺", "CulturalTradition", WY), ("余杭滚灯", "CulturalTradition", WY),
    ("湖州湖笔", "CulturalTradition", WY), ("龙泉青瓷烧制技艺", "CulturalTradition", WY), ("龙泉宝剑锻制技艺", "CulturalTradition", WY),
    ("青田石雕", "CulturalTradition", WY), ("宁波朱金漆木雕", "CulturalTradition", WY), ("乐清黄杨木雕", "CulturalTradition", WY),
    ("东阳木雕", "CulturalTradition", WY), ("宁波泥金彩漆", "CulturalTradition", WY), ("绍兴黄酒酿制技艺", "CulturalTradition", WY),
    ("金陵鸭馁制作技艺", "CulturalTradition", WY), ("镇江恒顺香醋酿制技艺", "CulturalTradition", WY),
    ("扬州漆器髹饰技艺", "CulturalTradition", WY), ("扬州玉雕", "CulturalTradition", WY), ("扬州剪纸", "CulturalTradition", WY),
    ("南通蓝印花布", "CulturalTradition", WY), ("如皋盆景技艺", "CulturalTradition", WY), ("雨花茶制作技艺", "CulturalTradition", WY),
    ("绿柳居素食烹制技艺", "CulturalTradition", WY), ("秦淮灯会", "CulturalTradition", WY), ("苏州庙会", "CulturalTradition", WY),
]


def build() -> list[dict]:
    cases: list[dict] = []
    contested = ["中山陵", "明孝陵", "江南贡院", "金陵刻经处", "大明寺", "瘦西湖",
                 "南京云锦", "夫子庙", "朝天宫", "栖霞寺", "镇江", "常熟", "南通",
                 "扬州漆器髹饰技艺", "扬剧", "淮剧", "夫差开凿邗沟", "吴王夫差开凿邗沟"]
    CONTESTED = set(contested)

    for name, etype, sysname in P + P2 + P4:
        case = {"name": name, "type": etype, "expected": "ADMIT",
                "system": sysname or JC, "family": "cross_region" if not sysname else "true_positive"}
        if name in CONTESTED:
            case["accept"] = [sysname or JC, "CANDIDATE"]
        EXTRA_ACCEPT = {
            "米芾": [JC, "吴越文化系统", "CANDIDATE"],
            "吴敬梓": [WY, "赣皖文化系统", "CANDIDATE"],
            "泸定桥": [QC, "巴蜀文化系统", "CANDIDATE"],
            "遵义会议会址": [DQ, "湖湘文化系统", "CANDIDATE"],
        }
        if name in EXTRA_ACCEPT:
            case["accept"] = EXTRA_ACCEPT[name]
        cases.append(case)
    # 多重成员：跨区对象允许任一系统 ADMIT
    for c in cases:
        if c["family"] == "cross_region":
            c["expected_systems"] = [BS, JC, HX, KW, WY]
    for name, etype in P3_CROSS:
        cases.append({"name": name, "type": etype, "expected": "ADMIT",
                      "system": JC, "expected_systems": [BS, JC, HX, KW, WY],
                      "family": "multi_membership"})
    more_neg = [f"长江{city}段航道养护站" for city in CITIES] +                [f"{city}港集装箱码头" for city in CITIES] +                [f"长江{city}公路液化气站" for city in CITIES] +                [f"{city}高新区管委会大楼" for city in CITIES] +                [f"{city}城市规划展览馆" for city in CITIES] +                [f"{city}政务服务中心" for city in CITIES] +                [f"{city}长江水厂取水泵站" for city in CITIES]
    for name, etype in [(n, "Place") for n in more_neg]:
        cases.append({"name": name, "type": etype, "expected": "REJECT", "system": None,
                      "family": "hard_negative"})
    for i, city in enumerate(CITIES):
        for t in MODERN_NEG_TEMPLATES:
            cases.append({"name": t.format(city=city, num=(i % 9) + 1), "type": "Place",
                          "expected": "REJECT", "system": None,
                          "family": "hard_negative"})
    for name, etype in EXTERNAL_NEG:
        cases.append({"name": name, "type": etype, "expected": "REJECT", "system": None,
                      "family": "external_context"})
    for name, etype in GENERIC_NEG:
        cases.append({"name": name, "type": etype, "expected": "REJECT", "system": None,
                      "family": "generic_entity"})
    border_more = [("武汉长江大桥", "Place"), ("鸡公山", "Place"), ("襄樊", "Place"), ("钟祥", "Place"), ("随州", "Place"), ("常德", "Place"),
                   ("澧县", "Place"), ("芜湖", "Place"), ("巢湖流域", "Place"), ("皖河", "Place"),
                   ("滁州", "Place"), ("湖州", "Place"), ("嘉兴", "Place"), ("南通", "Place"),
                   ("通州", "Place"), ("海门", "Place"), ("启东", "Place"), ("当涂", "Place")]
    border_all = BORDER + border_more
    BORDER_ACCEPT = {
        "扬州": ["吴越文化系统", "赣皖文化系统"], "镇江": ["吴越文化系统"], "常熟": ["吴越文化系统"],
        "南通": ["吴越文化系统"], "通州": ["吴越文化系统"], "海门": ["吴越文化系统"], "启东": ["吴越文化系统"],
        "信阳": ["荆楚文化系统", "REJECT"], "南阳": ["荆楚文化系统", "REJECT"], "汉中": ["巴蜀文化系统", "REJECT"],
        "赣州": ["赣皖文化系统"], "九江": ["赣皖文化系统", "荆楚文化系统"], "湖州": ["吴越文化系统"],
        "嘉兴": ["吴越文化系统"], "安庆": ["赣皖文化系统"], "芜湖": ["赣皖文化系统"], "当涂": ["赣皖文化系统"],
        "巢湖流域": ["赣皖文化系统"], "皖河": ["赣皖文化系统"], "滁州": ["赣皖文化系统"],
        "襄樊": ["荆楚文化系统"], "钟祥": ["荆楚文化系统"], "随州": ["荆楚文化系统"],
        "常德": ["湖湘文化系统"], "澧县": ["湖湘文化系统"],
        "武汉长江大桥": ["REJECT", "荆楚文化系统"], "鸡公山": ["REJECT", "荆楚文化系统"],
    }
    for name, etype in border_all:
        acc = ["CANDIDATE"] + BORDER_ACCEPT.get(name, [])
        cases.append({"name": name, "type": etype, "expected": "CANDIDATE", "system": None,
                      "accept": acc, "family": "border"})
    # 历史政区（确定性映射）
    hist = [("江州", JC), ("郢都", JC), ("金陵", WY), ("临安", WY), ("益州", BS),
            ("渝州", BS), ("潭州", HX), ("洪都", KW), ("歙州", KW), ("毗陵", WY)]
    for name, sysname in hist:
        cases.append({"name": name, "type": "Place", "expected": "ADMIT", "system": sysname,
                      "family": "historical_region"})
    return cases


def main() -> int:
    cases = build()
    fams: dict[str, int] = {}
    for c in cases:
        fams[c["family"]] = fams.get(c["family"], 0) + 1
    doc = {"version": "membership_gold_v2", "cases": cases,
           "family_counts": fams, "total": len(cases)}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(fams, ensure_ascii=False), "total=", len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
