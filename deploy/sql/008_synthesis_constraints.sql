-- ============================================================
-- 008_synthesis_constraints.sql
-- 结构合成层（Tradition/Process/Flow）约束：名称唯一 + 准入幂等
-- ============================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_traditions_name ON public.cultural_traditions (tradition_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_processes_name ON public.cultural_processes (process_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_structural_admissions_object_decision
    ON public.structural_admissions (object_kind, object_id, decision, COALESCE(rule_version,''));
CREATE INDEX IF NOT EXISTS idx_claims_subject ON public.claims (subject_id, status);
CREATE INDEX IF NOT EXISTS idx_claims_object ON public.claims (object_id, status);
CREATE INDEX IF NOT EXISTS idx_events_entity ON public.events (entity_id, status);

COMMIT;
