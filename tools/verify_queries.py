# -*- coding: utf-8 -*-
"""YCKI 抽检验证：跨主题真实提问 → /query/data → 引用 file_path 反查 PG（URL+权威级+标题）。
只输出真实结果：引用无法回查的会如实打印 UNRESOLVED。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from tools.registry import Registry

LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4", "Content-Type": "application/json"}

QUESTIONS = [
    ("时空水利", "都江堰是谁主持修建的？由哪三大主体工程构成？"),
    ("水系", "汉江和洞庭湖在长江水系中的地位是什么？"),
    ("考古", "三星堆遗址发现了哪些重要文物？"),
    ("红色文化", "武昌起义发生在什么时候？有什么历史意义？"),
    ("工业文化", "汉阳铁厂是谁创办的？后来合并成了什么公司？"),
    ("交通航运", "卢作孚和他的民生公司对抗战航运有什么贡献？"),
    ("文学", "屈原是什么时期的人物？他的代表作是什么？"),
    ("非遗", "昆曲有什么艺术特点？它列入了什么名录？"),
    ("生态", "长江十年禁渔是什么时候开始的？目的是什么？"),
    ("综合", "长江流域有哪些世界文化遗产或重要考古遗址？"),
]


def main():
    reg = Registry()
    try:
        with reg.conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(lightrag_file_source, lightrag_doc_id) AS fs,
                                  resource_id, source_url, title,
                                  source_domain, s.authority_level, s.source_type
                           FROM resources r LEFT JOIN sources s USING (source_id)
                           WHERE lightrag_file_source IS NOT NULL
                              OR lightrag_doc_id IS NOT NULL""")
            rows = cur.fetchall()
        by_fs = {}
        for r in rows:
            if r[0] and not str(r[0]).startswith("doc-"):
                by_fs[r[0]] = r   # file_source 形式
        print(f"PG 可回查映射: {len(by_fs)} 条\n")

        resolved_total = unresolved_total = 0
        for theme, q in QUESTIONS:
            payload = {"query": q, "mode": "hybrid"}
            r = requests.post(f"{LIGHTRAG}/query/data", headers=H, json=payload, timeout=300)
            if r.status_code != 200:
                print(f"✗ [{theme}] HTTP {r.status_code}: {r.text[:120]}")
                continue
            d = r.json()
            refs = ((d.get("data") or {}).get("references")) or []
            ents = ((d.get("data") or {}).get("entities")) or []
            print(f"◆ [{theme}] {q}")
            print(f"  实体命中 {len(ents)} | 引用 {len(refs)} 条:")
            for ref in refs[:4]:
                fp = ref.get("file_path") if isinstance(ref, dict) else str(ref)
                row = by_fs.get(fp)
                if row:
                    resolved_total += 1
                    print(f"    ✓ {fp[:42]} → {row[2][:60]} [{row[5]}/{row[6]}]")
                else:
                    unresolved_total += 1
                    print(f"    ? {fp[:60]} → (PG 无映射)")
            # 答案正文摘要
            resp = requests.post(f"{LIGHTRAG}/query", headers=H,
                                 json={"query": q, "mode": "hybrid"}, timeout=300)
            if resp.status_code == 200:
                ans = resp.json().get("response", "")
                print(f"  答案({len(ans)}字): {ans[:160]}…")
            print()
            time.sleep(1)
        print(f"引用回查: 成功 {resolved_total} / 未映射 {unresolved_total}")
    finally:
        reg.close()


if __name__ == "__main__":
    main()
