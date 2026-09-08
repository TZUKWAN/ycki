# -*- coding: utf-8 -*-
"""YCKI 统一配置层（Phase 16 去硬编码）。

优先级：环境变量 > config/.env > 内置默认。
密钥不入 Git（config/.env 已 gitignore）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PIPELINE_VERSION = "canonical_v1"


def _load_env_file(path: Path) -> None:
    """极简 dotenv 加载（不覆盖已有环境变量）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env_file(ROOT / "config" / ".env")
_load_env_file(ROOT / "deploy" / "lightrag" / ".env")


@dataclass
class Settings:
    # 服务
    lightrag_url: str = os.environ.get("YCKI_LR_URL", "http://localhost:9621")
    lightrag_api_key: str = os.environ.get("LIGHTRAG_API_KEY", "")
    console_port: int = int(os.environ.get("YCKI_CONSOLE_PORT", "9622"))

    # LLM 网关（OpenAI 兼容）
    gateway_url: str = os.environ.get("YCKI_GATEWAY_URL", "http://218.197.140.7:3001/v1")
    gateway_key: str = os.environ.get(
        "YCKI_GATEWAY_KEY", os.environ.get("LLM_BINDING_API_KEY", ""))
    llm_model: str = os.environ.get("YCKI_LLM_MODEL", "Qwen3.6-35B-A3B")
    embed_model: str = os.environ.get("YCKI_EMBED_MODEL", "bge-m3")

    # PostgreSQL
    pg_dsn: str = os.environ.get(
        "YCKI_PG_DSN",
        "host=127.0.0.1 port=5433 dbname=ycki user=postgres password=ycki_pg_2026")

    # 路径
    lake_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "YCKI_LAKE_DIR", str(ROOT / "data" / "lake"))))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "YCKI_DATA_DIR", str(ROOT / "data"))))

    # 版本
    pipeline_version: str = PIPELINE_VERSION
    prompt_scope_resource: str = "resource_scope_v1"
    prompt_scope_chunk: str = "chunk_scope_v1"
    prompt_extraction: str = "entity_event_claim_extraction_v1"
    prompt_resolution: str = "entity_resolution_v1"
    prompt_admission: str = "claim_admission_v1"
    prompt_gap: str = "gap_detection_v1"


SETTINGS = Settings()
