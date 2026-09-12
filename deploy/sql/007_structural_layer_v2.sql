-- ============================================================
-- 007_structural_layer_v2.sql
-- canonical_v2 结构层补全与合规升级
--
-- 覆盖目标 §5.1 缺失对象 + §11 分期/演化模式分离 + §18 membership 锚点结构
-- + §24-27 无证据结构关系降级。幂等：可重复执行。
-- ============================================================

BEGIN;

-- ============================================================
-- A. 自然键唯一索引（builder 幂等 upsert 的前提）
-- ============================================================
CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_systems_name ON public.cultural_systems (system_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_regions_name ON public.cultural_regions (region_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_domains_name ON public.cultural_domains (domain_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_historical_phases_name ON public.historical_phases (phase_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hydro_relation_triple ON public.hydro_spatial_relations (from_hsu, relation, to_hsu);
CREATE INDEX IF NOT EXISTS idx_system_memberships_object ON public.system_memberships (object_id);
CREATE INDEX IF NOT EXISTS idx_structural_relations_subject ON public.structural_relations (subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_structural_relations_object ON public.structural_relations (object_id, predicate);

-- ============================================================
-- B. HistoricalPhase ←→ MacroEvolutionPattern 多对多（§11）
--    禁止"一个朝代=一个演化机制"：旧 macro_phase 单值列迁移进 junction 后冻结
-- ============================================================
CREATE TABLE IF NOT EXISTS public.macro_evolution_patterns (
    pattern_id uuid DEFAULT gen_random_uuid() NOT NULL,
    pattern_code text NOT NULL,
    pattern_name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now()
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'macro_evolution_patterns_pkey') THEN
    ALTER TABLE public.macro_evolution_patterns ADD CONSTRAINT macro_evolution_patterns_pkey PRIMARY KEY (pattern_id);
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_macro_evolution_code ON public.macro_evolution_patterns (pattern_code);

CREATE TABLE IF NOT EXISTS public.historical_phase_patterns (
    id bigint GENERATED ALWAYS AS IDENTITY,
    phase_id uuid NOT NULL,
    pattern_id uuid NOT NULL,
    note text,
    PRIMARY KEY (id)
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'historical_phase_patterns_phase_fkey') THEN
    ALTER TABLE public.historical_phase_patterns ADD CONSTRAINT historical_phase_patterns_phase_fkey
      FOREIGN KEY (phase_id) REFERENCES public.historical_phases(phase_id);
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'historical_phase_patterns_pattern_fkey') THEN
    ALTER TABLE public.historical_phase_patterns ADD CONSTRAINT historical_phase_patterns_pattern_fkey
      FOREIGN KEY (pattern_id) REFERENCES public.macro_evolution_patterns(pattern_id);
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_phase_pattern ON public.historical_phase_patterns (phase_id, pattern_id);

-- ============================================================
-- C. system_memberships 锚点结构升级（§18.1）
--    存量 10,004 条由 legacy 地理规则生成、无派生记录 → 全部降级 CANDIDATE
--    等待 membership 重建管线重新推导（geo-only 永不 ADMITTED，§19-20）
-- ============================================================
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS spatial_anchor jsonb;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS temporal_anchor jsonb;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS domain_anchor jsonb;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS process_anchor jsonb;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS anchor_count integer DEFAULT 0;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS membership_strength real;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS derivation_method text;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS derivation_reason text;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS supporting_claim_ids uuid[];
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS supporting_evidence_ids uuid[];
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS rule_version text;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE public.system_memberships ADD COLUMN IF NOT EXISTS status text DEFAULT 'CANDIDATE';

-- 存量数据：无锚点证明 → CANDIDATE + 派生来源标记（幂等：只处理未标记行）
UPDATE public.system_memberships
   SET status = 'CANDIDATE',
       derivation_method = COALESCE(derivation_method, 'legacy_geo_rule_v0'),
       derivation_reason = COALESCE(derivation_reason, 'legacy row without anchor proof; pending rebuild'),
       anchor_count = COALESCE(anchor_count, 0),
       rule_version = COALESCE(rule_version, 'legacy_unversioned')
 WHERE derivation_method IS NULL;

-- ============================================================
-- D. structural_relations 合规升级（§24-27）
--    knowledge_type 区分 ONTOLOGY_RELATION / EVIDENCE_BACKED；
--    0 证据高风险边全部降级 CANDIDATE
-- ============================================================
ALTER TABLE public.structural_relations ADD COLUMN IF NOT EXISTS knowledge_type text;
ALTER TABLE public.structural_relations ADD COLUMN IF NOT EXISTS evidence_policy_version text;
ALTER TABLE public.structural_relations ADD COLUMN IF NOT EXISTS downgrade_reason text;

-- 0 独立证据的关系不得保持 ADMITTED（幂等：只动违规行）
UPDATE public.structural_relations
   SET status = 'CANDIDATE',
       knowledge_type = COALESCE(knowledge_type, 'EVIDENCE_BACKED'),
       evidence_policy_version = COALESCE(evidence_policy_version, 'v2_0'),
       downgrade_reason = COALESCE(downgrade_reason,
           'evidence_count=0 at v2 audit; high-risk predicate requires >=2 independent source clusters')
 WHERE status = 'ADMITTED'
   AND COALESCE(independent_source_count, 0) = 0
   AND COALESCE(evidence_count, 0) = 0;

-- ============================================================
-- E. 目标 §5.1 缺失对象
-- ============================================================

-- E1. 结构关系证据
CREATE TABLE IF NOT EXISTS public.structural_relation_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY,
    relation_id uuid NOT NULL,
    claim_id uuid,
    evidence_id uuid,
    resource_id text,
    quote_span text,
    PRIMARY KEY (id)
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'structural_relation_evidence_relation_fkey') THEN
    ALTER TABLE public.structural_relation_evidence ADD CONSTRAINT structural_relation_evidence_relation_fkey
      FOREIGN KEY (relation_id) REFERENCES public.structural_relations(relation_id) ON DELETE CASCADE;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_sre_relation ON public.structural_relation_evidence (relation_id);

-- E2. 传统变体 / 传统证据
CREATE TABLE IF NOT EXISTS public.tradition_variants (
    variant_id uuid DEFAULT gen_random_uuid() NOT NULL,
    tradition_id uuid NOT NULL,
    variant_name text NOT NULL,
    region text,
    system_id uuid,
    distinct_features text,
    PRIMARY KEY (variant_id)
);
CREATE INDEX IF NOT EXISTS idx_tradition_variants_tradition ON public.tradition_variants (tradition_id);

CREATE TABLE IF NOT EXISTS public.tradition_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY,
    tradition_id uuid NOT NULL,
    claim_id uuid,
    evidence_id uuid,
    resource_id text,
    evidence_role text,
    quote_span text,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_tradition_evidence_tradition ON public.tradition_evidence (tradition_id);

-- E3. 过程参与者 / 路线 / 证据
CREATE TABLE IF NOT EXISTS public.process_participants (
    id bigint GENERATED ALWAYS AS IDENTITY,
    process_id uuid NOT NULL,
    participant_entity_id uuid,
    participant_role text,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_process_participants_process ON public.process_participants (process_id);

CREATE TABLE IF NOT EXISTS public.process_routes (
    id bigint GENERATED ALWAYS AS IDENTITY,
    process_id uuid NOT NULL,
    route_id uuid,
    hydro_hsu_id uuid,
    route_role text,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_process_routes_process ON public.process_routes (process_id);

CREATE TABLE IF NOT EXISTS public.process_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY,
    process_id uuid NOT NULL,
    field_name text NOT NULL,
    claim_id uuid,
    evidence_id uuid,
    resource_id text,
    quote_span text,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_process_evidence_process ON public.process_evidence (process_id, field_name);

-- E4. 文化景观 / 制度谱系 / 人地互动
CREATE TABLE IF NOT EXISTS public.cultural_landscapes (
    landscape_id uuid DEFAULT gen_random_uuid() NOT NULL,
    landscape_name text NOT NULL,
    landscape_type text,
    hsu_ids uuid[],
    system_ids uuid[],
    description text,
    status text DEFAULT 'CANDIDATE',
    PRIMARY KEY (landscape_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cultural_landscapes_name ON public.cultural_landscapes (landscape_name);

CREATE TABLE IF NOT EXISTS public.institutional_lineages (
    lineage_id uuid DEFAULT gen_random_uuid() NOT NULL,
    lineage_name text NOT NULL,
    institution_type text,
    founder_entity_id uuid,
    successor_of uuid,
    time_span text,
    description text,
    status text DEFAULT 'CANDIDATE',
    PRIMARY KEY (lineage_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_institutional_lineages_name ON public.institutional_lineages (lineage_name);

CREATE TABLE IF NOT EXISTS public.human_environment_interactions (
    interaction_id uuid DEFAULT gen_random_uuid() NOT NULL,
    interaction_name text NOT NULL,
    interaction_type text,
    hsu_id uuid,
    system_id uuid,
    time_span text,
    mechanism text,
    outcome text,
    description text,
    status text DEFAULT 'CANDIDATE',
    PRIMARY KEY (interaction_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_human_env_interactions_name ON public.human_environment_interactions (interaction_name);

-- E5. 解释层（§44-45）：事实与学术解释严格分层
CREATE TABLE IF NOT EXISTS public.interpretations (
    interpretation_id uuid DEFAULT gen_random_uuid() NOT NULL,
    statement text NOT NULL,
    knowledge_type text NOT NULL DEFAULT 'SCHOLARLY_INTERPRETATION'
        CHECK (knowledge_type IN ('FACT','SCHOLARLY_INTERPRETATION','STRUCTURAL_INFERENCE','SYSTEM_HYPOTHESIS')),
    author text,
    source_ref text,
    scope text,
    subject_kind text,
    subject_id uuid,
    supporting_resource_ids text[],
    contradicting_resource_ids text[],
    status text DEFAULT 'CANDIDATE',
    confidence real,
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (interpretation_id)
);

CREATE TABLE IF NOT EXISTS public.interpretation_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY,
    interpretation_id uuid NOT NULL,
    evidence_id uuid,
    claim_id uuid,
    resource_id text,
    stance text CHECK (stance IN ('SUPPORT','CONTRADICT','CONTEXT')),
    PRIMARY KEY (id)
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'interpretation_evidence_interp_fkey') THEN
    ALTER TABLE public.interpretation_evidence ADD CONSTRAINT interpretation_evidence_interp_fkey
      FOREIGN KEY (interpretation_id) REFERENCES public.interpretations(interpretation_id) ON DELETE CASCADE;
  END IF;
END $$;

-- E6. 结构准入记录（§13-14 / §48 结构准入审计轨迹）
CREATE TABLE IF NOT EXISTS public.structural_admissions (
    admission_id uuid DEFAULT gen_random_uuid() NOT NULL,
    object_kind text NOT NULL,
    object_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('ADMITTED','SUPPORTED','CANDIDATE','REJECTED','CONTESTED')),
    checks jsonb DEFAULT '{}'::jsonb,
    evidence_coverage real,
    independent_source_clusters integer,
    rule_version text,
    model_version text,
    reason text,
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (admission_id)
);
CREATE INDEX IF NOT EXISTS idx_structural_admissions_object ON public.structural_admissions (object_kind, object_id);

COMMIT;
