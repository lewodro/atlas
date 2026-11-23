"""A tiny freshness policy shared by the CLI and Web agent loops.

The skill *guides* the model; this module *enforces* the one rule that matters:
a time-sensitive question must be answered from web evidence, not memory.

No model call, no network, no configuration — just a compact classifier and a
small state tracker so both harnesses behave identically and stop after a
bounded number of corrections.
"""

from __future__ import annotations

import datetime
import json
import re

WEB_TOOLS = ("web_search", "web_fetch")
MAX_CORRECTIONS = 2
CORRECTION = "Fresh information requested. Use web_search before answering."
_FAILURE = "I couldn't verify current {period} information from the web."

_MONTHS = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december"
)
_PATTERNS = [
    r"\b(?:latest|newest|up[- ]to[- ]date|recent|recently|currently|current|"
    r"today|tonight|yesterday|nowadays)\b",
    r"\bthis\s+(?:week|month|year|quarter|morning|afternoon|evening|season|" + _MONTHS + r")\b",
    r"\bnew\b(?!\s+(?:to|york|zealand|jersey|mexico|hampshire|delhi|orleans)\b)",
    rf"\b(?:{_MONTHS})\s+(?:20\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)?)\b",
    rf"\b20\d{{2}}\s+(?:{_MONTHS})\b",
    r"\bq[1-4]\s*20\d{2}\b",
    r"\bas of\b",
]
_DATE = re.compile(
    rf"\b((?:{_MONTHS})\s+20\d{{2}}|20\d{{2}}\s+(?:{_MONTHS}))\b", re.IGNORECASE
)
_STOP = {
    "what", "are", "is", "the", "a", "an", "in", "on", "at", "for", "from",
    "about", "tell", "me", "be", "more", "specific", "use", "using", "news",
    "please", "research", "find", "show", "give", "with", "and", "latest",
    "newest", "recent", "current", "currently", "today", "this", "week",
    "month", "year", "version", "versions", "list", "of", "to", "do", "does",
}


def required(text: str) -> bool:
    """True when the request asks for information that could have changed."""
    low = str(text or "").lower()
    return any(re.search(pattern, low) for pattern in _PATTERNS)


def period(text: str) -> str:
    """A short human label for the requested timeframe (for honest failures)."""
    match = _DATE.search(str(text or ""))
    if match:
        parts = match.group(1).split()
        if parts[0].isdigit():
            parts.reverse()
        return f"{parts[0].capitalize()} {parts[1]}"
    low = str(text or "").lower()
    for phrase in ("this week", "this month", "this year", "today", "yesterday"):
        if phrase in low:
            return phrase
    return ""


def is_web_tool(name: str) -> bool:
    return str(name or "") in WEB_TOOLS


def web_available() -> bool:
    """Is web_search actually usable right now? No import cycle at module load."""
    import registry

    spec = registry.get("web_search")
    return bool(
        spec and registry.is_available(spec)
        and registry.permission("web_search") != "DENY"
    )


def failure(period_label: str = "") -> str:
    label = period_label or "time-sensitive"
    return _FAILURE.format(period=label)


_URL = re.compile(r"https?://[^\s<>\"'\)\]]+")


def grounding_note() -> str:
    """Runtime date + evidence-only reminder after an automatic tool call."""
    return (
        f"Today is {datetime.date.today().isoformat()} (system clock). "
        "Use only the web results above for current claims. Do not answer from "
        "memory, invent items, or claim the requested date is in the future. "
        "Name the source URL for each item; omit any detail the sources do not "
        "support. If the evidence does not cover the timeframe, say so plainly."
    )


def first_url(text: str) -> str:
    """Pick the first concrete URL out of a search-result tool message."""
    match = _URL.search(str(text or ""))
    return match.group(0).rstrip(".,;:") if match else ""


def auto_tool_messages(name: str, args: dict, call_id: str) -> tuple[list[dict], dict]:
    """Run a web tool on the model's behalf when it will not emit a call.

    Small local models often narrate a search instead of calling it. The
    harness owns this critical behavior; the result still enters model context
    through a normal tool message, so synthesis is grounded in real evidence.
    """
    import registry

    result = registry.run(name, args, approved=True)
    text = registry.content(result)
    ok = bool(result.get("ok")) and not text.lower().startswith("no usable results")
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }]},
        {"role": "tool", "tool_call_id": call_id, "content": text},
    ]
    return messages, {"ok": ok, "text": text}


def says_will_search(text: str) -> bool:
    """The model narrated an intent to search but emitted no call."""
    return bool(re.search(
        r"\b(?:i\s+(?:should|need\s+to|will|must|have\s+to)\s+"
        r"(?:search|look\s+up|check|fetch|browse|research))",
        str(text or "").lower(),
    ))


def suggest_queries(text: str, limit: int = 3) -> list[str]:
    """Turn a user request into a few specific searches, not one vague query."""
    label = period(text)
    raw = re.sub("|".join(_PATTERNS), " ", str(text or "").lower())
    raw = re.sub(r"[^a-z0-9\s,]+", " ", raw)
    clauses = re.split(r"\s+(?:and|also|plus|,)\s+", raw)
    queries: list[str] = []
    for clause in clauses:
        words = [
            word for word in clause.split()
            if word not in _STOP and len(word) >= 2  # keep "AI"
        ][:4]
        if not words:
            continue
        query = " ".join(words)
        if label and label.lower() not in query:
            query += " " + label
        if query not in queries:
            queries.append(query)
        if len(queries) >= limit:
            break
    return queries or ([f"{label} news"] if label else [])


def directive(text: str) -> str:
    """Compact system-prompt rule, injected only for freshness-required turns."""
    label = period(text)
    queries = suggest_queries(text)
    lines = [
        "FRESHNESS RULE (harness-enforced): current information is required. "
        "You MUST call web_search before answering, then web_fetch a useful source.",
    ]
    if queries:
        lines.append("Specific searches: " + "; ".join(f'"{q}"' for q in queries) + ".")
    lines.append(
        "Never answer a current claim from memory alone. If web search fails, "
        f'say exactly: "{failure(label)}"'
    )
    return "\n".join(lines)


class Tracker:
    """Per-turn state: did we actually research, and how many retries are left?"""

    def __init__(self, required_: bool, period_label: str = ""):
        self.required = required_
        self.period = period_label
        self.searches = 0
        self.fetches = 0
        self.search_ok = False
        self.last_search = ""
        self.corrections = 0
        self.auto_searches = 0
        self.auto_fetches = 0
        self._fetch_nudged = False

    def note_call(self, name: str) -> None:
        if name == "web_search":
            self.searches += 1
        elif name == "web_fetch":
            self.fetches += 1

    def note_result(self, name: str, ok: bool, text: str = "") -> None:
        if name != "web_search":
            return
        self.last_search = str(text or "")
        if not ok:
            return
        low = self.last_search.lower()
        if low.startswith("no usable results") or "tool error" in low:
            return
        self.search_ok = True

    def blocked(self) -> bool:
        """A final answer is not allowed until a search succeeded."""
        return self.required and not self.search_ok

    def correct(self) -> str | None:
        """A bounded internal correction, or None when retries are exhausted."""
        if not self.blocked() or self.corrections >= MAX_CORRECTIONS:
            return None
        self.corrections += 1
        return CORRECTION

    def can_auto_search(self) -> bool:
        return self.required and not self.search_ok and self.auto_searches < 2

    def can_auto_fetch(self) -> bool:
        return self.required and self.search_ok and not self.fetches and self.auto_fetches < 1

    def fetch_nudge(self) -> str | None:
        """One gentle nudge to open a source after a successful search."""
        if not self.required or not self.search_ok or self.fetches:
            return None
        if self._fetch_nudged:
            return None
        self._fetch_nudged = True
        return (
            "Call web_fetch on the most useful result URL now, before answering. "
            "If the sources are stale, search again with a more specific query."
        )

    def summary(self) -> dict:
        return {
            "searches": self.searches,
            "fetches": self.fetches,
            "search_ok": self.search_ok,
            "corrections": self.corrections,
        }
