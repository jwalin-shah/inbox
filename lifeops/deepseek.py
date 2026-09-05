"""Bounded DeepSeek classification for already-collected LifeOps evidence."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

import httpx

from lifeops.triage import TRIAGE_CATEGORIES


def _tokenrouter_key() -> tuple[str, str]:
    key = os.environ.get("TOKENROUTER_API_KEY", "").strip()
    if key:
        return key, "environment"
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                "TOKENROUTER_API_KEY",
                "-s",
                "bridge-secrets",
                "-w",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "", "unavailable"
    key = result.stdout.strip()
    return key, "keychain" if key else "unavailable"


def _generation_options(model: str, evidence_count: int) -> dict[str, Any]:
    """Return the smallest compatible generation settings for a routed model."""
    options: dict[str, Any] = {
        "temperature": 0,
        "max_tokens": max(256, min(2048, 64 + evidence_count * 64)),
        "response_format": {"type": "json_object"},
    }
    # Kimi K3 always reasons; TokenRouter rejects an explicit disabled-thinking
    # setting for it. Low effort preserves bounded cost while keeping the
    # structured-output contract used by LifeOps.
    if "kimi-k3" in model.lower():
        options["reasoning_effort"] = "low"
    else:
        options["thinking"] = {"type": "disabled"}
    return options


def classify_items(items: list[dict[str, Any]], *, timeout: float = 120.0) -> dict[str, Any]:
    """Classify evidence summaries; never fetches sources or performs writes."""
    api_key, key_source = _tokenrouter_key()
    model = os.environ.get("LIFEOPS_TRIAGE_MODEL", "deepseek/deepseek-v4-pro").strip()
    base_url = os.environ.get("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1").rstrip("/")
    if not api_key:
        return {
            "status": "unavailable",
            "model": model,
            "reason": "TOKENROUTER_API_KEY_not_available_in_environment_or_keychain",
            "key_source": key_source,
            "labels": {},
        }
    if not items:
        return {"status": "ok", "model": model, "classified_items": 0, "labels": {}}

    bounded = items[:50]
    evidence = []
    for item in bounded:
        evidence.append(
            {
                "item_id": item.get("item_id", ""),
                "source": item.get("source", ""),
                "title": str(item.get("title", ""))[:240],
                "summary": str(item.get("summary") or item.get("reason") or "")[:500],
                "state": item.get("state", ""),
                "attention_class": item.get("attention_class", ""),
            }
        )
    system = (
        "Classify each already-collected personal inbox item. Do not invent facts, IDs, or actions. "
        "Return only JSON: {\"items\":[{\"item_id\":string,\"category\":string,\"confidence\":number}]}. "
        f"category must be one of: {', '.join(TRIAGE_CATEGORIES)}."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
        ],
        **_generation_options(model, len(evidence)),
    }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        message = (body.get("choices") or [{}])[0].get("message") or {}
        content = str(message.get("content") or "")
        parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip()))
        rows = parsed.get("items") if isinstance(parsed, dict) else []
    except (httpx.HTTPError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return {
            "status": "error",
            "model": model,
            "reason": f"{type(exc).__name__}:{str(exc)[:240]}",
            "labels": {},
        }

    allowed_ids = {str(item.get("item_id")) for item in bounded}
    labels: dict[str, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "")
        category = row.get("category")
        if item_id not in allowed_ids or category not in TRIAGE_CATEGORIES:
            continue
        try:
            confidence = max(0.0, min(1.0, float(row.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        labels[item_id] = {"category": category, "confidence": confidence}
    return {
        "status": "ok",
        "model": body.get("model", model),
        "key_source": key_source,
        "labels": labels,
        "returned_items": len(labels),
    }
