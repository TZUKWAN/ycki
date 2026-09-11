# -*- coding: utf-8 -*-
"""Retrieval Graph → PostgreSQL 逐条写入适配器。

核心设计：替代 LightRAG 的 GraphML 全量序列化。
每次 upsert/delete 只触及单行，利用 PostgreSQL 事务保证原子性。
即使进程被强杀，已提交的事务永久保留，未提交的自动回滚。

使用方式（在 rebuild_canonical.py 或独立工具中）：
    from extensions.kg.pg_retrieval_graph import PGRetrievalGraph
    g = PGRetrievalGraph(conn)
    g.upsert_node("汉阳铁厂", "artifact", "中国近代第一家钢铁联合企业...")
    g.upsert_edge("张之洞", "汉阳铁厂", "创办,奏准", "1890年奏准创办...")
    g.delete_node("故宫博物院")
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger("ycki.pg_retrieval_graph")


class PGRetrievalGraph:
    """Retrieval Graph 的 PostgreSQL 逐条写入实现。

    与 NetworkX 的区别：
    - NetworkX：全量内存图，每次写入 = 读全图 + 写全文件（127MB）
    - PGRetrievalGraph：每条写入 = 单条 INSERT/UPDATE（<1KB），事务保证原子性
    """

    def __init__(self, conn):
        self.conn = conn

    def commit(self):
        """显式提交事务。调用方负责在适当时候调用。"""
        self.conn.commit()

    # ---------------------------------------------------------------- 节点
    def upsert_node(self, node_id: str, entity_type: str, description: str = "",
                    source_id: str = "", file_path: str = "") -> None:
        """插入或更新单个节点。只写一行，绝不清空其他数据。"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO retrieval_nodes
                    (node_id, entity_type, description, source_id, file_path)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (node_id) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    description = EXCLUDED.description,
                    source_id   = EXCLUDED.source_id,
                    file_path   = EXCLUDED.file_path,
                    updated_at  = now()
            """, (node_id, entity_type, description, source_id, file_path))
        pass  # commit 由调用方控制

    def upsert_nodes_batch(self, nodes: list[dict[str, Any]]) -> int:
        """批量插入节点（逐条 UPSERT，单事务）。"""
        n = 0
        with self.conn.cursor() as cur:
            for node in nodes:
                cur.execute("""
                    INSERT INTO retrieval_nodes
                        (node_id, entity_type, description, source_id, file_path)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (node_id) DO UPDATE SET
                        entity_type = EXCLUDED.entity_type,
                        description = EXCLUDED.description,
                        source_id   = EXCLUDED.source_id,
                        file_path   = EXCLUDED.file_path,
                        updated_at  = now()
                """, (node["node_id"], node["entity_type"],
                      node.get("description", ""),
                      node.get("source_id", ""),
                      node.get("file_path", "")))
                n += 1
        pass  # commit 由调用方控制
        return n

    def delete_node(self, node_id: str) -> None:
        """删除单个节点及其所有边（级联）。"""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM retrieval_edges WHERE src_id=%s OR tgt_id=%s",
                        (node_id, node_id))
            cur.execute("DELETE FROM retrieval_nodes WHERE node_id=%s", (node_id,))
        pass  # commit 由调用方控制

    # ---------------------------------------------------------------- 边
    def upsert_edge(self, src_id: str, tgt_id: str, keywords: str,
                    description: str = "", weight: float = 1.0,
                    source_id: str = "", file_path: str = "") -> None:
        """插入或更新单条边。edge_id 由 src+tgt+keywords 哈希确定，幂等。"""
        edge_id = hashlib.sha1(
            f"{src_id}|{tgt_id}|{keywords}".encode("utf-8")).hexdigest()[:16]
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO retrieval_edges
                    (edge_id, src_id, tgt_id, keywords, description,
                     weight, source_id, file_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (edge_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    weight      = EXCLUDED.weight,
                    source_id   = EXCLUDED.source_id,
                    file_path   = EXCLUDED.file_path,
                    updated_at  = now()
            """, (edge_id, src_id, tgt_id, keywords, description,
                  weight, source_id, file_path))
        pass  # commit 由调用方控制

    def upsert_edges_batch(self, edges: list[dict[str, Any]]) -> int:
        """批量插入边（逐条 UPSERT，单事务）。"""
        n = 0
        with self.conn.cursor() as cur:
            for e in edges:
                edge_id = hashlib.sha1(
                    f"{e['src_id']}|{e['tgt_id']}|{e['keywords']}".encode()
                ).hexdigest()[:16]
                cur.execute("""
                    INSERT INTO retrieval_edges
                        (edge_id, src_id, tgt_id, keywords, description,
                         weight, source_id, file_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (edge_id) DO UPDATE SET
                        description = EXCLUDED.description,
                        weight      = EXCLUDED.weight,
                        source_id   = EXCLUDED.source_id,
                        file_path   = EXCLUDED.file_path,
                        updated_at  = now()
                """, (edge_id, e["src_id"], e["tgt_id"], e["keywords"],
                      e.get("description", ""), e.get("weight", 1.0),
                      e.get("source_id", ""), e.get("file_path", "")))
                n += 1
        pass  # commit 由调用方控制
        return n

    def delete_edge(self, src_id: str, tgt_id: str, keywords: str = "") -> None:
        """删除单条边。"""
        with self.conn.cursor() as cur:
            if keywords:
                edge_id = hashlib.sha1(
                    f"{src_id}|{tgt_id}|{keywords}".encode()).hexdigest()[:16]
                cur.execute("DELETE FROM retrieval_edges WHERE edge_id=%s", (edge_id,))
            else:
                cur.execute(
                    "DELETE FROM retrieval_edges WHERE src_id=%s AND tgt_id=%s",
                    (src_id, tgt_id))
        pass  # commit 由调用方控制

    # ---------------------------------------------------------------- 查询
    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute("""SELECT node_id, entity_type, description,
                                  source_id, file_path
                           FROM retrieval_nodes WHERE node_id=%s""", (node_id,))
            row = cur.fetchone()
        if row:
            return {"node_id": row[0], "entity_type": row[1],
                    "description": row[2], "source_id": row[3],
                    "file_path": row[4]}
        return None

    def get_neighbors(self, node_id: str, depth: int = 1,
                      limit: int = 100) -> dict[str, Any]:
        """BFS 邻域查询，返回节点+边。"""
        nodes_visited = {node_id}
        edges_out = []
        frontier = [node_id]
        for _ in range(depth):
            if not frontier:
                break
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT e.src_id, e.tgt_id, e.keywords, e.description, e.weight,
                           n.entity_type, n.description
                    FROM retrieval_edges e
                    LEFT JOIN retrieval_nodes n
                      ON n.node_id = CASE WHEN e.src_id=%s THEN e.tgt_id ELSE e.src_id END
                    WHERE e.src_id = ANY(%s) OR e.tgt_id = ANY(%s)
                    LIMIT %s
                """, (frontier[0], frontier, frontier, limit))
                new_frontier = []
                for row in cur.fetchall():
                    src, tgt = row[0], row[1]
                    edges_out.append({"src": src, "tgt": tgt, "keywords": row[2],
                                      "description": row[3], "weight": row[4]})
                    for nid in (src, tgt):
                        if nid not in nodes_visited:
                            nodes_visited.add(nid)
                            new_frontier.append(nid)
                frontier = new_frontier[:50]

        # 获取节点详情
        with self.conn.cursor() as cur:
            cur.execute("""SELECT node_id, entity_type, description
                           FROM retrieval_nodes WHERE node_id = ANY(%s)""",
                        (list(nodes_visited),))
            nodes_out = [{"node_id": r[0], "entity_type": r[1],
                          "description": r[2]}
                         for r in cur.fetchall()]
        return {"nodes": nodes_out, "edges": edges_out}

    def stats(self) -> dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM retrieval_nodes")
            nodes = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM retrieval_edges")
            edges = cur.fetchone()[0]
        return {"nodes": nodes, "edges": edges}

    # ---------------------------------------------------------------- 批量迁移
    def migrate_from_graphml(self, graphml_path: str) -> dict[str, int]:
        """从 GraphML 文件批量迁移到 PostgreSQL（一次性操作，后续不再依赖文件）。"""
        import xml.etree.ElementTree as ET
        tree = ET.parse(graphml_path)
        root = tree.getroot()
        ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
        tag = lambda t: f"{{http://graphml.graphdrawing.org/xmlns}}{t}"

        nodes = []
        for n in root.iter(tag("node")):
            attrs = {}
            for d in n.findall(tag("data")):
                key = d.get("key")
                if key == "d0":
                    attrs["node_id"] = d.text or ""
                elif key == "d1":
                    attrs["entity_type"] = d.text or ""
                elif key == "d2":
                    attrs["description"] = d.text or ""
                elif key == "d3":
                    attrs["source_id"] = d.text or ""
                elif key == "d4":
                    attrs["file_path"] = d.text or ""
            if attrs.get("node_id"):
                nodes.append(attrs)

        edges = []
        for e in root.iter(tag("edge")):
            attrs = {}
            for d in e.findall(tag("data")):
                key = d.get("key")
                if key == "d7":
                    attrs["weight"] = float(d.text or 1.0)
                elif key == "d8":
                    attrs["description"] = d.text or ""
                elif key == "d9":
                    attrs["keywords"] = d.text or ""
                elif key == "d10":
                    attrs["source_id"] = d.text or ""
                elif key == "d11":
                    attrs["file_path"] = d.text or ""
            attrs["src_id"] = e.get("source", "")
            attrs["tgt_id"] = e.get("target", "")
            if attrs.get("src_id") and attrs.get("tgt_id"):
                edges.append(attrs)

        n_nodes = self.upsert_nodes_batch(nodes)
        n_edges = self.upsert_edges_batch(edges)
        log.info("migrated %d nodes, %d edges from GraphML", n_nodes, n_edges)
        return {"nodes": n_nodes, "edges": n_edges}
