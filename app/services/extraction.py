"""Heuristic and optional LLM process extraction from document text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class ExtractedActivity:
    name: str
    actor: str
    raci_hint: str
    confidence: float


@dataclass
class ExtractionResult:
    processes: list[dict]
    roles: list[dict]
    ambiguities: list[dict]
    mode: str


def heuristic_extract(text: str) -> ExtractionResult:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    activities: list[ExtractedActivity] = []
    roles: set[str] = set()
    step_re = re.compile(r"^(\d+[\.\)]\s*|-\s*)(.+)$", re.I)
    for line in lines[:200]:
        m = step_re.match(line)
        if m:
            name = m.group(2)[:120]
            actor = "Unassigned"
            raci = "R"
            if re.search(r"\b(approv|sign.?off|authoriz)\b", name, re.I):
                raci = "A"
            elif re.search(r"\b(consult|review)\b", name, re.I):
                raci = "C"
            elif re.search(r"\b(inform|notify)\b", name, re.I):
                raci = "I"
            activities.append(ExtractedActivity(name, actor, raci, 0.55))
        elif re.search(r"\b(role|owner|responsible)\b", line, re.I):
            parts = re.split(r"[:–-]", line, maxsplit=1)
            if len(parts) == 2:
                roles.add(parts[1].strip()[:80])

    if not activities and lines:
        for line in lines[:15]:
            activities.append(ExtractedActivity(line[:100], "Unassigned", "R", 0.4))

    proc = {
        "name": "Extracted Process",
        "owner": next(iter(roles), "Process Owner"),
        "activities": [
            {
                "name": a.name,
                "actor": a.actor,
                "raci_hint": a.raci_hint,
                "confidence": a.confidence,
                "sequence": i + 1,
            }
            for i, a in enumerate(activities)
        ],
    }
    return ExtractionResult(
        processes=[proc] if activities else [],
        roles=[{"name": r, "department": None} for r in roles],
        ambiguities=[{"sentence": "Heuristic extraction — review all items.", "reason": "No LLM key configured or fallback mode."}],
        mode="heuristic",
    )


async def llm_extract(text: str) -> ExtractionResult:
    settings = get_settings()
    if not settings.has_llm:
        return heuristic_extract(text)

    snippet = text[:12000]
    prompt = (
        "Extract processes and activities from the following document. "
        "Return JSON with keys: processes (name, owner, activities with name, actor, raci_hint, sequence), "
        "roles (name, department), ambiguities (sentence, reason). "
        "Use RACI hints R/A/C/I only.\n\nDocument:\n" + snippet
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": "You are a process mapping assistant. Respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return ExtractionResult(
            processes=data.get("processes", []),
            roles=data.get("roles", []),
            ambiguities=data.get("ambiguities", []),
            mode="llm",
        )
