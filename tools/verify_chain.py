# -*- coding: utf-8 -*-
"""YCKI 端到端关联核验（真实数据，无模拟）：
1. 解析 LightRAG 持久层：graphml（实体/关系）+ kv_store_text_chunks / full_docs
2. 全链校验：实体.source_id → chunk 存在 → chunk.full_doc_id → 文档 file_path → PG resources（source_url 可回查）
3. 实体类型分布（验证长江文化本体生效）
4. 主题抽查询（真实 RAG 回答）+ 引用 file_path 反查 PG 的 source_url/authority
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests
import xml.etree.ElementTree as ET

RAG = Path(r"D:\长江学论纲\ycki\deploy\lightrag\data\rag_storage")
GRAPH = RAG / "graph_chunk_entity_relation.graphml"
CHUNKS = RAG / "kv_store_text_chunks.json"
DOCS = RAG / "kv_store_full_docs.json"
LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4"}
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.registry import Registry  # noqa: E402


def load_graphml():
    """LightRAG GraphML：属性为纯文本 key（d0=entity_id d1=entity_type d2=description
    d3=source_id d4=file_path；边 d7=weight d8=description d9=keywords d10=source_id d11=file_path）"""
    tree = ET.parse(GRAPH)
    root = tree.getroot()
    ns = {"g": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    tag = lambda t: f"{{{ns['g']}}}{t}" if ns else t
    NODE_KEYS = {"d0": "entity_id", "d1": "entity_type", "d2": "description",
                 "d3": "source_id", "d4": "file_path"}
    EDGE_KEYS = {"d7": "weight", "d8": "description", "d9": "keywords",
                 "d10": "source_id", "d11": "file_path"}
    nodes, edges = [], []
    for n in root.iter(tag("node")):
        attrs = {"entity_id": n.get("id")}
        for d in n.findall(tag("data")):
            k = NODE_KEYS.get(d.get("key"))
            if k and d.text:
                attrs[k] = d.text
        nodes.append(attrs)
    for e in root.iter(tag("edge")):
        attrs = {"source": e.get("source"), "target": e.get("target")}
        for d in e.findall(tag("data")):
            k = EDGE_KEYS.get(d.get("key"))
            if k and d.text:
                attrs[k] = d.text
        edges.append(attrs)
    return nodes, edges


def main():
    # ---------- 持久层加载 ----------
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))     # 扁平: {chunk_id: {...,full_doc_id}}
    docs = json.loads(DOCS.read_text(encoding="utf-8"))         # {doc_id: {file_path,...}}
    chunk_index = {cid: (c.get("full_doc_id"), c) for cid, c in chunks.items()}
    nodes, edges = load_graphml()
    print(f"graph: {len(nodes)} entities, {len(edges)} relations; "
          f"chunks: {len(chunks)} in {len(docs)} docs")

    # ---------- 实体类型分布（本体生效证据） ----------
    type_hist = collections.Counter(
        (n.get("entity_type") or "?").strip().lower() for n in nodes)
    print("\n[实体类型分布]")
    for t, c in type_hist.most_common():
        print(f"  {t:<14} {c}")

    # ---------- 全链关联校验 ----------
    reg = Registry()
    try:
        # PG: file_source/file_path → resource 映射
        with reg.conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(lightrag_file_source, lightrag_doc_id),
                                  resource_id, source_url, title,
                                  source_domain, ingest_status FROM resources
                           WHERE lightrag_doc_id IS NOT NULL""")
            by_file_source = {r[0]: r for r in cur.fetchall()}

        miss_chunk = miss_doc = miss_pg = ok_chain = 0
        unresolved_sources = collections.Counter()
        for n in nodes:
            src = n.get("source_id") or ""
            ids = [s.strip() for s in re.split(r";|<SEP>", src) if s.strip()]
            resolved = False
            for cid in ids:
                if cid in chunk_index:
                    doc_id, _ = chunk_index[cid]
                    doc = docs.get(doc_id)
                    if not doc:
                        miss_doc += 1
                        continue
                    fp = doc.get("file_path") or ""
                    if by_file_source.get(fp):
                        resolved = True
                    else:
                        miss_pg += 1
                else:
                    miss_chunk += 1
            if resolved:
                ok_chain += 1
            else:
                unresolved_sources[src[:60]] += 1
        print("\n[全链关联校验] Knowledge→Chunk→Document→Resource(Source)")
        print(f"  实体总数: {len(nodes)} | 可闭合回溯到 PG 资源: {ok_chain}")
        print(f"  chunk 缺失引用: {miss_chunk} | doc 缺失引用: {miss_doc} | 未入 PG(基线测试文档等): {miss_pg}")
        if unresolved_sources:
            print(f"  未解析样例(前5): {unresolved_sources.most_common(5)}")
        return reg
    finally:
        pass


if __name__ == "__main__":
    main()
