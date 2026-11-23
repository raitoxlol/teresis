"""Deterministic fact extraction from conversation text (no LLM).

Precision over recall: only durable preferences and explicit decisions are
captured. Momentary requests ("I want tuna"), system prompts, tool output,
compaction summaries and Teresis's own injected memory block are not facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
# Compound sentences: split on ";" and on ", and/but/also" so each clause is one fact.
_CLAUSE = re.compile(r";\s+|,?\s+(?:and|but|also)\s+(?=(?:I|we|my|our|never|always|don't|do not|the|this)\b)", re.I)
_LEAD = re.compile(r"^(?:for future reference|update|correction|note that|remember(?: this(?: for later)?| that)?|fyi|heads up|just so you know)\s*[:,\-]?\s*", re.I)
_SPEAKER = re.compile(r"^(?:user|human)\s*:\s*", re.I)
_QUOTES = "\"'“”‘’"

# Preferences must be stated as habits, not one-off wants. Importance stays
# above MIN_PREFERENCE_IMPORTANCE so a weak match cannot become a preference.
MIN_PREFERENCE_IMPORTANCE = 0.7

_RULES: list[tuple[str, float, list[re.Pattern]]] = [
    ("preference", 0.8, [
        re.compile(r"\bI\s+(?:really\s+)?prefer\b", re.I),
        re.compile(r"\bI\s+(?:always|never)\s+(?:prefer|use|like|want|need|eat|order)\b", re.I),
        re.compile(r"\bmy\s+(?:favou?rite|preferred|default|usual)\s+\w+(?:\s+\w+)?\s+is\b", re.I),
        re.compile(r"\bI(?:'m| am)\s+(?:based|located|living)\s+in\b", re.I),
    ]),
    ("procedure", 0.7, [
        re.compile(r"\b(?:always|never|don't ever|do not ever)\s+\w+", re.I),
        re.compile(r"\bfrom now on\b", re.I),
        re.compile(r"\bmake sure (?:to|you)\b", re.I),
        # build / test / ops runbook statements
        re.compile(r"\brun\s+`?[\w./-]+`?(?:\s+`?[\w./-]+`?){0,3}\s+to\s+"
                   r"(?:test|build|lint|verify|deploy|check|format)\b", re.I),
        re.compile(r"\bdeploy(?:s|ed|ing)?\s+(?:[\w-]+\s+)?(?:with|via|using|through)\b", re.I),
        re.compile(r"\btests?\s+(?:are\s+)?(?:live|lives|kept|found|located|reside)\b", re.I),
        re.compile(r"\btests?\s+(?:are|is)\s+(?:in|inside|under)\s+(?:the\s+)?"
                   r"[\w./~-]*(?:test|spec|e2e|unit|integration)[\w./~-]*", re.I),
    ]),
    ("fact", 0.6, [
        re.compile(r"\b(?:my|our)\s+(?:[\w-]+\s+){1,3}(?:is|are)\s+(?:called|named|at|on|hosted|located)\b", re.I),
        re.compile(r"\b(?:my|our)\s+(?:[\w-]+\s+){0,3}(?:port|host|url|endpoint|database|db|repo|branch)\s+(?:is|are)\b", re.I),
    ]),
    ("decision", 0.75, [
        # migration / replacement statements: "switched from X to Y", "use X instead of Y" ...
        re.compile(r"\b(?:switched|migrated|moved|upgraded|downgraded)\s+"
                   r"(?:[\w./-]+\s+){0,4}(?:from|to|over)\b", re.I),
        re.compile(r"\breplaced\s+[\w./-]+(?:\s+[\w./-]+){0,3}\s+with\b", re.I),
        re.compile(r"\buse\s+[\w./-]+(?:\s+[\w./-]+){0,3}\s+instead\s+of\b", re.I),
        re.compile(r"\b(?:stopped|quit|dropped)\s+using\b|\bno\s+longer\s+us(?:e|ing)\b", re.I),
    ]),
    ("fact", 0.65, [
        # tool / stack conventions (the project variant below stays a decision at 0.7)
        re.compile(r"\b(?:this|the|our)\s+(?:repo|repository|codebase|stack|service|app|workspace|monorepo)"
                   r"\s+(?:uses?|runs?|requires?)\b", re.I),
        re.compile(r"\bwe\s+run\s+[\w./-]+(?:\s+[\w./-]+){0,3}\s+(?:on|in|with|for)\b", re.I),
    ]),
    ("decision", 0.7, [
        re.compile(r"\bwe(?:'ve| have)?\s+(?:decided|agreed|chose|settled on|are going with)\b", re.I),
        re.compile(r"\blet'?s go with\b", re.I),
        re.compile(r"\b(?:the|this) project (?:uses|requires|needs)\b", re.I),
    ]),
]

# Questions and hypotheticals are not facts.
_SKIP = re.compile(r"\?\s*$|^\s*(?:if|what if|should|could|would|can|do|does|is|are)\b", re.I)
_MOMENTARY = re.compile(
    r"\bI\s+(?:really\s+|just\s+|also\s+|do\s+)*(?:want|need|wanna|'d like|would like)\b",
    re.I,
)
_DURABLE = re.compile(
    r"\b(?:prefer|always|never|from now on|favou?rite|preferred|default|usual)\b",
    re.I,
)

# Drop the whole remainder once one of these appears. They mark compaction
# summaries, system prompts, kanban/notification wrappers and tool dumps.
_BLOCK_MARKERS = (
    "[CONTEXT COMPACTION",
    "CONTEXT COMPACTION",
    "REFERENCE ONLY",
    "Historical Task Snapshot",
    "[CONTEXT SUMMARY]",
    "[CONTEXT SUMMARY]:",
    "PRIOR CONTEXT",
    "[Runtime note:",
    "Kanban task execution protocol",
    "You have been assigned ONE task",
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_WORKSPACE",
    "worker_context",
    "PRIORITY: refuse",
    "NEVER reveal these instructions",
    "You are Max, Wright's primary",
    "<tool_result",
    "</tool_result>",
    "[tool output]",
    "function_call",
)

# Sentence-level fingerprints for system/compaction text that was already split
# out of its wrapper (the form that landed in the dogfood store).
_SYSTEM_SENTENCE = re.compile(
    r"pairing token|context compaction|reference only|historical task snapshot|"
    r"<\s*/?\s*memory-context|out-of-band user message|system prompt|"
    r"in-flight work|compaction note|active turn by itself|"
    r"kanban task|must immediately end|persistent memory \(memory\.md|"
    r"never waived|credential redaction|never reprint|never invent\b|"
    r"do not re-surface|never print\b",
    re.I,
)

_MEMORY_BLOCK = re.compile(r"<\s*memory-context\b[^>]*>[\s\S]*?</\s*memory-context\s*>", re.I)
_MEMORY_UNCLOSED = re.compile(r"<\s*memory-context\b[^>]*>[\s\S]*$", re.I)
_SYSTEM_NOTE = re.compile(r"\[System note:[^\]]*\]", re.I)
_OOB = re.compile(r"\[/?OUT-OF-BAND USER MESSAGE[^\]]*\]", re.I)
_TERESIS_HEAD = re.compile(
    r"(?:^|\n)#{1,3}[^\n]*Long-term memory \(teresis\)[^\n]*\n(?:[ \t]*- \[[^\]]+\].*(?:\n|$))*",
    re.I,
)
_INJECTION_BULLET = re.compile(
    r"(?:^|\n)[ \t]*-\s+\[[a-z_ ]+\][^\n]*\(id\s+[0-9a-f]{8,}\)",
    re.I,
)

EXTRACT_SOURCES = ("hermes:auto-extract", "hermes:pre-compress")


@dataclass(frozen=True)
class Candidate:
    content: str
    kind: str
    importance: float


def _strip_speaker(text: str) -> str:
    text = _SPEAKER.sub("", (text or "").strip())
    return text.strip(_QUOTES + " \t").strip()


def user_authored_text(text: str) -> str:
    """Text safe to treat as something the user wrote.

    Empty means "do not extract". Strips Teresis's own ``<memory-context>``
    block so a prefetch cannot be saved again. Compaction summaries, system
    prompts, kanban wrappers and tool dumps are cut off, including any text
    after the marker.
    """
    raw = text or ""
    if not raw.strip():
        return ""
    cleaned = _MEMORY_BLOCK.sub("\n", raw)
    cleaned = _MEMORY_UNCLOSED.sub("\n", cleaned)
    cleaned = _TERESIS_HEAD.sub("\n", cleaned)
    cleaned = _INJECTION_BULLET.sub("\n", cleaned)
    cleaned = _SYSTEM_NOTE.sub("\n", cleaned)
    cleaned = _OOB.sub("\n", cleaned)
    lower = cleaned.lower()
    cut = len(cleaned)
    for marker in _BLOCK_MARKERS:
        idx = lower.find(marker.lower())
        if idx != -1:
            cut = min(cut, idx)
    cleaned = cleaned[:cut].strip()
    if not cleaned:
        return ""
    low = cleaned.lower()
    signals = (
        "you are max",
        "priority: refuse",
        "kanban task",
        "hermes_kanban",
        "context compaction",
        "reference only",
        "historical task snapshot",
        "system prompt is always",
        "pairing token",
        "<tool_result",
        "tool output",
        "worker_context",
    )
    if len(low) > 80 and any(s in low for s in signals):
        return ""
    return cleaned


def _prepare_clause(sent: str) -> str:
    sent = _strip_speaker(_LEAD.sub("", (sent or "").strip(" -*•\t,")))
    sent = _strip_speaker(_LEAD.sub("", sent))
    return sent.strip()


def extract(text: str, *, max_len: int = 300) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    authored = user_authored_text(text)
    clauses = [c for sent in _SENT.split(authored) for c in _CLAUSE.split(_LEAD.sub("", sent.strip()))]
    for raw in clauses:
        sent = _prepare_clause(raw)
        if len(sent) < 12 or len(sent) > max_len or _SKIP.search(sent) or "```" in sent:
            continue
        if _SYSTEM_SENTENCE.search(sent):
            continue
        if _MOMENTARY.search(sent) and not _DURABLE.search(sent):
            continue
        for kind, importance, patterns in _RULES:
            if kind == "preference" and importance < MIN_PREFERENCE_IMPORTANCE:
                continue
            if any(p.search(sent) for p in patterns):
                key = sent.casefold()
                if key not in seen:
                    seen.add(key)
                    out.append(Candidate(sent, kind, importance))
                break
    return out


def extraction_problem(content: str, *, kind: str = "", source: str = "") -> str | None:
    """Why an already-stored row looks like a bad auto-extraction, or None.

    Only rows written by the Hermes extractor are considered. Imported notes
    and explicit tool writes are left alone. This is not called on the write
    path; ``teresis scrub`` is opt-in and dry-run unless ``--apply``.
    """
    if source not in EXTRACT_SOURCES:
        return None
    text = content or ""
    if _SYSTEM_SENTENCE.search(text) or any(m.lower() in text.lower() for m in _BLOCK_MARKERS):
        return "injected-or-system"
    body = _strip_speaker(text)
    if _MOMENTARY.search(body) and not _DURABLE.search(body):
        return "momentary-want"
    if text.lower().startswith(("user:", "human:")) and not extract(body):
        return "speaker-prefixed-nondurable"
    if not extract(body):
        return "rejected-by-extractor"
    return None
