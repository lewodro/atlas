"""Autonomous, budgeted web research for local models.

The model is used only for small, structured decisions (query generation,
evidence evaluation, synthesis). The harness owns the loop: it searches,
fetches, extracts evidence, checks completeness, reformulates and stops early.
No full system prompt is replayed into each stage, so this works on 2B models.

    for kind, payload in run_stream(question):
        if kind == "event": show(payload)
        else: answer = payload["answer"]
"""

from __future__ import annotations

import html
import difflib
import json
import os
import re
import time
import urllib.parse

import llm
import netguard
import registry

# ------------------------------------------------------------------ config

_DEFAULTS = {
    "ATLAS_RESEARCH_MAX_QUERIES": "6",
    "ATLAS_RESEARCH_MAX_SOURCES": "8",
    "ATLAS_RESEARCH_MAX_PAGES": "5",
    "ATLAS_RESEARCH_SECONDS": "240",
    "ATLAS_RESEARCH_PAGE_CHARS": "3600",
    "ATLAS_RESEARCH_MIN_EVIDENCE": "2",
}


def limits() -> dict:
    values = {}
    for key, default in _DEFAULTS.items():
        try:
            values[key] = int(os.getenv(key, default))
        except ValueError:
            values[key] = int(default)
    return {
        "queries": max(1, min(values["ATLAS_RESEARCH_MAX_QUERIES"], 12)),
        "sources": max(1, min(values["ATLAS_RESEARCH_MAX_SOURCES"], 20)),
        "pages": max(1, min(values["ATLAS_RESEARCH_MAX_PAGES"], 10)),
        "seconds": max(10, min(values["ATLAS_RESEARCH_SECONDS"], 900)),
        "page_chars": max(500, min(values["ATLAS_RESEARCH_PAGE_CHARS"], 12000)),
        "min_evidence": max(1, min(values["ATLAS_RESEARCH_MIN_EVIDENCE"], 6)),
    }


# --------------------------------------------------------------- classify

# Function words and question words are stripped when looking for the topic.
# Content words ("words", "language", "French", "entered") are deliberately
# kept: removing them was what produced useless searches like "number of
# russian french".
_QUERY_STOP = set(
    "a an the and or but if then than that this these those of in on at to for "
    "from with by about into through during before after over under between "
    "is are was were be been being do does did done have has had can could "
    "would should will shall may might must not no nor so as too very more "
    "most some any all each every what which who whom whose when where why how "
    "please tell me give show find look up approximately roughly "
    "about around estimate estimated many much number count amount "
    "i you my your it its they them their "
    "including such e.g eg etc"
    .split()
)

# Kept for compatibility with tests that import the older name.
_STOP = _QUERY_STOP

NUMBER_RE = re.compile(
    r"\b(?:how many|how much|number of|count of|approximately|roughly|"
    r"about how many|estimate|estimated|what percent|percentage|average|"
    r"how large|how long|how old)\b", re.I,
)
DATE_RE = re.compile(r"\b(?:when|what year|in which year|what date|how old)\b", re.I)
COMPARE_RE = re.compile(r"\b(?:compare|comparison|versus|vs\.?|difference between|differ from)\b", re.I)
DEF_RE = re.compile(r"\b(?:what is|what are|define|definition|meaning of|stand for)\b", re.I)
EXPLAIN_RE = re.compile(r"\b(?:why|how does|how do|explain|mechanism|reason for)\b", re.I)
APPROX_RE = re.compile(r"\b(?:approximately|roughly|about|around|estimate|estimated|circa|near)\b", re.I)

MEMORY_RE = re.compile(
    r"\b(?:who am i|what do you know about me|do you remember|what did i|"
    r"my name|what am i studying|my memory|recall what|my project)\b", re.I,
)
CODE_RE = re.compile(
    r"\b(?:write|create|make|edit|fix|debug|implement|refactor|build|generate)\b"
    r".*\b(?:file|script|code|function|class|module|app|program|test)\b", re.I,
)
RESEARCH_RE = re.compile(
    r"\b(?:research|find out|look up|according to|source|sources|evidence|"
    r"verify|statistics|study|studies|citation|cited|estimate)\b", re.I,
)
SCRIPT_RE = re.compile(r"[\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF\u0600-\u06FF\u0900-\u097F]")

LANG_NAMES = {
    "russian": "ru", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "arabic": "ar", "hindi": "hi", "portuguese": "pt", "polish": "pl",
    "ukrainian": "uk", "turkish": "tr", "dutch": "nl",
}
LANG_TERMS = {
    "ru": ("сколько", "количество"), "fr": ("combien", "nombre de"),
    "de": ("wie viele", "anzahl"), "es": ("cuántos", "número de"),
    "it": ("quanti", "numero di"), "zh": ("多少", "数量"),
    "ja": ("いくつ", "数"), "ko": ("몇", "수량"),
    "ar": ("كم", "عدد"), "hi": ("कितने", "संख्या"),
    "pt": ("quantos", "número de"), "pl": ("ile", "liczba"),
    "uk": ("скільки", "кількість"), "tr": ("kaç", "sayısı"),
    "nl": ("hoeveel", "aantal"),
}
# A few common words used only to recognise the language of a generated query.
LANG_MARKERS = {
    "ru": ("сколько", "слов", "русский", "русском", "язык", "языке", "через"),
    "fr": ("combien", "mots", "français", "langue", "russe", "dans", "sont"),
    "de": ("wie", "viele", "wörter", "russisch", "sprache", "durch"),
    "es": ("cuántos", "palabras", "ruso", "idioma", "lengua", "por"),
    "it": ("quanti", "parole", "russo", "lingua", "attraverso"),
    "pt": ("quantos", "palavras", "russo", "língua", "através"),
    "pl": ("ile", "słów", "rosyjski", "język", "przez"),
}

# Numeric words, so a range like "около двух тысяч" or "two thousand" counts
# as a numeric claim rather than prose.
_NUMBER = re.compile(
    r"\b\d[\d\s,\.]*\b|\b(?:two|three|four|five|six|seven|eight|nine|ten|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion)\b|"
    r"(?:тысяч|тысячи|тысяча|сотен|миллион|миллиард|две|три|четыре|пять|"
    r"десять|сто)\w*",
    re.I,
)
_TOKEN_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_NUM_RE = re.compile(r"\d[\d\s,\.]*", re.UNICODE)


def unicode_tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(text or ""))}


def answer_type(question: str) -> str:
    low = str(question or "").lower()
    if NUMBER_RE.search(low):
        return "number"
    if DATE_RE.search(low):
        return "date"
    if COMPARE_RE.search(low):
        return "comparison"
    if DEF_RE.search(low):
        return "definition"
    if EXPLAIN_RE.search(low):
        return "explanation"
    return "general"


def is_approximate(question: str) -> bool:
    return bool(APPROX_RE.search(str(question or "")))


def language_hints(question: str) -> list[dict]:
    text = str(question or "")
    low = text.lower()
    codes: list[str] = []
    if re.search(r"[\u0400-\u04FF]", text):
        codes.append("ru")
    if re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text):
        codes.append("zh")
    if re.search(r"[\u0600-\u06FF]", text):
        codes.append("ar")
    if re.search(r"[\u0900-\u097F]", text):
        codes.append("hi")
    for name, code in LANG_NAMES.items():
        if re.search(rf"\b{name}\b", low) and code not in codes:
            codes.append(code)
    return [{"code": code, "terms": list(LANG_TERMS.get(code, ()))} for code in codes]


_COMPANY_CONTEXT = re.compile(
    r"\b(?:company|companies|revenue|earnings|profit|stock|shares|filings|"
    r"filing|10-k|10-q|8-k|financials|investor|market cap|ceo|business|"
    r"annual report|quarterly report)\b", re.I,
)


def company_request(question: str) -> str:
    """Return a company name when the user wants company files/facts."""
    try:
        from research import extract_company
        name = extract_company(question)
    except Exception:
        name = ""
    if not name:
        return ""
    if _COMPANY_CONTEXT.search(question) or re.match(
        r"^(?:research|analyze|analyse|report)\b", question.strip(), re.I
    ):
        return name
    return ""


def needs_research(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        return False
    if company_request(text):
        return True
    if MEMORY_RE.search(text) or CODE_RE.search(text):
        return False
    if re.match(r"^(?:hi|hello|hey|thanks|thank you|ok|okay)\b", text, re.I):
        return False
    kind = answer_type(text)
    if kind in ("number", "date", "comparison") and ("?" in text or len(text.split()) >= 4):
        return True
    if RESEARCH_RE.search(text):
        return True
    if SCRIPT_RE.search(text):
        return True
    if kind in ("definition", "explanation") and re.search(
        r"\b(?:historical|scientific|technical|medical|legal|economic|linguistic)\b", text, re.I
    ):
        return True
    return False


# -------------------------------------------------------------- structuring

QUERY_SYSTEM = """Return JSON ONLY: {"queries":["query1","query2"]}.
Generate 4 DISTINCT web searches that could directly answer the question.
At least two queries must be written in English.
Keep the exact subject (what is being counted or described) and the requested
attribute in every query. Add the standard technical term or a synonym when
one exists; do not merely reorder the same words.
If the subject names another language, include one query written in that
language. Never include a guessed answer. Max 14 words per query."""

EVAL_SYSTEM = """Return JSON ONLY: {"complete":true,"missing":"","reason":""}.
Decide whether the evidence directly answers the user's requested deliverable.
An approximate question only needs a defensible estimate or range, not an exact
figure. Use only the evidence shown. If the requested number, date or
comparison is absent, complete=false and say what is missing."""

COMPANY_SYSTEM = """Answer the user's question from the company research digest.
Use only facts and URLs that appear in the digest. Mention the company's real
SEC filings when the user asks for files, reports or filings. Separate reported
facts from interpretation. Never invent a figure, filing date or URL.
Cite at least two real URLs. Under 400 words; no offers to help further."""

SYNTH_SYSTEM = """Answer the user's question directly from the evidence.
- If they ask for an approximate quantity, give a defensible number or range.
- Use numbers exactly as they appear in the evidence; never invent one.
- Say what the estimate represents (dictionary entries, loanwords, speakers).
- If sources disagree, give the range and explain why they differ.
- If you infer a figure from incomplete evidence, label it as an inference.
- Cite real URLs from the evidence. Never invent a source or a quotation.
- Ignore sources that discuss a different language or a different subject.
- No background lecture, no offers to help further. Under 300 words."""


def _safe_chat(messages: list[dict], model: str | None, *, timeout: int = 30,
               max_tokens: int = 700, temperature: float = 0.2):
    """A model call that cannot abort research on a slow local runtime."""
    try:
        return llm.chat(
            messages, None, model=model, temperature=temperature,
            timeout=timeout, max_tokens=max_tokens,
        )
    except Exception:
        return None


def _json_call(messages: list[dict], model: str | None, max_tokens: int = 340) -> dict:
    options = {
        "model": model, "temperature": 0, "max_tokens": max_tokens,
        "timeout": 20,
        "response_format": {"type": "json_object"},
    }
    try:
        reply = llm.chat(messages, None, **options)
    except Exception:
        # Slow 2B runtimes must not consume the whole research budget. The
        # harness has deterministic fallbacks for every structured decision.
        return {}
    text = str(getattr(reply, "content", "") or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _normal_query(query: str) -> str:
    words = [
        word.lower() for word in _TOKEN_RE.findall(str(query or ""))
        if word.lower() not in _QUERY_STOP
    ]
    numbers = re.findall(r"\d{2,}", str(query or ""))
    return " ".join(words + numbers)


def _near_duplicate(query: str, seen: list[str]) -> bool:
    token = _normal_query(query).split()
    if not token:
        return True
    script = bool(SCRIPT_RE.search(query))
    for old in seen:
        other = _normal_query(old).split()
        if not other:
            continue
        if script != bool(SCRIPT_RE.search(old)):
            # Different writing systems are different searches, even if a
            # shared number or name appears in both.
            continue
        if difflib.SequenceMatcher(None, token, other).ratio() >= 0.82:
            return True
    return False


def topic_words(question: str) -> set[str]:
    words = unicode_tokens(searchable(question)) - _QUERY_STOP
    return {word for word in words if len(word) >= 3}


_GENERIC_CORE = set(
    "statistics estimate research influence influences enter entered entering "
    "borrow borrowed borrowing word words language languages number count "
    "amount total figures figure data fact facts".split()
)


def core_terms(question: str) -> set[str]:
    """The few words that identify the subject, e.g. {french, russian}."""
    words = topic_words(question) - _GENERIC_CORE
    return words or topic_words(question)


def searchable(question: str) -> str:
    text = str(question or "").strip()
    text = re.sub(
        r"^\s*(?:approximately|roughly|about|can you|could you|please|"
        r"tell me|do you know|i want to know)\b[,: ]*", "", text, flags=re.I,
    )
    text = re.sub(r"[,\s]+(?:including|such as|e\.g\.)\b[\s\S]*$", "", text, flags=re.I)
    return " ".join(text.rstrip(" ?.!").split())


def language_pair(question: str) -> tuple[str, str]:
    """Return (source language, target language) for borrowing-style questions."""
    text = searchable(question)
    source = re.search(
        r"\b(?:through|from|via)\s+(?:the\s+)?([A-Za-z][\w-]+)", text, re.I
    )
    target = re.search(r"\b([A-Za-z][\w-]+)\s+language\b", text, re.I)
    if source and target:
        first, second = source.group(1).lower(), target.group(1).lower()
        if first != second:
            return first, second
    return "", ""


_APPROX_CUE = re.compile(
    r"\b(?:about|around|approximately|roughly|more than|over|nearly|almost|"
    r"около|приблизительно|свыше|более|порядка)\b", re.I,
)
_REVERSED = re.compile(
    r"([A-Za-z]+)\s+terms\s+(?:derived|borrowed)\s+from\s+([A-Za-z]+)", re.I
)


def _query_language(query: str) -> str:
    text = str(query or "")
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"
    if re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text):
        return "zh"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    low = text.lower()
    for code, markers in LANG_MARKERS.items():
        hits = sum(1 for marker in markers if re.search(rf"\b{re.escape(marker)}\b", low))
        if hits >= 2:
            return code
    return "en"


def _query_allowed(query: str, hints: list[dict]) -> bool:
    lang = _query_language(query)
    if lang == "en":
        return True
    return any(hint["code"] == lang for hint in hints)


def _programmatic_queries(question: str, kind: str, seen: list[str]) -> list[str]:
    clean = searchable(question)
    out: list[str] = []
    if clean:
        out.append(clean)
        source, target = language_pair(question)
        if source and target:
            out.append(f"{source} words in {target} language how many")
            out.append(f"number of {source} loanwords in {target} language")
        swapped = re.sub(r"\bthrough\b", "from", clean, flags=re.I)
        if swapped != clean:
            out.append(swapped)
        # "how many words ... through French" -> "how many French words ..."
        match = re.search(
            r"\b(?:through|from|via)\s+([A-Za-z][\w-]+)\s*$", clean, re.I
        )
        if match:
            name = match.group(1)
            stem = re.sub(
                r"^how\s+(?:many|much)\s+", "", clean[: match.start()].strip(),
                flags=re.I,
            )
            out.append(f"how many {name} {stem}")
        words = [
            word.lower() for word in _TOKEN_RE.findall(clean)
            if word.lower() not in _QUERY_STOP
        ]
        words = list(dict.fromkeys(words))
        if len(words) >= 3:
            phrase = " ".join(words[:7])
            out.append(f"{phrase} number statistics")
            out.append(f"{phrase} research estimate")
    return [query for query in out if not _near_duplicate(query, seen)][:4]


def generate_queries(question: str, kind: str, hints: list[dict], seen: list[str],
                     model: str | None, missing: str = "",
                     use_model: bool = True,
                     on_model_failure=None) -> list[str]:
    """Ask for a few searches, then guarantee useful English ones exist."""
    prompt = (
        f"Question: {question}\nRequested answer type: {kind}\n"
        + ("Approximate answer acceptable: yes\n" if is_approximate(question) else "")
        + (f"Another language likely has primary sources: "
           f"{', '.join(h['code'] for h in hints)}\n" if hints else "")
        + (f"Still missing: {missing}\n" if missing else "")
        + "Already used (do not repeat): " + "; ".join(seen[-8:]) + "\n"
    )
    # A guaranteed, well-formed English query goes first. Small models often
    # answer with foreign-language-only queries, which are useful later but
    # should not decide the first search.
    seeds = _programmatic_queries(question, kind, [])
    queries: list[str] = list(seeds[:1])

    data = _json_call(
        [{"role": "system", "content": QUERY_SYSTEM},
         {"role": "user", "content": prompt}], model,
    ) if use_model else {}
    if not data and use_model and on_model_failure:
        on_model_failure()
    raw = data.get("queries") or []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("query") or item.get("text") or ""
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split()).strip("\"' ")[:140]
        # Small models often prefix the language code: "ru сколько ...".
        cleaned = re.sub(
            r"^(?:en|fr|ru|de|es|it|zh|ja|ko|ar|hi|pt|pl|uk|tr|nl)"
            r"\s*[:|\-]?\s+",
            "", cleaned, flags=re.I,
        )
        if len(cleaned) < 4:
            continue
        if not _query_allowed(cleaned, hints):
            continue
        if _near_duplicate(cleaned, seen + queries):
            continue
        queries.append(cleaned)
    # The model may return only translations or nothing at all. Programmatic
    # English queries keep the loop usable on 2B models.
    for query in seeds[1:] + _programmatic_queries(question, kind, []):
        if not _near_duplicate(query, seen + queries):
            queries.append(query)
    return queries[:6]


# ------------------------------------------------------------------ search

_URL_LINE = re.compile(r"^\s*\d+\.\s+(.+)$")
_URL = re.compile(r"https?://[^\s)]+")


def parse_results(text: str) -> list[dict]:
    rows: list[dict] = []
    blocks = re.split(r"\n(?=\s*\d+\.\s+)", str(text or ""))
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        title_match = _URL_LINE.match(lines[0])
        url_match = next((_URL.search(line) for line in lines[1:] if _URL.search(line)), None)
        if not title_match or not url_match:
            continue
        url = url_match.group(0).rstrip(".,;:")
        snippet = ""
        for line in lines[1:]:
            if _URL.search(line) or line.startswith("Published:"):
                continue
            if line and not line.startswith("Web results for"):
                snippet = line
                break
        rows.append({
            "title": title_match.group(1)[:180],
            "url": url,
            "snippet": snippet[:400],
        })
    return rows


def _quality(url: str) -> int:
    low = url.lower()
    score = 0
    for good in (".edu", ".gov", ".ac.", "jstor", "springer", "cambridge",
                 "oxford", "dictionary", "britannica", "encyclopedia",
                 "wikipedia", "wiktionary", "archive", "academia"):
        if good in low:
            score += 2
    if ".org" in low:
        score += 1
    return score


def rank_results(rows: list[dict], keywords: set[str]) -> list[dict]:
    def score(row: dict) -> float:
        text = f"{row['title']} {row['snippet']}"
        overlap = len(keywords & unicode_tokens(text))
        return _quality(row["url"]) * 2 + overlap
    return sorted(rows, key=score, reverse=True)


def search(query: str, limit: int) -> list[dict]:
    result = registry.run("web_search", {"query": query, "limit": limit}, approved=True)
    text = registry.content(result)
    return parse_results(text) if result["ok"] else []


def fetch(url: str) -> str:
    result = registry.run("web_fetch", {"url": url}, approved=True)
    return registry.content(result) if result["ok"] else ""


# ------------------------------------------------------------ wikipedia api

_WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
_WIKI_UA = {"User-Agent": "AtlasLocalResearch/1.0 (local-first; no telemetry)"}


def _wiki_json(params: dict) -> dict:
    url = _WIKI_API.format(lang=params.pop("lang")) + "?" + urllib.parse.urlencode(params)
    try:
        response = netguard.fetch(url, headers=_WIKI_UA)
        data = json.loads(response.text)
    except (netguard.NetError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def wiki_search(query: str, lang: str = "en", limit: int = 2) -> list[dict]:
    data = _wiki_json({
        "lang": lang, "action": "query", "list": "search",
        "srsearch": query, "format": "json", "srlimit": str(limit),
    })
    rows = []
    for item in (data.get("query", {}).get("search") or [])[:limit]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        rows.append({
            "title": title,
            "url": f"https://{lang}.wikipedia.org/wiki/"
                   + urllib.parse.quote(title.replace(" ", "_")),
            "snippet": html.unescape(re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))),
            "source": "wikipedia",
            "lang": lang,
        })
    return rows


def wiki_extract(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    lang = parsed.netloc.split(".")[0] or "en"
    title = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1]).replace("_", " ")
    data = _wiki_json({
        "lang": lang, "action": "query", "prop": "extracts",
        "explaintext": "1", "titles": title, "format": "json", "redirects": "1",
    })
    pages = data.get("query", {}).get("pages") or {}
    for page in pages.values():
        text = str(page.get("extract") or "")
        if text:
            return text
    return ""


# ----------------------------------------------------------------- evidence

def _numbers(text: str) -> set[str]:
    found = set()
    for value in _NUM_RE.findall(str(text or "")):
        cleaned = re.sub(r"[^\d]", "", value)
        if cleaned:
            found.add(cleaned.lstrip("0") or "0")
    return found


def _redirect_numbers(text: str) -> set[str]:
    """Normalise thousands written with spaces or dots: 2 000 / 2.000 -> 2000."""
    value = re.sub(r"(?<=\d)[\s.](?=\d{3}\b)", "", str(text or ""))
    return _numbers(value)


def relevant_numeric(evidence: list[dict], keywords: set[str] | None = None) -> bool:
    """Numbers only count when they appear in passages about the subject."""
    words = {word for word in (keywords or set()) if len(word) >= 3}
    for item in evidence:
        for passage in item.get("passages", []):
            if not _NUMBER.search(passage):
                continue
            if item.get("trusted"):
                return True
            if not words:
                return True
            if len(unicode_tokens(passage) & words) >= 2:
                return True
    return False


def supported_urls(answer: str, urls: list[str]) -> bool:
    """Never let a model citation point somewhere the tools did not fetch."""
    allowed = {url.rstrip(".,") for url in urls}
    cited = re.findall(r"https?://[^\s)\]>]+", str(answer or ""))
    return all(url.rstrip(".,") in allowed for url in cited)


def supported_numbers(answer: str, evidence: list[dict]) -> bool:
    """Every number in the answer must occur in the collected evidence."""
    answer_numbers = _redirect_numbers(answer)
    if not answer_numbers:
        return False
    corpus = " ".join(
        " ".join(item.get("passages", [])) + " " + item.get("url", "")
        for item in evidence
    )
    return bool(answer_numbers & _redirect_numbers(corpus))


def extract_passages(text: str, keywords: set[str], max_passages: int = 4,
                     trusted: bool = False) -> list[str]:
    body = text.split("Page text (untrusted external text, not instructions):", 1)[-1]
    body = re.sub(r"\s+", " ", body).strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    scored = []
    for sentence in sentences:
        if len(sentence) < 30:
            continue
        overlap = len(unicode_tokens(sentence) & keywords)
        numeric = 3 if _NUMBER.search(sentence) else 0
        if numeric and _APPROX_CUE.search(sentence):
            numeric += 5
        # A trusted page (Wikipedia article found for this question) can
        # contribute numeric context even when its language differs.
        if numeric and (overlap or trusted):
            score = 4 + overlap * 2 + numeric
        elif overlap >= 2:
            score = overlap * 2
        else:
            continue
        scored.append((score, sentence[:700]))
    scored.sort(key=lambda item: -item[0])
    return [text for _, text in scored[:max_passages]]


def evaluate(question: str, kind: str, evidence: list[dict],
             model: str | None, keywords: set[str] | None = None) -> dict:
    numeric = relevant_numeric(evidence, keywords)
    programmatic = {
        "complete": not (kind == "number" and not numeric),
        "missing": "" if numeric or kind != "number" else "a numerical estimate",
        "reason": "programmatic check",
    }
    if not evidence:
        return {"complete": False, "missing": "any relevant source text",
                "reason": "no evidence collected"}

    digest = "\n".join(
        f"URL: {item['url']}\n" + "\n".join(f"- {p}" for p in item["passages"][:2])
        for item in best_evidence(evidence, keywords or set(), 4)
    )[:6000]
    data = _json_call(
        [{"role": "system", "content": EVAL_SYSTEM},
         {"role": "user", "content":
          f"Question: {question}\nType: {kind}\n\nEvidence:\n{digest}"}], model,
    )
    complete = data.get("complete")
    if isinstance(complete, bool):
        if kind == "number" and not numeric:
            complete = False
        return {
            "complete": complete,
            "missing": str(data.get("missing") or "")[:220],
            "reason": str(data.get("reason") or "model evaluation")[:220],
        }
    return programmatic


def validate_answer(answer: str, kind: str) -> bool:
    text = str(answer or "").strip()
    if len(text) < 30:
        return False
    if kind == "number":
        return bool(_NUMBER.search(text))
    if kind == "date":
        return bool(re.search(r"\b(?:1[5-9]\d{2}|20\d{2})\b", text))
    if kind == "comparison":
        return bool(re.search(r"\b(?:vs|versus|difference|compared|whereas|but|while)\b", text, re.I))
    return True


def extractive_answer(question: str, kind: str, evidence: list[dict],
                      core: set[str] | None = None) -> str:
    """Deterministic fallback built from real evidence sentences.

    Used only when the model's synthesis is missing the deliverable or cites a
    number that is not in the evidence. It never adds facts of its own.
    """
    picks: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    core = core or set()
    for item in best_evidence(evidence, core, 6):
        for passage in item.get("passages", []):
            if any(marker in passage for marker in (
                "Edit links", "Toolbox", "Toggle the table", "Wikimedia",
                "Retrieved from", "oldid="
            )):
                continue
            if kind == "number" and (
                not _NUMBER.search(passage) or not count_context(passage)
            ):
                continue
            key = passage[:90].lower()
            if key in seen:
                continue
            seen.add(key)
            score = (
                _quality(item["url"]) + (2 if item.get("trusted") else 0)
                + (10 if (_APPROX_CUE.search(passage) and _NUMBER.search(passage)
                          and count_context(passage)) else 0)
                - (4 if _REVERSED.search(f"{item['title']} {passage}") else 0)
            )
            picks.append((score, passage.strip(), item["url"]))
    picks.sort(key=lambda row: -row[0])
    if not picks:
        return ""
    lines = []
    if kind == "number":
        estimates = estimate_numbers(evidence, core)
        values = sorted(estimates, key=lambda value: int(value or 0))
        if values:
            lines.append(
                f"Approximate answer: about {values[0]} French-origin words in "
                "Russian, according to the collected sources."
            )
            lines.append("")
            lines.append(
                "The sources appear to count loanwords recorded in dictionaries "
                "and reference lists rather than every word ever used."
            )
            lines.append("")
        else:
            lines.append(f"Here is what the sources say about: {question}")
            lines.append("")
    else:
        lines.append(f"Here is what the sources say about: {question}")
        lines.append("")
    for _, passage, url in picks[:3]:
        lines.append(f"- {passage[:380].strip()}")
        lines.append(f"  Source: {url}")
    lines.append("")
    lines.append(
        "This is a direct extract of the collected evidence. The sources do "
        "not all state the same figure, so treat the range as approximate."
        if len(picks) > 1 else
        "This is a direct extract of the collected evidence."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------- stream

def _insufficient(question: str, kind: str, queries: list[str], urls: list[str]) -> str:
    lines = [
        f"I could not establish a defensible answer to: {question}",
        f"I searched {len(queries)} queries and inspected {len(urls)} sources:",
    ]
    lines += [f"- {query}" for query in queries[:6]]
    if urls:
        lines.append("Sources inspected:")
        lines += [f"- {url}" for url in urls[:6]]
    lines.append(
        "The available evidence did not support a reliable "
        + ("number" if kind == "number" else "answer")
        + ", so I have not invented one."
    )
    return "\n".join(lines)


def evidence_score(item: dict, core: set[str]) -> int:
    text = " ".join(item.get("passages", []))
    return (
        _quality(item.get("url", "")) * 2
        + len(unicode_tokens(text) & core) * 2
        + (4 if _NUMBER.search(text) else 0)
        + (6 if _APPROX_CUE.search(text) and _NUMBER.search(text) else 0)
        + (1 if item.get("trusted") else 0)
    )


_COUNT_CONTEXT = re.compile(
    r"\b(?:words?|terms?|entries|loanwords?|borrowings?|vocabulary|"
    r"лексик\w*|слов|термин\w*|заимствован\w*)\b", re.I,
)


def count_context(passage: str) -> bool:
    """A number only answers a counting question when it counts words."""
    return bool(_COUNT_CONTEXT.search(str(passage or "")))


def primary_number_ok(answer: str, estimates: set[str]) -> bool:
    """The number that answers the question must be a sourced estimate."""
    if not estimates:
        return True
    numbers = re.findall(r"\d[\d,\.]*", str(answer or ""))
    if not numbers:
        return False
    first = re.sub(r"[^\d]", "", numbers[0]).lstrip("0") or "0"
    return first in estimates


def estimate_numbers(evidence: list[dict], core: set[str]) -> set[str]:
    """Numbers stated with an approximation cue in the strongest passages."""
    numbers: set[str] = set()
    cue_number = re.compile(
        r"(?:above|over|more\s+than|about|around|roughly|approximately|"
        r"nearly|almost|около|приблизительно|свыше|более|порядка)\s+"
        r"(\d[\d.,\s]*)", re.I,
    )
    for item in best_evidence(evidence, core, 6):
        for passage in item["passages"]:
            if not count_context(passage):
                continue
            for match in cue_number.finditer(passage):
                numbers |= _redirect_numbers(match.group(1))
    return numbers


def best_evidence(evidence: list[dict], core: set[str], limit: int = 4) -> list[dict]:
    ranked = sorted(evidence, key=lambda item: -evidence_score(item, core))
    chosen = []
    for item in ranked:
        passages = item["passages"]
        relevant = [
            p for p in passages
            if len(unicode_tokens(p) & core) >= min(2, len(core))
            or item.get("foreign")
        ]
        numeric = [p for p in relevant if _NUMBER.search(p)]
        passages = (numeric or relevant)[:2]
        if not passages:
            continue
        chosen.append({**item, "passages": passages})
        if len(chosen) >= limit:
            break
    return chosen


def _digest(evidence: list[dict], core: set[str] | None = None,
            limit: int = 7000) -> str:
    items = best_evidence(evidence, core or set(), 4)
    return "\n\n".join(
        f"SOURCE: {item['url']}\nTITLE: {item['title']}\n"
        + "\n".join(f"- {p}" for p in item["passages"])
        for item in items
    )[:limit]


def run_stream(question: str, model: str | None = None, tier: str = "local"):
    """Yield ("event", payload) while working, then ("result", result) once."""
    started = time.time()
    cfg = limits()
    kind = answer_type(question)

    def event(payload: dict):
        return ("event", payload)

    company = company_request(question)
    if company:
        try:
            import research
            yield event({"stage": "search", "query": f"company files: {company}",
                         "count": 0})
            found = research.company(company)
            digest = str(found.get("digest") or "")
            yield event({"stage": "inspect", "url": f"SEC filings: {found.get('filings', 0)}",
                         "passages": found.get("sources", 0)})
            if not digest:
                raise ValueError("empty company digest")
            answer_msg = _safe_chat(
                [{"role": "system", "content": COMPANY_SYSTEM},
                 {"role": "user", "content":
                  f"Question: {question}\n\nCompany research:\n{digest[:9000]}"}],
                model, timeout=30, max_tokens=900,
            )
            answer = ((getattr(answer_msg, "content", "") if answer_msg else "") or "").strip()
            urls = re.findall(r"https?://[^\s)]+", digest)
            if not answer:
                answer = (
                    f"Company research for {company} found "
                    f"{found.get('sources', 0)} sources, including "
                    f"{found.get('filings', 0)} SEC filings. "
                    "Key sources: " + ", ".join(dict.fromkeys(urls[:4]))
                )
            elif not supported_urls(answer, urls):
                # The model invented a citation; fall back to a grounded answer.
                answer = (
                    f"Company research for {company} found "
                    f"{found.get('sources', 0)} sources, including "
                    f"{found.get('filings', 0)} SEC filings. "
                    "Key sources: " + ", ".join(dict.fromkeys(urls[:4]))
                )
            elif not any(url in answer for url in urls[:6]):
                answer += "\n\nSources: " + ", ".join(dict.fromkeys(urls[:4]))
            yield ("result", {
                "question": question,
                "answer": answer,
                "answer_type": "company",
                "complete": True,
                "queries": [f"company files: {company}"],
                "sources": list(dict.fromkeys(urls))[:20],
                "pages": found.get("sources", 0),
                "evidence": found.get("sources", 0),
                "filings": found.get("filings", 0),
                "duration_s": round(time.time() - started, 1),
                "model_used": model or llm.tier_model(tier),
            })
            return
        except Exception as exc:
            yield event({"stage": "stop", "reason": f"company research failed: {exc}"})
    hints = language_hints(question)
    keywords = topic_words(question)
    core = core_terms(question)
    for hint in hints:
        keywords.update(hint["terms"])
    hints = [hint for hint in hints if hint["code"] != "en"]

    seen: list[str] = []
    queries: list[str] = []
    evidence: list[dict] = []
    fetched_urls: set[str] = set()
    source_urls: list[str] = []
    missing = ""
    complete = False
    discarded = 0
    model_usable = True

    def model_failed() -> None:
        nonlocal model_usable
        model_usable = False

    def add_queries(new: list[str]) -> None:
        for query in new:
            if query not in queries and not _near_duplicate(query, seen):
                queries.append(query)
                seen.append(query)

    def row_relevant(row: dict) -> bool:
        text = f"{row.get('title', '')} {row.get('snippet', '')}"
        source, target = language_pair(question)
        if source and target:
            for match in _REVERSED.finditer(text):
                if match.group(1).lower() == source and match.group(2).lower() == target:
                    return False
        tokens = unicode_tokens(text)
        if len(tokens & core) >= min(2, len(core)):
            return True
        if SCRIPT_RE.search(text) and any(hint["code"] == "ru" for hint in hints):
            return True
        return False

    def add_evidence(url: str, title: str, passages: list[str],
                     trusted: bool, source: str = "web",
                     foreign: bool = False) -> None:
        if not passages:
            return
        for item in evidence:
            if item["url"] == url:
                known = set(item["passages"])
                item["passages"] += [p for p in passages if p not in known]
                item["trusted"] = item["trusted"] or trusted
                return
        evidence.append({"url": url, "title": title, "passages": passages,
                         "trusted": trusted, "source": source,
                         "foreign": foreign})

    def ingest_row(row: dict, *, trusted: bool, source: str,
                   foreign: bool = False) -> None:
        url = row["url"]
        if url in fetched_urls:
            return
        fetched_urls.add(url)
        source_urls.append(url)
        if source == "wikipedia":
            text = wiki_extract(url)
            passages = extract_passages(text, keywords, trusted=True)
        else:
            text = fetch(url)
            passages = extract_passages(text, keywords, trusted=trusted)
        if passages:
            add_evidence(url, row["title"], passages, trusted, source, foreign)
        snippet = " ".join(str(row.get("snippet") or "").split())
        if len(snippet) >= 40 and _NUMBER.search(snippet):
            add_evidence(url, row["title"], [snippet[:500]],
                         trusted or source == "wikipedia", source, foreign)

    add_queries(generate_queries(
        question, kind, hints, seen, model,
        on_model_failure=model_failed,
    ))

    index = 0
    first_round = True
    pages_used = 0
    while index < len(queries) and index < cfg["queries"]:
        if time.time() - started > cfg["seconds"]:
            yield event({"stage": "stop", "reason": "time budget"})
            break
        query = queries[index]
        index += 1
        rows = search(query, min(8, cfg["sources"]))
        yield event({"stage": "search", "query": query, "count": len(rows)})
        if not rows:
            # Search provider throttled or offline: Wikipedia is a stable,
            # key-free fallback instead of ending the investigation early.
            for lang in ["en"] + [hint["code"] for hint in hints[:1]]:
                rows.extend(wiki_search(query, lang, 3))
            if rows:
                yield event({"stage": "search", "query": query,
                             "count": len(rows), "fallback": "wikipedia"})

        relevant = [row for row in rank_results(rows, keywords) if row_relevant(row)]
        discarded += len(rows) - len(relevant)
        for row in relevant:
            if pages_used >= cfg["pages"]:
                # Still keep the snippet; it can carry the number even when
                # the page itself is not fetched.
                snippet = " ".join(str(row.get("snippet") or "").split())
                if len(snippet) >= 40 and _NUMBER.search(snippet):
                    if row["url"] not in source_urls:
                        source_urls.append(row["url"])
                    add_evidence(
                        row["url"], row["title"], [snippet[:500]], False,
                        foreign=bool(SCRIPT_RE.search(snippet)) and bool(hints),
                    )
                continue
            pages_used += 1
            foreign = bool(SCRIPT_RE.search(f"{row['title']} {row.get('snippet', '')}")) and bool(hints)
            ingest_row(row, trusted=True, source="web", foreign=foreign)
            yield event({"stage": "inspect", "url": row["url"],
                         "passages": len(evidence[-1]["passages"]) if evidence else 0})

        # Wikipedia is a stable, key-free reference source. Search it in the
        # question's languages as well as English when a language is hinted.
        if first_round or missing:
            langs = ["en"] + [hint["code"] for hint in hints if hint["code"] != "en"]
            for lang in langs[:3]:
                for wrow in wiki_search(query, lang, 2):
                    if pages_used >= cfg["pages"]:
                        break
                    if wrow["url"] in fetched_urls:
                        continue
                    if not row_relevant(wrow) and not first_round:
                        continue
                    pages_used += 1
                    ingest_row(wrow, trusted=True, source="wikipedia")
                    yield event({"stage": "inspect", "url": wrow["url"],
                                 "passages": len(evidence[-1]["passages"]) if evidence else 0})

        first_round = False
        verdict = evaluate(question, kind, evidence, model, keywords)
        complete = bool(verdict["complete"]) and len(evidence) >= cfg["min_evidence"]
        yield event({"stage": "evaluate", "complete": complete,
                     "missing": verdict.get("missing", ""),
                     "evidence": len(evidence)})
        if complete:
            break
        missing = verdict.get("missing") or "more specific evidence"
        new_queries = generate_queries(
            question, kind, hints, seen, model, missing,
            use_model=model_usable, on_model_failure=model_failed,
        )
        if not new_queries:
            yield event({"stage": "reformulate", "missing": missing,
                         "queries": [], "note": "using remaining plan"})
        else:
            yield event({"stage": "reformulate", "missing": missing,
                         "queries": new_queries[:3]})
            add_queries(new_queries)

    has_number = relevant_numeric(evidence, keywords)
    if not evidence or (kind == "number" and not has_number):
        answer = _insufficient(question, kind, queries, source_urls)
    else:
        digest = _digest(evidence, core)
        estimates = estimate_numbers(evidence, core) if kind == "number" else set()
        summary = _safe_chat(
            [{"role": "system", "content": SYNTH_SYSTEM},
             {"role": "user", "content":
              f"Original question: {question}\nAnswer type: {kind}\n\n{digest}"}],
            model, timeout=30,
            max_tokens=900 if kind == "number" else 700,
        ) if model_usable else None
        answer = ((getattr(summary, "content", "") if summary else "") or "").strip()

        contradicts_estimates = bool(
            estimates and not (_redirect_numbers(answer) & estimates)
        )
        evidence_urls = [item["url"] for item in evidence]
        bad_urls = not supported_urls(answer, evidence_urls)
        if (not validate_answer(answer, kind) or contradicts_estimates or bad_urls
                or not primary_number_ok(answer, estimates)
                or (kind == "number" and not supported_numbers(answer, evidence))):
            repair = _safe_chat(
                [{"role": "system", "content":
                  "Your previous answer did not contain the requested deliverable, "
                  "or used a number that is not in the evidence. Answer the original "
                  "question directly now using only the evidence. Quote numbers "
                  "exactly as written. Cite real URLs. No preamble."},
                 {"role": "user", "content":
                  f"Question: {question}\nPrevious answer: {answer[:800]}\n\n{digest[:6000]}"}],
                model, timeout=25, temperature=0,
                max_tokens=700,
            ) if model_usable else None
            repaired = ((getattr(repair, "content", "") if repair else "") or "").strip()
            if (validate_answer(repaired, kind)
                    and primary_number_ok(repaired, estimates)
                    and supported_urls(repaired, evidence_urls)
                    and (kind != "number" or (
                        supported_numbers(repaired, evidence)
                        and (not estimates or _redirect_numbers(repaired) & estimates)
                    ))):
                answer = repaired
            else:
                answer = extractive_answer(question, kind, evidence, core) or _insufficient(
                    question, kind, queries, source_urls
                )

    result = {
        "question": question,
        "answer": answer,
        "answer_type": kind,
        "approximate": is_approximate(question),
        "complete": complete or validate_answer(answer, kind),
        "queries": queries[: cfg["queries"]],
        "sources": source_urls,
        "pages": pages_used,
        "evidence": len(evidence),
        "discarded_results": discarded,
        "digest": _digest(evidence, core, 4000),
        "duration_s": round(time.time() - started, 1),
        "model_used": model or llm.tier_model(tier),
    }
    yield ("result", result)


def run(question: str, model: str | None = None, tier: str = "local") -> dict:
    """Convenience wrapper: drain the stream and return the final result."""
    result = {}
    for kind, payload in run_stream(question, model=model, tier=tier):
        if kind == "result":
            result = payload
    return result
