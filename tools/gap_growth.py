# -*- coding: utf-8 -*-
"""Phase 15：Gap 驱动自增长 runner。

流程：挑 OPEN 缺口 → planner 生成检索词 → 写 research_tasks
     → 用生成检索词跑采集（经 Scope Gate）→ 消费后重算覆盖。

用法：
  python tools/gap_growth.py --max-tasks 4      # 处理 4 个缺口
  python tools/gap_growth.py --plan-only        # 只生成任务不采集
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from config.settings import SETTINGS


def pick_gaps(conn, max_tasks: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT DISTINCT ON (region, period, topic, entity_type)
                   gap_id, gap_type, region, period, topic, entity_type, detail, priority
            FROM knowledge_gaps WHERE status='OPEN'
            ORDER BY region, period, topic, entity_type, priority DESC""")
        rows = [dict(r) for r in cur.fetchall()]
        rows.sort(key=lambda r: -r["priority"])
        return rows[:max_tasks]


def plan_tasks(conn, gaps: list[dict]) -> list[dict]:
    from extensions.gap.planner import expand_queries, make_task
    tasks = []
    for gap in gaps:
        queries = expand_queries(gap)
        if not queries:
            continue
        t = make_task(gap, queries)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO research_tasks
                   (task_id, gap_id, status, search_intent, queries)
                   VALUES (%s,%s,'PLANNED',%s,%s)
                   ON CONFLICT (task_id) DO NOTHING""",
                (t["task_id"], t["gap_id"], t["search_intent"],
                 t["queries"]))
            cur.execute("UPDATE knowledge_gaps SET status='RESEARCHING' WHERE gap_id=%s",
                        (gap["gap_id"],))
        tasks.append(t)
    conn.commit()
    return tasks


def write_topics(tasks: list[dict]) -> str:
    queries = []
    for t in tasks:
        queries.extend(t["queries"])
    topics = ROOT / "data" / "gap_topics.json"
    topics.write_text(json.dumps(
        {"themes": [{"topic": f"gap:{t['task_id']}", "queries": queries}]},
        ensure_ascii=False), encoding="utf-8")
    return str(topics)


def run_collect(topics: str, batch: str, max_total: int):
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "collect.py"),
                        "--batch", batch, "--topics", topics,
                        "--max-total", str(max_total), "--max-urls", "5",
                        "--wiki-per-query", "2", "--delay", "1.1"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=7200, cwd=str(ROOT))
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tasks", type=int, default=4)
    ap.add_argument("--max-total", type=int, default=80)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()

    conn = psycopg2.connect(SETTINGS.pg_dsn)
    gaps = pick_gaps(conn, a.max_tasks)
    conn.close()
    if not gaps:
        print("没有 OPEN 缺口（重算覆盖后会有新缺口产生）")
        return
    tasks = plan_tasks(conn2 := psycopg2.connect(SETTINGS.pg_dsn), gaps)
    conn2.close()
    print(f"生成 ResearchTask {len(tasks)} 个：")
    for t in tasks:
        print(f"  {t['task_id']} [{t['gap_id']}] {t['search_intent']} | 词: {t['queries'][:3]}")
    if a.plan_only:
        return
    topics = write_topics(tasks)
    code = run_collect(topics, "gap-growth", a.max_total)
    print(f"采集完成 exit={code}。采集结果经 Scope Gate 准入后，"
          f"重跑 python -m extensions.gap.coverage 复算缺口。")
    # 采集完成 → COLLECTED；RESOLVED/NO_GAIN 由 autonomous_growth 验证阶段判定
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    with conn.cursor() as cur:
        for t in tasks:
            cur.execute("UPDATE research_tasks SET status='COLLECTED', updated_at=now() "
                        "WHERE task_id=%s", (t["task_id"],))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
