"""Deterministic fact extraction from conversation text (no LLM).

Precision over recall: only first-person preference/rule statements and explicit team decisions
are captured. Each candidate is one sentence, so dedup and supersession work on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
# Compound sentences: split on ";" and on ", and/but/also" so each clause is one fact.
_CLAUSE = re.compile(r";\s+|,?\s+(?:and|but|also)\s+(?=(?:I|we|my|our|never|always|don't|do not|the|this)\b)", re.I)
_LEAD = re.compile(r"^(?:for future reference|note that|remember(?: that)?|fyi|heads up|just so you know)\s*[:,\-]?\s*", re.I)

_RULES: list[tuple[str, float, list[re.Pattern]]] = [
    ("preference", 0.6, [
        re.compile(r"\bI\s+(?:really\s+)?(?:prefer|like|love|hate|dislike|want|use|need)\b", re.I),
        re.compile(r"\bmy\s+(?:favou?rite|preferred|default|usual)\s+\w+(?:\s+\w+)?\s+is\b", re.I),
        re.compile(r"\bI(?:'m| am)\s+(?:based|located|living)\s+in\b", re.I),
    ]),
    ("procedure", 0.7, [
        re.compile(r"\b(?:always|never|don't ever|do not ever)\s+\w+", re.I),
        re.compile(r"\bfrom now on\b", re.I),
        re.compile(r"\bmake sure (?:to|you)\b", re.I),
    ]),
    ("fact", 0.6, [
        re.compile(r"\b(?:my|our)\s+(?:[\w-]+\s+){1,3}(?:is|are)\s+(?:called|named|at|on|hosted|located)\b", re.I),
        re.compile(r"\b(?:my|our)\s+(?:[\w-]+\s+){0,3}(?:port|host|url|endpoint|database|db|repo|branch)\s+(?:is|are)\b", re.I),
    ]),
    ("decision", 0.7, [
        re.compile(r"\bwe(?:'ve| have)?\s+(?:decided|agreed|chose|settled on|are going with)\b", re.I),
        re.compile(r"\blet'?s go with\b", re.I),
        re.compile(r"\b(?:the|this) project (?:uses|requires|needs)\b", re.I),
    ]),
]

# Questions and hypotheticals are not facts.
_SKIP = re.compile(r"\?\s*$|^\s*(?:if|what if|should|could|would|can|do|does|is|are)\b", re.I)


@dataclass(frozen=True)
class Candidate:
    content: str
    kind: str
    importance: float


def extract(text: str, *, max_len: int = 300) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    clauses = [c for sent in _SENT.split(text or "") for c in _CLAUSE.split(_LEAD.sub("", sent.strip()))]
    for sent in clauses:
        sent = _LEAD.sub("", (sent or "").strip(" -*•\t,")).strip()
        if len(sent) < 12 or len(sent) > max_len or _SKIP.search(sent) or "```" in sent:
            continue
        for kind, importance, patterns in _RULES:
            if any(p.search(sent) for p in patterns):
                key = sent.casefold()
                if key not in seen:
                    seen.add(key)
                    out.append(Candidate(sent, kind, importance))
                break
    return out
