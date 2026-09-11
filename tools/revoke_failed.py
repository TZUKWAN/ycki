# -*- coding: utf-8 -*-
"""全量证据独立复验 + REVOKED 失败 claim。"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2, psycopg2.extras
from config.settings import SETTINGS
from extensions.evidence.binder import bind

conn = psycopg2.connect(SETTINGS.pg_dsn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT c.claim_id, e.evidence_id, e.quote_span, e.chunk_id, r.text_path
    FROM claims c
    JOIN evidence e ON e.claim_id = c.claim_id
    JOIN resources r ON r.resource_id = e.resource_id
    WHERE c.status = 'ADMITTED'
""")
rows = cur.fetchall()
print(f"ADMITTED with evidence: {len(rows)}")

text_cache = {}
relocated = failed = 0
fail_claims = set()
for r in rows:
    tp = r["text_path"]
    if tp not in text_cache:
        text_cache[tp] = (Path(tp).read_text(encoding="utf-8", errors="replace")
                          if tp and Path(tp).exists() else None)
    full = text_cache[tp]
    part = None
    if r["chunk_id"] and "#" in r["chunk_id"]:
        try: part = int(r["chunk_id"].rsplit("#",1)[1])
        except: pass
    if full is None or part is None:
        failed += 1; fail_claims.add(r["claim_id"]); continue
    chunks = [full[i:i+1200] for i in range(0, len(full), 1200)]
    if part >= len(chunks):
        failed += 1; fail_claims.add(r["claim_id"]); continue
    m = bind(r["quote_span"], chunks[part])
    if m in ("EXACT","NORMALIZED"):
        relocated += 1
    else:
        failed += 1; fail_claims.add(r["claim_id"])

rate = relocated / len(rows) if rows else 0
print(f"独立复验: {relocated}/{len(rows)} = {rate:.4f}")
print(f"失败: {failed} claims")

# REVOKE 失败的
for cid in fail_claims:
    cur.execute("UPDATE claims SET status='REVOKED' WHERE claim_id=%s AND status='ADMITTED'", (str(cid),))
conn.commit()

# 终态
cur.execute("SELECT count(*) FROM claims WHERE status='ADMITTED'")
final = cur.fetchone()[0]
final_rate = relocated / (final + failed) if (final + failed) else 0
print(f"\n最终: ADMITTED={final}, 重定位率={relocated}/{len(rows)}={rate:.4f}")
conn.close()
