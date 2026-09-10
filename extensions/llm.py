# -*- coding: utf-8 -*-
"""YCKI 共享 LLM 客户端（OpenAI 兼容网关，Qwen3 思考模式关闭，JSON 容错解析）。"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from config.settings import SETTINGS

# 禁用系统代理（代理会拦 LLM 网关请求导致超时）
_SESSION = requests.Session()
_SESSION.trust_env = False

log = logging.getLogger("ycki.llm")


def chat(messages: list[dict], max_tokens: int = 2000, temperature: float = 0.2,
         timeout: int = 180, retries: int = 2, model: str | None = None) -> str:
    """对话补全，返回 content 字符串。思考模式强制关闭。model 可覆盖（多模型金标）。"""
    body = {
        "model": model or SETTINGS.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    for attempt in range(retries + 1):
        try:
            r = _SESSION.post(f"{SETTINGS.gateway_url}/chat/completions",
                              headers={"Authorization": f"Bearer {SETTINGS.gateway_key}",
                                       "Content-Type": "application/json"},
                              json=body, timeout=timeout)
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"]
                return (msg.get("content") or "").strip()
            log.warning("llm http %d (attempt %d): %s", r.status_code, attempt, r.text[:150])
        except Exception as exc:
            log.warning("llm error (attempt %d): %s", attempt, exc)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("LLM 调用失败（重试耗尽）")


def embed(texts: list[str]) -> list[list[float]]:
    """bge-m3 批量嵌入。"""
    r = _SESSION.post(f"{SETTINGS.gateway_url}/embeddings",
                      headers={"Authorization": f"Bearer {SETTINGS.gateway_key}",
                               "Content-Type": "application/json"},
                      json={"model": SETTINGS.embed_model, "input": texts}, timeout=120)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda x: x["index"])
    return [d["embedding"] for d in data]


_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> dict[str, Any] | None:
    """容错解析 LLM JSON（剥 code fence、截取首尾大括号、json_repair 兜底）。"""
    if not text:
        return None
    m = _JSON_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    lo, hi = text.find("{"), text.rfind("}")
    if 0 <= lo < hi:
        frag = text[lo:hi + 1]
        try:
            return json.loads(frag)
        except Exception:
            pass
    if lo >= 0:
        # 截断 JSON：逐字符回退到最近的完整数组元素边界后用 json_repair
        frag = text[lo:]
        try:
            import json_repair
            repaired = json_repair.loads(frag)
            return repaired if isinstance(repaired, dict) else None
        except Exception:
            # 截断兜底：切到最后一个 "}] 或 "}" 处
            for cut in (frag.rfind('}'), frag.rfind(']')):
                if cut > 0:
                    try:
                        return json.loads(frag[:cut + 1] + (
                            "]" if frag.rstrip()[-1] in ',"' and frag.count("[") > frag.count("]") else ""))
                    except Exception:
                        continue
    return None
