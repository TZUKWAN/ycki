-- ============================================================
-- 006_cultural_system_v2.sql
-- canonical_v2 文化系统层：运行库16张表的幂等重建
--
-- 来源：2026-09-13 运行库 pg_dump 审计（见 reports/V2_RUNTIME_GIT_DRIFT.md）。
-- 该批表此前仅存在于本地运行库，DDL/数据由未提交的临时脚本写入，
-- 不可复现。本迁移使其完全可复现：
--   * 全部 CREATE TABLE IF NOT EXISTS / CREATE SEQUENCE IF NOT EXISTS
--   * 约束通过 DO 块检查 pg_constraint 后添加（Postgres 不支持 ADD CONSTRAINT IF NOT EXISTS）
--   * 在任意库重复执行 exit=0、不破坏数据
-- 高阶结构对象（证据表/解释层/演化模式等）见 007_structural_layer_v2.sql
-- ============================================================

BEGIN;

-- ---------- 受控本体：文化系统 ----------
CREATE TABLE IF NOT EXISTS public.cultural_systems (
    system_id uuid DEFAULT gen_random_uuid() NOT NULL,
    system_name text NOT NULL,
    parent_system uuid,
    region_id uuid,
    system_level text DEFAULT 'REGIONAL',
    description text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_systems_pkey') THEN
    ALTER TABLE public.cultural_systems ADD CONSTRAINT cultural_systems_pkey PRIMARY KEY (system_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_systems_parent_system_fkey') THEN
    ALTER TABLE public.cultural_systems ADD CONSTRAINT cultural_systems_parent_system_fkey
      FOREIGN KEY (parent_system) REFERENCES public.cultural_systems(system_id);
  END IF;
END $$;

-- ---------- 受控本体：文化区域 ----------
CREATE TABLE IF NOT EXISTS public.cultural_regions (
    region_id uuid DEFAULT gen_random_uuid() NOT NULL,
    region_name text NOT NULL,
    parent_region uuid,
    entity_id uuid,
    hydro_basis text[],
    provinces text[],
    description text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_regions_pkey') THEN
    ALTER TABLE public.cultural_regions ADD CONSTRAINT cultural_regions_pkey PRIMARY KEY (region_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_regions_parent_region_fkey') THEN
    ALTER TABLE public.cultural_regions ADD CONSTRAINT cultural_regions_parent_region_fkey
      FOREIGN KEY (parent_region) REFERENCES public.cultural_regions(region_id);
  END IF;
END $$;

-- ---------- 受控本体：文化领域 ----------
CREATE TABLE IF NOT EXISTS public.cultural_domains (
    domain_id uuid DEFAULT gen_random_uuid() NOT NULL,
    domain_name text NOT NULL,
    parent_domain uuid,
    description text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_domains_pkey') THEN
    ALTER TABLE public.cultural_domains ADD CONSTRAINT cultural_domains_pkey PRIMARY KEY (domain_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_domains_parent_domain_fkey') THEN
    ALTER TABLE public.cultural_domains ADD CONSTRAINT cultural_domains_parent_domain_fkey
      FOREIGN KEY (parent_domain) REFERENCES public.cultural_domains(domain_id);
  END IF;
END $$;

-- ---------- 受控本体：历史分期 ----------
CREATE TABLE IF NOT EXISTS public.historical_phases (
    phase_id uuid DEFAULT gen_random_uuid() NOT NULL,
    phase_name text NOT NULL,
    parent_phase uuid,
    macro_phase text,
    start_year text,
    end_year text,
    approximate boolean DEFAULT false,
    description text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'historical_phases_pkey') THEN
    ALTER TABLE public.historical_phases ADD CONSTRAINT historical_phases_pkey PRIMARY KEY (phase_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'historical_phases_parent_phase_fkey') THEN
    ALTER TABLE public.historical_phases ADD CONSTRAINT historical_phases_parent_phase_fkey
      FOREIGN KEY (parent_phase) REFERENCES public.historical_phases(phase_id);
  END IF;
END $$;

-- ---------- 水系空间骨架 ----------
CREATE TABLE IF NOT EXISTS public.hydro_spatial_units (
    hsu_id uuid DEFAULT gen_random_uuid() NOT NULL,
    hsu_name text NOT NULL,
    hsu_type text NOT NULL,
    parent_hsu uuid,
    province text,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT hydro_spatial_units_hsu_type_check CHECK ((hsu_type = ANY (ARRAY[
        'Basin'::text, 'MainStem'::text, 'RiverSection'::text, 'Tributary'::text,
        'Lake'::text, 'Wetland'::text, 'Delta'::text, 'Plain'::text,
        'MountainRegion'::text, 'Valley'::text, 'SubBasin'::text,
        'WaterTransportCorridor'::text])))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_units_pkey') THEN
    ALTER TABLE public.hydro_spatial_units ADD CONSTRAINT hydro_spatial_units_pkey PRIMARY KEY (hsu_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_units_hsu_name_hsu_type_key') THEN
    ALTER TABLE public.hydro_spatial_units ADD CONSTRAINT hydro_spatial_units_hsu_name_hsu_type_key
      UNIQUE (hsu_name, hsu_type);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_units_parent_hsu_fkey') THEN
    ALTER TABLE public.hydro_spatial_units ADD CONSTRAINT hydro_spatial_units_parent_hsu_fkey
      FOREIGN KEY (parent_hsu) REFERENCES public.hydro_spatial_units(hsu_id);
  END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS public.hydro_spatial_relations_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE TABLE IF NOT EXISTS public.hydro_spatial_relations (
    id bigint NOT NULL DEFAULT nextval('public.hydro_spatial_relations_id_seq'),
    from_hsu uuid NOT NULL,
    relation text NOT NULL,
    to_hsu uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT hydro_spatial_relations_relation_check CHECK ((relation = ANY (ARRAY[
        'tributary_of'::text, 'flows_into'::text, 'part_of_basin'::text,
        'upstream_of'::text, 'downstream_of'::text, 'hydrologically_connects'::text,
        'passes_through'::text, 'adjacent_basin'::text])))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_relations_pkey') THEN
    ALTER TABLE public.hydro_spatial_relations ADD CONSTRAINT hydro_spatial_relations_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_relations_from_hsu_fkey') THEN
    ALTER TABLE public.hydro_spatial_relations ADD CONSTRAINT hydro_spatial_relations_from_hsu_fkey
      FOREIGN KEY (from_hsu) REFERENCES public.hydro_spatial_units(hsu_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_spatial_relations_to_hsu_fkey') THEN
    ALTER TABLE public.hydro_spatial_relations ADD CONSTRAINT hydro_spatial_relations_to_hsu_fkey
      FOREIGN KEY (to_hsu) REFERENCES public.hydro_spatial_units(hsu_id);
  END IF;
END $$;

-- ---------- 水系 ↔ 行政区 显式映射（Place 与 HydroSpatial 分离，§16.4） ----------
CREATE SEQUENCE IF NOT EXISTS public.hydro_place_mapping_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE TABLE IF NOT EXISTS public.hydro_place_mapping (
    id bigint NOT NULL DEFAULT nextval('public.hydro_place_mapping_id_seq'),
    place_entity_id uuid NOT NULL,
    hsu_id uuid NOT NULL,
    mapping_type text DEFAULT 'located_in',
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_place_mapping_pkey') THEN
    ALTER TABLE public.hydro_place_mapping ADD CONSTRAINT hydro_place_mapping_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_place_mapping_place_entity_id_hsu_id_key') THEN
    ALTER TABLE public.hydro_place_mapping ADD CONSTRAINT hydro_place_mapping_place_entity_id_hsu_id_key
      UNIQUE (place_entity_id, hsu_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'hydro_place_mapping_hsu_id_fkey') THEN
    ALTER TABLE public.hydro_place_mapping ADD CONSTRAINT hydro_place_mapping_hsu_id_fkey
      FOREIGN KEY (hsu_id) REFERENCES public.hydro_spatial_units(hsu_id);
  END IF;
END $$;

-- ---------- 系统成员关系 ----------
CREATE TABLE IF NOT EXISTS public.system_memberships (
    membership_id uuid DEFAULT gen_random_uuid() NOT NULL,
    object_id uuid NOT NULL,
    system_id uuid,
    region_id uuid,
    domain_id uuid,
    membership_role text DEFAULT 'CARRIER' NOT NULL,
    region text,
    period text,
    domain text,
    strength real DEFAULT 0.5,
    confidence real DEFAULT 0.5,
    evidence_id uuid,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'system_memberships_pkey') THEN
    ALTER TABLE public.system_memberships ADD CONSTRAINT system_memberships_pkey PRIMARY KEY (membership_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'system_memberships_object_id_system_id_key') THEN
    ALTER TABLE public.system_memberships ADD CONSTRAINT system_memberships_object_id_system_id_key
      UNIQUE (object_id, system_id);
  END IF;
END $$;

-- ---------- 结构关系 ----------
CREATE TABLE IF NOT EXISTS public.structural_relations (
    relation_id uuid DEFAULT gen_random_uuid() NOT NULL,
    subject_id uuid NOT NULL,
    predicate text NOT NULL,
    object_id uuid NOT NULL,
    valid_from text,
    valid_to text,
    spatial_scope text,
    confidence real DEFAULT 0.5,
    status text DEFAULT 'CANDIDATE',
    evidence_count integer DEFAULT 0,
    independent_source_count integer DEFAULT 0,
    model text,
    prompt_version text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'structural_relations_pkey') THEN
    ALTER TABLE public.structural_relations ADD CONSTRAINT structural_relations_pkey PRIMARY KEY (relation_id);
  END IF;
END $$;

-- ---------- 文化传统 ----------
CREATE TABLE IF NOT EXISTS public.cultural_traditions (
    tradition_id uuid DEFAULT gen_random_uuid() NOT NULL,
    tradition_name text NOT NULL,
    domain_id uuid,
    origin text,
    historical_development text,
    regional_variants jsonb DEFAULT '[]'::jsonb,
    description text,
    status text DEFAULT 'CANDIDATE',
    confidence real,
    resource_id text,
    quote_span text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_traditions_pkey') THEN
    ALTER TABLE public.cultural_traditions ADD CONSTRAINT cultural_traditions_pkey PRIMARY KEY (tradition_id);
  END IF;
END $$;

-- ---------- 文化过程 ----------
CREATE TABLE IF NOT EXISTS public.cultural_processes (
    process_id uuid DEFAULT gen_random_uuid() NOT NULL,
    process_name text NOT NULL,
    process_type text NOT NULL,
    description text,
    start_time text,
    end_time text,
    historical_phase uuid,
    origin_region text,
    destination_region text,
    hydro_network text[],
    transport_network text[],
    actors text[],
    carriers text[],
    mechanisms text,
    causes text,
    outcomes text,
    long_term_impacts text,
    status text DEFAULT 'CANDIDATE',
    confidence real,
    resource_id text,
    quote_span text,
    evidence_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_processes_pkey') THEN
    ALTER TABLE public.cultural_processes ADD CONSTRAINT cultural_processes_pkey PRIMARY KEY (process_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_processes_historical_phase_fkey') THEN
    ALTER TABLE public.cultural_processes ADD CONSTRAINT cultural_processes_historical_phase_fkey
      FOREIGN KEY (historical_phase) REFERENCES public.historical_phases(phase_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.process_stages (
    stage_id uuid DEFAULT gen_random_uuid() NOT NULL,
    process_id uuid NOT NULL,
    stage_name text NOT NULL,
    stage_order integer,
    time_range text,
    description text
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'process_stages_pkey') THEN
    ALTER TABLE public.process_stages ADD CONSTRAINT process_stages_pkey PRIMARY KEY (stage_id);
  END IF;
END $$;

-- ---------- 文化流动 ----------
CREATE TABLE IF NOT EXISTS public.cultural_flows (
    flow_id uuid DEFAULT gen_random_uuid() NOT NULL,
    process_id uuid,
    flow_type text NOT NULL,
    origin text,
    destination text,
    via text,
    time_range text,
    carrier text,
    content text,
    mechanism text,
    impact text,
    quote_span text,
    resource_id text,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cultural_flows_pkey') THEN
    ALTER TABLE public.cultural_flows ADD CONSTRAINT cultural_flows_pkey PRIMARY KEY (flow_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.transmission_routes (
    route_id uuid DEFAULT gen_random_uuid() NOT NULL,
    route_name text NOT NULL,
    route_type text NOT NULL,
    description text,
    origin text,
    destination text,
    hydro_links text[],
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'transmission_routes_pkey') THEN
    ALTER TABLE public.transmission_routes ADD CONSTRAINT transmission_routes_pkey PRIMARY KEY (route_id);
  END IF;
END $$;

-- ---------- 结构缺口 / 研究任务 ----------
CREATE TABLE IF NOT EXISTS public.structural_gaps (
    gap_id uuid DEFAULT gen_random_uuid() NOT NULL,
    gap_type text NOT NULL,
    target_entity uuid,
    target_system uuid,
    target_region text,
    target_period text,
    target_domain text,
    current_structure jsonb DEFAULT '{}'::jsonb,
    missing_structure jsonb DEFAULT '{}'::jsonb,
    candidate_hypotheses text[],
    priority real DEFAULT 0.5,
    status text DEFAULT 'OPEN',
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'structural_gaps_pkey') THEN
    ALTER TABLE public.structural_gaps ADD CONSTRAINT structural_gaps_pkey PRIMARY KEY (gap_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.structural_research_tasks (
    task_id uuid DEFAULT gen_random_uuid() NOT NULL,
    gap_id uuid,
    research_question text NOT NULL,
    structural_gap_type text,
    target_object text,
    current_known_structure text,
    missing_structure text,
    candidate_hypotheses text[],
    required_evidence text,
    search_strategy text[],
    expected_output_type text,
    resolution_criteria text,
    status text DEFAULT 'PLANNED' NOT NULL,
    attempt_count integer DEFAULT 0,
    resolution_evidence jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'structural_research_tasks_pkey') THEN
    ALTER TABLE public.structural_research_tasks ADD CONSTRAINT structural_research_tasks_pkey PRIMARY KEY (task_id);
  END IF;
END $$;

COMMIT;
