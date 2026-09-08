# -*- coding: utf-8 -*-
"""T04 验证：上传都江堰测试文本，验证长江文化本体类型（Person/WaterSystem/Site）真实生效"""
import json
import sys
import time

import requests

API = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4",
     "Content-Type": "application/json"}

TEXT = """都江堰水利工程概况
都江堰位于四川省成都市都江堰市，坐落于岷江之上，是战国时期秦国蜀郡太守李冰父子于公元前256年左右主持修建的大型水利工程。
都江堰由鱼嘴分水堤、飞沙堰溢洪道、宝瓶口引水口三大主体工程构成，两千多年来一直发挥着防洪灌溉作用，使成都平原成为"天府之国"。
2000年，都江堰被联合国教科文组织列入世界文化遗产名录。岷江是长江上游重要支流，都江堰水利工程体现了古人"乘势利导、因时制宜"的治水智慧。"""

r = requests.post(f"{API}/documents/text", headers=H,
                  json={"text": TEXT, "file_source": "都江堰本体验证.txt"}, timeout=60)
print("upload:", r.status_code, r.text[:150])
time.sleep(5)
for _ in range(30):
    docs = requests.post(f"{API}/documents/paginated", headers=H,
                         json={"page": 1, "page_size": 20}, timeout=30).json()
    docs = docs.get("data", {}).get("documents", docs.get("documents", []))
    target = [d for d in docs if "都江堰" in (d.get("file_path") or "")]
    if target and target[0]["status"] in ("processed", "failed"):
        print("status:", target[0]["status"])
        break
    time.sleep(8)

labels = requests.get(f"{API}/graph/label/list", headers=H, timeout=30).json()
print("total labels:", len(labels))
# 查询新实体的类型：从子图接口逐个验证
for ent in ["李冰", "都江堰", "岷江", "宝瓶口"]:
    g = requests.get(f"{API}/graphs", headers=H, params={"label": ent, "max_depth": 1},
                     timeout=30).json()
    for n in g.get("nodes", []):
        p = n.get("properties") or {}
        if p.get("entity_id") == ent:
            print(f"  {ent}: type={p.get('entity_type')}")
