# -*- coding: utf-8 -*-
"""§39-42 CONTESTED 自动分类与处置。

分类（八类）→ 确定性错误自动修 → TRUE_HISTORICAL_DISPUTE 保留 CONTESTED。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
import yaml

from config.settings import SETTINGS
from extensions.llm import chat, parse_json

CLASSIFY_PROMPT = """两条关于长江文化的主张相互冲突。请分类并给出处置建议。

主张A：{subject} --{predicate}--> {object_a}
A证据：「{quote_a}」（来源 {authority_a}）

主张B：{subject} --{predicate}--> {object_b}
B证据：「{quote_b}」（来源 {authority_b}）

分类（必须单选）：
- TRUE_HISTORICAL_DISPUTE：史料本身存在真实争议（学界的不同观点）
- TEMPORAL_DIFFERENCE：A/B 描述不同时期（应拆 TimeScope，均可成立）
- SPATIAL_DIFFERENCE：A/B 描述不同地点/粒度（应拆空间，均可成立）
- SOURCE_DISAGREEMENT：来源观点差异但事实可能都对
- ENTITY_RESOLUTION_ERROR：A/B 的实体其实应合并或应分裂
- PREDICATE_ERROR：谓词选择错了（应为其他谓词）
- EXTRACTION_ERROR：某条是抽取错误（证据不支持）
- NON_EXCLUSIVE_MULTI_VALUE：该谓词天然允许多值，两条都成立

输出严格 JSON：{{"classification":"...","action":"KEEP_CONTESTED|BOTH_CONDITIONAL|PREFER_A|PREFER_B|REJECT_BOTH","reason":"40字内"}}"""


def classify_and_fix(limit=300):
    preds = yaml.safe_load(open(ROOT / "yangtze" / "schema" / "predicates.yaml",
                                encoding="utf-8"))["predicates"]
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    stats = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.claim_id, c.subject_id, s.canonical_name AS subject,
                   c.predicate_id, c.object_id, o.canonical_name AS object_a,
                   e.quote_span AS quote_a,
                   (SELECT so.authority_level FROM evidence e2
                    JOIN resources r2 ON r2.resource_id=e2.resource_id
                    LEFT JOIN sources so ON so.source_id=r2.source_id
                    WHERE e2.claim_id=c.claim_id LIMIT 1) AS authority_a,
                   (SELECT c2.claim_id FROM claims c2
                    WHERE c2.subject_id=c.subject_id AND c2.predicate_id=c.predicate_id
                      AND c2.object_id<>c.object_id AND c2.status='ADMITTED' LIMIT 1) AS other_id,
                   (SELECT o2.canonical_name FROM claims c2
                    JOIN canonical_entities o2 ON o2.entity_id=c2.object_id
                    WHERE c2.subject_id=c.subject_id AND c2.predicate_id=c.predicate_id
                      AND c2.object_id<>c.object_id AND c2.status='ADMITTED' LIMIT 1) AS object_b,
                   (SELECT e3.quote_span FROM claims c3
                    JOIN evidence e3 ON e3.claim_id=c3.claim_id
                    WHERE c3.subject_id=c.subject_id AND c3.predicate_id=c.predicate_id
                      AND c3.object_id<>c.object_id AND c3.status='ADMITTED' LIMIT 1) AS quote_b,
                   (SELECT so3.authority_level FROM claims c3
                    JOIN evidence e3 ON e3.claim_id=c3.claim_id
                    JOIN resources r3 ON r3.resource_id=e3.resource_id
                    LEFT JOIN sources so3 ON so3.source_id=r3.source_id
                    WHERE c3.subject_id=c.subject_id AND c3.predicate_id=c.predicate_id
                      AND c3.object_id<>c.object_id AND c3.status='ADMITTED' LIMIT 1) AS authority_b
            FROM claims c
            JOIN canonical_entities s ON s.entity_id=c.subject_id
            JOIN canonical_entities o ON o.entity_id=c.object_id
            LEFT JOIN evidence e ON e.claim_id=c.claim_id
            WHERE c.status='CONTESTED' LIMIT %s""", (limit,))
        rows = cur.fetchall()
    print(f"CONTESTED: {len(rows)}")
    for r in rows:
        prompt = CLASSIFY_PROMPT.format(
            subject=r["subject"], predicate=r["predicate_id"],
            object_a=r["object_a"], quote_a=(r["quote_a"] or "")[:120],
            authority_a=r["authority_a"], object_b=r["object_b"] or "（无对手）",
            quote_b=(r["quote_b"] or "")[:120], authority_b=r["authority_b"])
        try:
            v = parse_json(chat([{"role": "user", "content": prompt}],
                                max_tokens=300)) or {}
        except Exception as exc:
            v = {"classification": "UNRESOLVED", "action": "KEEP_CONTESTED",
                 "reason": str(exc)[:60]}
        cls = v.get("classification", "UNRESOLVED")
        action = v.get("action", "KEEP_CONTESTED")
        stats[cls] = stats.get(cls, 0) + 1
        with conn.cursor() as cur2:
            cur2.execute(
                """INSERT INTO provenance_events
                   (object_type, object_id, action, actor, detail)
                   VALUES ('claim', %s, 'contested_classified',
                           'contest_adjudicator', %s)""",
                (str(r["claim_id"]), json.dumps(
                    {"classification": cls, "action": action,
                     "reason": v.get("reason", "")}, ensure_ascii=False)))
            # 自动处置规则（§41）
            if action == "BOTH_CONDITIONAL":
                cur2.execute("UPDATE claims SET status='CONDITIONAL' WHERE claim_id=%s",
                             (r["claim_id"],))
                if r["other_id"]:
                    cur2.execute("UPDATE claims SET status='CONDITIONAL' WHERE claim_id=%s",
                                 (r["other_id"],))
            elif action == "PREFER_A":
                cur2.execute("UPDATE claims SET status='ADMITTED' WHERE claim_id=%s",
                             (r["claim_id"],))
                if r["other_id"]:
                    cur2.execute("UPDATE claims SET status='SUPERSEDED' WHERE claim_id=%s",
                                 (r["other_id"],))
            elif action == "PREFER_B":
                cur2.execute("UPDATE claims SET status='SUPERSEDED' WHERE claim_id=%s",
                             (r["claim_id"],))
                if r["other_id"]:
                    cur2.execute("UPDATE claims SET status='ADMITTED' WHERE claim_id=%s",
                                 (r["other_id"],))
            elif action == "REJECT_BOTH":
                cur2.execute("UPDATE claims SET status='REJECTED' WHERE claim_id=%s",
                             (r["claim_id"],))
                if r["other_id"]:
                    cur2.execute("UPDATE claims SET status='REJECTED' WHERE claim_id=%s",
                                 (r["other_id"],))
            # KEEP_CONTESTED：保留（真实历史争议）
        conn.commit()
    conn.close()
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    classify_and_fix()
