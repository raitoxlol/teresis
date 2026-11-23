"""Deterministic entity extraction (stdlib only, no LLM).

Entities give retrieval a second, structural channel: facts that never share a word
("Priya owns billing" / "Priya is on leave") still connect through ``Priya``.

Precision over recall. A span is only a *candidate* here; ``MemoryStore`` promotes it to a
traversable entity once it is either explicit (``[[Link]]``, ``@mention``, a host, a path, a
``owner/repo``) or has been seen in at least two different memories. One-off capitalised words
at the start of a sentence ("Fixed", "Deploy") therefore never pollute the graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("person", "project", "host", "tool", "concept")

_WIKI = re.compile(r"\[\[([^\[\]\n]{1,80})\]\]")
_MENTION = re.compile(r"(?<![\w@/])@([A-Za-z][\w.-]{0,40})")
_HOST = re.compile(
    r"\b((?:[A-Za-z0-9][A-Za-z0-9-]*\.)+(?:com|org|net|io|dev|ai|app|tech|cafe|sh|co|xyz|me|gg|so))\b"
)
_HOSTPORT = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9.-]{1,60}):(\d{2,5})\b")
_PATH = re.compile(r"(?:^|[\s(])((?:~|\.{1,2})?/[\w.@%+-]+(?:/[\w.@%+-]+)+)")
_REPO = re.compile(r"(?<![\w/])([A-Za-z0-9][\w.-]{1,38}/[\w.-]{1,38})(?![\w/])")
_HOSTPATH = re.compile(
    r"\b(?:[A-Za-z0-9][A-Za-z0-9-]*\.)+(?:com|org|net|io|dev|ai|app|tech|cafe|sh|co|xyz|me|gg|so)"
    r"/([\w.@%+-]+(?:/[\w.@%+-]+)+)"
)
_PROPER = re.compile(r"(?<![\w'’-])([A-Z][\w'’-]*)((?:\s+(?:[A-Z][\w'’-]*|\d+(?:\.\d+)*)){0,2})(?![\w])")

# Sentence-initial capitals and generic verbs/nouns that are not names.
_NOISE = frozenset(
    """a an the this that these those it its i we you he she they my our your their his her
    and but or so then than if when while because since after before once now here there
    what who why how where which whether not no yes ok okay sure thanks thank please
    add added adds fix fixed fixes fixing use used uses using run ran runs make made makes
    set sets note noted notes see saw seen keep kept keeps save saved saves store stored
    deploy deployed deploys build built builds test tested tests check checked checks
    update updated updates remove removed removes delete deleted deletes change changed changes
    create created creates install installed installs start started starts stop stopped stops
    moved migrated moves migrate write wrote written writes read reads get got gets put
    also just only still even very really much more most less least many few some any all
    both each every other another same different new old next last first second third
    monday tuesday wednesday thursday friday saturday sunday january february march april may
    june july august september october november december today tomorrow yesterday
    memory memories agent agents user users project projects fact facts note notes
    never always should must can could would will shall may might do does did done
    ok okay lgtm wip todo tbd na none null true false""".split()
)


@dataclass(frozen=True)
class Entity:
    key: str      # normalized lookup key
    name: str     # display form as first seen
    kind: str     # one of KINDS
    weight: float  # 1.0 explicit, 0.5 inferred
    explicit: bool


def normalize(name: str) -> str:
    """Case-folded, whitespace-collapsed lookup key."""
    return " ".join(name.strip().strip("[](){}.,;:!?\"'").split()).casefold()


def _add(found: dict[str, Entity], name: str, kind: str, weight: float, explicit: bool) -> None:
    name = " ".join(name.strip().split())
    key = normalize(name)
    if len(key) < 2 or key in _NOISE:
        return
    prev = found.get(key)
    if prev is None or (explicit and not prev.explicit):
        found[key] = Entity(key, name, kind, max(weight, prev.weight if prev else 0.0), explicit)
    elif weight > prev.weight:
        found[key] = Entity(key, prev.name, prev.kind if prev.explicit else kind, weight, prev.explicit)


def extract(text: str, *, limit: int = 14) -> list[Entity]:
    """Candidate entities in ``text``, highest confidence first."""
    found: dict[str, Entity] = {}
    if not text:
        return []

    for m in _WIKI.finditer(text):
        raw = m.group(1).strip()
        kind = "concept"
        if ":" in raw:
            prefix, rest = raw.split(":", 1)
            if prefix.strip().lower() in KINDS and rest.strip():
                kind, raw = prefix.strip().lower(), rest.strip()
        _add(found, raw, kind, 1.0, True)

    for m in _MENTION.finditer(text):
        _add(found, m.group(1), "person", 1.0, True)

    for m in _HOST.finditer(text):
        _add(found, m.group(1), "host", 1.0, True)

    for m in _HOSTPORT.finditer(text):
        _add(found, f"{m.group(1)}:{m.group(2)}", "host", 1.0, True)

    for m in _PATH.finditer(text):
        _add(found, m.group(1), "project", 1.0, True)

    for m in _REPO.finditer(text):
        if m.group(1).count("/") == 1 and not m.group(1).startswith(("http", "~/", "./", "../")):
            _add(found, m.group(1), "project", 1.0, True)

    for m in _HOSTPATH.finditer(text):
        _add(found, m.group(1), "project", 1.0, True)

    for m in _PROPER.finditer(text):
        head, tail = m.group(1), m.group(2) or ""
        span = (head + tail).strip()
        tokens = span.split()
        if head.casefold() in _NOISE:
            continue
        if len(tokens) == 1:
            if len(head) < 3 or head.isupper():
                continue
            kind = "person"
        else:
            if all(t.casefold() in _NOISE for t in tokens):
                continue
            kind = "concept"
        _add(found, span, kind, 0.5, False)

    out = sorted(found.values(), key=lambda e: (-e.weight, -len(e.key)))
    return out[:limit]
