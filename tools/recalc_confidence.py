# -*- coding: utf-8 -*-
"""§九：全量重算 Claim confidence（独立证据单位=cluster，可解释模型）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from config.settings import SETTINGS
from extensions.admission.claim_gate import _confidence
from extensions.extraction.extract import _PRED


def main():
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    updated = 0
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.claim_id, c.status, c.predicate_id,
                   COALESCE(t.raw_text,'') AS time_text,
                   count(DISTINCT COALESCE(r.source_cluster_id, r.resource_id)) AS indep,
                   count(DISTINCT e.resource_id) AS raw_res,
                   count(DISTINCT e.source_id) AS raw_src,
                   count(e.id) AS raw_ev,
                   MAX(COALESCE(so.authority_level,'UNKNOWN')) AS authority,
                   MAX(e.match_status) AS match
            FROM claims c
            LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
            LEFT JOIN evidence e ON e.claim_id=c.claim_id
            LEFT JOIN resources r ON r.resource_id=e.resource_id
            LEFT JOIN sources so ON so.source_id=r.source_id
            WHERE c.status IN ('ADMITTED','SUPPORTED','CONTESTED')
            GROUP BY c.claim_id, c.status, c.predicate_id, t.raw_text""")
        rows = cur.fetchall()
        for r in rows:
            c, explanation = _confidence(
                r["indep"], r["authority"], r["match"] or "NORMALIZED",
                r["time_text"], r["predicate_id"], r["status"])
            cur.execute("""UPDATE claims SET confidence=%s WHERE claim_id=%s""",
                        (c, r["claim_id"]))
            cur.execute(
                """INSERT INTO claim_admissions
                   (claim_id, stage, result, detail, model, prompt_version)
                   VALUES (%s,'admission','PASS',%s,'recalc','confidence_v2')""",
                (r["claim_id"], __import__("json").dumps(
                    {"confidence_explanation": explanation,
                     "independent_evidence_count": r["indep"],
                     "raw_evidence_count": r["raw_ev"],
                     "distinct_resource_count": r["raw_res"],
                     "distinct_domain_count": r["raw_src"],
                     "recalculated": True}, ensure_ascii=False)))
            updated += 1
    conn.commit()
    conn.close()
    print(f"confidence 重算完成: {updated} 条")


if __name__ == "__main__":
    main()
