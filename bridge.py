"""Local model drafts the brief, frontier model answers it.

This is an explicit two-tier handoff: the cheap local model turns a loose user
request into a compact, structured brief; the (optionally configured) frontier
API answers only that brief. The harness keeps both messages and labels which
model produced which, so nothing is passed off as local knowledge.

Frontier egress is recorded in data/egress.jsonl by llm.chat like any other
API call. Nothing is sent unless ATLAS_FRONTIER_* is configured.
"""

from __future__ import annotations

import json
import re

import config
import llm

BRIEF_SYSTEM = """Return JSON ONLY:
{"goal":"the user's actual request","what_matters":["key constraints"],
 "missing":"what the answer must establish","instructions":"how a strong model should answer"}
Use at most 6 words per item. Never answer the question here."""

ANSWER_SYSTEM = """Answer the user's goal using the local model's brief.
Keep the original question authoritative. Be direct, structured and cite real
sources only if they are in the brief. Never invent a source or a number."""


def _brief(question: str, model: str | None) -> dict:
    try:
        reply = llm.chat(
            [{"role": "system", "content": BRIEF_SYSTEM},
             {"role": "user", "content": question}],
            None, tier="local", model=model, temperature=0, timeout=25,
            max_tokens=300, response_format={"type": "json_object"},
        )
        data = json.loads(reply.content or "{}")
        if isinstance(data, dict) and data.get("goal"):
            return data
    except Exception:
        pass
    # Deterministic brief: works when the local model is slow or offline.
    return {
        "goal": question,
        "what_matters": re.findall(r"\b(?:how many|when|why|compare|explain|verify)\b",
                                   question.lower(), re.I),
        "missing": "a direct answer to the question",
        "instructions": "Answer concisely; label any inference.",
    }


def run(question: str, *, model: str | None = None, refine: bool = True) -> dict:
    question = str(question or "").strip()
    if not question:
        raise ValueError("question is empty")
    if not config.FRONTIER_READY:
        return {
            "ok": False,
            "error": ("frontier tier is not configured. Set ATLAS_FRONTIER_BASE_URL, "
                      "ATLAS_FRONTIER_API_KEY and ATLAS_FRONTIER_MODEL in .env, "
                      "or use a provider preset with 'atlas models --provider NAME'."),
            "question": question,
        }
    brief = _brief(question, model) if refine else {
        "goal": question, "missing": "", "instructions": "Answer directly."
    }
    try:
        reply = llm.chat(
            [{"role": "system", "content": ANSWER_SYSTEM},
             {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
            None, tier="frontier", temperature=0.3, timeout=60, max_tokens=1200,
        )
        answer = (reply.content or "").strip()
        if not answer:
            raise RuntimeError("frontier model returned an empty answer")
        return {
            "ok": True,
            "question": question,
            "brief": brief,
            "answer": answer,
            "local_model": model or config.MODEL,
            "frontier_model": config.FRONTIER_MODEL,
            "frontier_endpoint": config.FRONTIER_BASE_URL,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "question": question, "brief": brief}
