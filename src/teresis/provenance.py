"""Where a memory came from, and whether it may be injected as a fact.

Auto-capture used to rely on a phrase denylist. New wrapper text always beat it. This module
holds the allowlist side instead:

* ``turn_trust``: is this turn provably typed by a person?
* ``origin`` / ``trust`` on every row (``meta.origin``), with a legacy fallback for old rows.
* ``injectable``: the last gate before a row is put into a prompt. Candidates never pass.

Core module, zero dependencies.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .extract import EXTRACT_SOURCES, _BLOCK_MARKERS, _MEMORY_BLOCK, _SYSTEM_SENTENCE

# --------------------------------------------------------------------------- origins
USER_TYPED = "user-typed"
USER_TOOL = "user-explicit-tool"
ASSISTANT_TOOL = "assistant-tool"
IMPORT = "import"
AUTO_CANDIDATE = "auto-candidate"
SYSTEM_TURN = "system-turn"  # an episode of a turn a person did not write
LEGACY = "legacy"            # written before provenance existed and not recognisable by source

ORIGINS = (USER_TYPED, USER_TOOL, ASSISTANT_TOOL, IMPORT, AUTO_CANDIDATE, SYSTEM_TURN, LEGACY)
TRUST = {
    USER_TYPED: "human",
    USER_TOOL: "human",
    ASSISTANT_TOOL: "assistant",
    IMPORT: "import",
    AUTO_CANDIDATE: "untrusted",
    SYSTEM_TURN: "system",
    LEGACY: "legacy",
}
CANDIDATE_KIND = "candidate"
DEFAULT_CANDIDATE_TTL_DAYS = 14.0
CANDIDATE_IMPORTANCE = 0.2

# --------------------------------------------------------------------------- turn trust
DEFAULT_SYSTEM_AUTHORS = (
    "kanban dispatcher", "kanban", "dispatcher", "cron", "cronjob", "scheduler", "webhook",
    "system", "gateway", "hermes", "compaction", "memory",
)
DEFAULT_UNTRUSTED_PLATFORMS = ("kanban", "cron", "webhook", "system", "batch", "subagent")
# Platforms where a message without a turn_author is a person typing into a chat or terminal.
DEFAULT_INTERACTIVE_PLATFORMS = (
    "cli", "tui", "desktop", "web", "telegram", "discord", "slack", "imessage", "photon", "bluebubbles",
    "signal", "whatsapp", "matrix", "mattermost", "sms", "line", "teams",
)

# Text that is shaped like a wrapper, summary or injected block, whoever "sent" it.
_WRAPPER_HEAD = re.compile(
    r"^\s*(?:"
    r"#{1,3}\s*kanban task\b"
    r"|\[(?:system|important|context|scheduled|cron|runtime|automated|your active)\b"
    r"|<\s*memory-context\b"
    r"|you have been assigned one task"
    r"|this session is being continued"
    r"|(?:the following is )?a summary of (?:the )?(?:prior|previous|earlier) (?:conversation|context)"
    r"|(?:scheduled|cron) (?:job|task|run)\b"
    r")",
    re.I,
)
_SPEAKER_PREFIX = re.compile(r"^\s*[\w .'@-]{1,40}:\s+(?=\S)")


def _csv(value: Any, default: Iterable[str] = ()) -> frozenset[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [str(v) for v in value]
    else:
        items = str(value or "").split(",")
    return frozenset(i.strip().casefold() for i in items if i and i.strip()) | frozenset(
        d.casefold() for d in default)


def wrapper_shaped(text: str) -> bool:
    """True when text starts like a task body, notice, cron wake-up, summary or memory block."""
    body = (text or "").strip()
    if _WRAPPER_HEAD.match(body):
        return True
    stripped = _SPEAKER_PREFIX.sub("", body, count=1)
    return stripped != body and bool(_WRAPPER_HEAD.match(stripped))


def structural_injected(text: str) -> bool:
    """Structural wrapper markers (compaction banners, kanban protocol, memory blocks) anywhere in text."""
    low = (text or "").lower()
    return bool(_MEMORY_BLOCK.search(text or "")) or "<memory-context" in low or any(
        m.lower() in low for m in _BLOCK_MARKERS)


def turn_trust(
    turn_author: Mapping[str, Any] | None,
    platform: str = "",
    *,
    system_authors: Any = (),
    untrusted_platforms: Any = (),
    interactive_platforms: Any = (),
) -> tuple[bool, str]:
    """Decide whether a user-role turn was typed by a person. Returns ``(human, reason)``.

    Allowlist: no extraction unless this positively says human. Hermes only sends
    ``turn_author`` for some deliveries, so a missing author counts as human on an interactive
    platform and nowhere else.
    """
    plat = (platform or "").strip().casefold()
    if plat in _csv(untrusted_platforms, DEFAULT_UNTRUSTED_PLATFORMS):
        return False, f"platform:{plat}"
    if isinstance(turn_author, Mapping) and turn_author:
        if turn_author.get("is_bot"):
            return False, "author:bot"
        names = _csv(system_authors, DEFAULT_SYSTEM_AUTHORS)
        for field in ("name", "id"):
            value = str(turn_author.get(field) or "").strip().casefold()
            if value and (value in names or value.startswith("bot:")):
                return False, f"author:{value}"
        if not (turn_author.get("name") or turn_author.get("id")):
            return False, "author:unnamed"
        return True, "author:human"
    if plat and plat in _csv(interactive_platforms, DEFAULT_INTERACTIVE_PLATFORMS):
        return True, f"interactive:{plat}"
    return False, f"unknown-author:{plat or 'no-platform'}"


# --------------------------------------------------------------------------- row provenance
def _as_meta(meta: Any) -> Mapping[str, Any]:
    return meta if isinstance(meta, Mapping) else {}


def effective_origin(meta: Any, source: str | None, kind: str = "") -> str:
    """``meta.origin`` when present, else inferred from ``source`` for rows written before provenance."""
    origin = _as_meta(meta).get("origin")
    if origin in ORIGINS:
        return str(origin)
    src = source or ""
    if src in EXTRACT_SOURCES:
        return AUTO_CANDIDATE
    if src.startswith("hermes:import"):
        return IMPORT
    if src == "hermes:memory-tool":
        return ASSISTANT_TOOL
    return LEGACY


def trust_of(origin: str) -> str:
    return TRUST.get(origin, "untrusted")


def is_promoted(meta: Any) -> bool:
    return bool(_as_meta(meta).get("promoted_by"))


def is_candidate(kind: str) -> bool:
    return kind == CANDIDATE_KIND


def needs_review(kind: str, meta: Any, source: str | None) -> bool:
    """A candidate row, or an old auto-extracted row nobody has promoted."""
    if kind == "episode":
        return False
    if is_candidate(kind):
        return True
    return effective_origin(meta, source, kind) == AUTO_CANDIDATE and not is_promoted(meta)


def injectable(kind: str, content: str, meta: Any, source: str | None) -> tuple[bool, str]:
    """May this row be put in a prompt as a standing fact? Applies to promoted rows too."""
    if is_candidate(kind):
        return False, "candidate"
    origin = effective_origin(meta, source, kind)
    m = _as_meta(meta)
    if kind == "episode":
        if m.get("trust") == "system" or origin == SYSTEM_TURN:
            return False, "system-turn"
        if source == "hermes:pre-compress":
            return False, "checkpoint"
        body = (content or "")
        if structural_injected(body) or wrapper_shaped(body):
            return False, "injected"
        return True, "ok"
    if origin == AUTO_CANDIDATE and not is_promoted(meta):
        return False, "unreviewed-auto"
    if structural_injected(content):
        return False, "injected"
    if origin in (AUTO_CANDIDATE, USER_TYPED, SYSTEM_TURN) and (
            _SYSTEM_SENTENCE.search(content or "") or wrapper_shaped(content)):
        return False, "injected"
    return True, "ok"
