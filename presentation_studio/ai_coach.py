"""AI assistant for refining presentation content and save instructions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from presentation_studio.config import PresentationSettings

COACH_SCHEMA = """
Return JSON only:
{
  "message": "Short reply to the user",
  "regenerate": true,
  "save_path": "optional full Windows path ending in .pptx or null",
  "patches": {
    "title": "optional",
    "subtitle": "optional",
    "footer": "optional slide footer text",
    "client_line": "optional cover client line",
    "closing": "optional",
    "what_paragraphs": ["optional list replacing what section body"],
    "opportunities": [["title", "body"], ...],
    "workstreams": [["title", "description"], ...],
    "team_roles": [["role", "description"], ...],
    "outputs": ["bullet", ...],
    "timeline": [["phase", "weeks", "activities"], ...]
  }
}
Rules:
- Only include patch keys that should change.
- If the user asks to save to a folder/path, set save_path (expand to .pptx filename if they give a folder).
- Set regenerate true when content changes require a new deck; false for save-only or questions.
"""


def extract_save_path_from_text(text: str) -> Path | None:
    """Heuristic: find Windows paths in user prompt."""
    patterns = [
        r"[A-Za-z]:\\(?:[^\\/\n\r\"<>|]+\\)*[^\\/\n\r\"<>|]*\.pptx",
        r"[A-Za-z]:\\(?:[^\\/\n\r\"<>|]+\\)+[^\\/\n\r\"<>|]+",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            p = Path(m.group(0).strip().strip('"'))
            if p.suffix.lower() != ".pptx":
                p = p / "presentation_output.pptx"
            return p
    return None


def _doc_summary(doc: dict[str, Any]) -> str:
    return json.dumps(
        {
            "title": doc.get("title"),
            "subtitle": doc.get("subtitle"),
            "opportunities_count": len(doc.get("opportunities") or []),
            "workstreams_count": len(doc.get("workstreams") or []),
            "team_roles_count": len(doc.get("team_roles") or []),
            "outputs_count": len(doc.get("outputs") or []),
            "timeline_count": len(doc.get("timeline") or []),
            "what_preview": (doc.get("what") or {}).get("paragraphs", [])[:2],
            "closing_preview": (doc.get("closing") or "")[:200],
        },
        indent=2,
    )[:6000]


def apply_patches(doc: dict[str, Any], patches: dict[str, Any]) -> dict[str, Any]:
    if not patches:
        return doc
    out = dict(doc)
    for key in ("title", "subtitle", "closing"):
        if key in patches and patches[key]:
            out[key] = patches[key]
    if patches.get("what_paragraphs"):
        what = dict(out.get("what") or {})
        what["paragraphs"] = patches["what_paragraphs"]
        out["what"] = what
    if patches.get("opportunities"):
        out["opportunities"] = [tuple(p) for p in patches["opportunities"]]
    if patches.get("workstreams"):
        out["workstreams"] = [tuple(w) for w in patches["workstreams"]]
    if patches.get("team_roles"):
        out["team_roles"] = [tuple(t) for t in patches["team_roles"]]
    if patches.get("outputs"):
        out["outputs"] = list(patches["outputs"])
    if patches.get("timeline"):
        out["timeline"] = [list(row) for row in patches["timeline"]]
    return out


def run_ai_coach(
    *,
    user_prompt: str,
    doc: dict[str, Any],
    settings: PresentationSettings,
    last_output_path: Path | None = None,
) -> dict[str, Any]:
    """
    Returns dict with keys: message, regenerate, save_path, doc (updated), patches.
    """
    save_guess = extract_save_path_from_text(user_prompt)
    if not settings.has_llm:
        patched = doc
        return {
            "message": (
                "OPENAI_API_KEY is not set in .env — AI editing is disabled. "
                "You can still generate and download decks. "
                + (f"Detected save path: {save_guess}" if save_guess else "")
            ),
            "regenerate": False,
            "save_path": save_guess,
            "doc": patched,
            "patches": {},
        }

    system = (
        "You help users refine a 15-slide PwC-style discovery presentation. "
        "Apply the user's instructions to the content patches. "
        + COACH_SCHEMA
    )
    user = (
        f"User request:\n{user_prompt}\n\n"
        f"Current output file: {last_output_path or 'not saved yet'}\n\n"
        f"Current content summary:\n{_doc_summary(doc)}"
    )

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "message": raw[:500],
            "regenerate": True,
            "save_path": save_guess,
            "doc": doc,
            "patches": {},
        }

    patches = data.get("patches") or {}
    updated = apply_patches(doc, patches)
    save_path = data.get("save_path")
    resolved_save: Path | None = None
    if save_path:
        resolved_save = Path(save_path)
        if resolved_save.suffix.lower() != ".pptx":
            resolved_save = resolved_save / f"{updated.get('title', 'presentation')[:40].strip()}.pptx"
    elif save_guess:
        resolved_save = save_guess

    return {
        "message": data.get("message", "Applied your changes."),
        "regenerate": bool(data.get("regenerate", True)),
        "save_path": resolved_save,
        "doc": updated,
        "patches": patches,
        "footer": patches.get("footer"),
        "client_line": patches.get("client_line"),
    }
