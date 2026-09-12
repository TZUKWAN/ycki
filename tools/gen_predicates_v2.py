#!/usr/bin/env python3
"""gen_predicates_v2.py — 从 v1 compact 谓词表生成 §13 Schema 2.0 谓词 YAML。

家族级默认 + 高风险谓词（§14）independent sources>=2。
输出：yangtze/schema/structural_predicates_v2.yaml（幂等，重跑覆盖）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "yangtze" / "schema" / "structural_predicates.yaml"
DST = ROOT / "yangtze" / "schema" / "structural_predicates_v2.yaml"

HIGH_RISK = {"developed_from", "emerged_from", "inherited_from", "transformed_into",
             "reconfigured_into", "influenced", "absorbed_from", "integrated_with",
             "fused_with", "hybridized_with", "contributed_to"}

FAMILIES = {
    "COMPOSITION": ("constitutes subsystem_of belongs_to_cultural_system manifestation_of representative_of",
                    dict(directed=True, symmetric=False, time_required=False, space_required=False,
                         mechanism_required=False, route_required=False,
                         knowledge_types=["ONTOLOGY_RELATION", "EVIDENCE_BACKED"])),
    "EVOLUTION": ("emerged_from developed_from inherited_from continued_as transformed_into "
                  "reconfigured_into revived_as localized_as institutionalized_as heritagized_as modernized_as",
                  dict(directed=True, symmetric=False, time_required=True, space_required=True,
                       mechanism_required=True, route_required=False, knowledge_types=["EVIDENCE_BACKED"])),
    "DIFFUSION": ("spread_to spread_along transmitted_via diffused_into",
                  dict(directed=True, symmetric=False, time_required=True, space_required=True,
                       mechanism_required=True, route_required=True, knowledge_types=["EVIDENCE_BACKED"])),
    "INTERACTION": ("interacted_with exchanged_with conflicted_with absorbed_from integrated_with "
                    "fused_with hybridized_with differentiated_from",
                    dict(directed=False, symmetric=True, time_required=True, space_required=True,
                         mechanism_required=True, route_required=False, knowledge_types=["EVIDENCE_BACKED"])),
    "CONDITION": ("originated_in enabled_by constrained_by mediated_by",
                  dict(directed=True, symmetric=False, time_required=False, space_required=True,
                       mechanism_required=True, route_required=False, knowledge_types=["EVIDENCE_BACKED"])),
    "CONTRIBUTION": ("contributed_to integrated_into",
                     dict(directed=True, symmetric=False, time_required=True, space_required=False,
                          mechanism_required=True, route_required=False, knowledge_types=["EVIDENCE_BACKED"])),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    src = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    v1 = src["predicates"]
    pid2fam = {p: fam for fam, (names, _) in FAMILIES.items() for p in names.split()}
    out = {"version": "structural_predicates_v2_0",
           "evidence_policy_version": "v2_0",
           "high_risk_min_independent_sources": 2,
           "primary_source_exception": ("仅当来源为一次文献(正史/地方志/档案原文)且经 evidence binder "
                                        "EXACT 验证时可豁免至1，须在 structural_admissions 记录豁免理由"),
           "predicates": []}
    items = dict(v1)
    if "influenced" not in items:  # §14 高风险清单要求，v1 缺失，补齐
        items["influenced"] = {"domain": ["CulturalSystem", "CulturalTradition", "Person", "Work"],
                               "range": ["CulturalSystem", "CulturalTradition", "Person", "Work"],
                               "description": "实质性影响（须有机制与过程证据，非时间先后）"}
    for pid, spec in items.items():
        spec = spec if isinstance(spec, dict) else {}
        fam = pid2fam.get(pid, "CONTRIBUTION")
        d = FAMILIES[fam][1]
        out["predicates"].append({
            "id": pid,
            "name": spec.get("description") or pid,
            "domain": spec.get("domain", ["any"]),
            "range": spec.get("range", ["any"]),
            "directed": d["directed"], "symmetric": d["symmetric"], "inverse": None,
            "cardinality": "many_to_many",
            "time_required": d["time_required"], "space_required": d["space_required"],
            "mechanism_required": d["mechanism_required"], "route_required": d["route_required"],
            "evidence_required": True,
            "minimum_independent_sources": 2 if pid in HIGH_RISK else 1,
            "allowed_knowledge_types": (["ONTOLOGY_RELATION"] if pid in ("constitutes", "subsystem_of")
                                        else d["knowledge_types"]),
            "family": fam,
            "description": spec.get("description") or pid,
            "positive_examples": ([f"{pid} 的正例须绑定可核验引文"] if pid not in
                                  ("developed_from", "interacted_with", "spread_to") else [
                                      "江南昆曲 developed_from 昆山腔（明代曲论与家班传承独立史料群）",
                                      "巴蜀 interacted_with 荆楚（盐铜贸易与战争的具体过程证据）",
                                      "端午竞渡 spread_to 吴越（各地竞渡记载与方志）"]),
            "negative_examples": (["时间先后不构成 developed_from；地理相邻不构成 interacted_with；"
                                   "同主题出现不构成 spread_to"] if pid in
                                  ("developed_from", "interacted_with", "spread_to") else []),
        })
    DST.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=110),
                   encoding="utf-8")
    print(f"written {len(out['predicates'])} predicates -> {DST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
