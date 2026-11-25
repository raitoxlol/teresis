"""Prompt-injection and exfiltration shapes that must not become a standing memory.

Memory text is put into the system/user context of later sessions, so a poisoned entry persists.
Hermes' built-in memory tool scans writes for these shapes (``tools/threat_patterns.py``, scope
``strict``). The patterns below are a compact, stdlib-only adaptation of that idea so Teresis does not
depend on Hermes internals. Precision first: each pattern anchors on attack vocabulary, not on
bossy English ("you must", "always").
"""

from __future__ import annotations

import re

_FILLER = r"(?:\w{1,32}\s{1,8}){0,6}"

_PATTERNS: list[tuple[str, str]] = [
    (rf"\bignore\s{{1,8}}{_FILLER}(?:previous|prior|above|earlier|all)\s{{1,8}}{_FILLER}(?:instructions|rules|prompts?|guidelines)", "prompt_injection"),
    (r"\bsystem\s{1,8}prompt\s{1,8}override\b", "sys_prompt_override"),
    (rf"\bdisregard\s{{1,8}}{_FILLER}(?:your|all|any|previous|prior)\s{{1,8}}{_FILLER}(?:instructions|rules|guidelines)", "disregard_rules"),
    (r"(?<!n't )(?<!not )(?<!never )\bforget\s{1,8}(?:about\s{1,8})?(?:your|all|any|previous|prior|above|earlier)\s{1,8}(?:\w{1,32}\s{1,8}){0,3}(?:instructions|rules|guidelines)\b", "forget_rules"),
    (rf"\bdo\s{{1,8}}not\s{{1,8}}{_FILLER}tell\s{{1,8}}{_FILLER}the\s{{1,8}}user\b", "deception_hide"),
    (r"\b(?:developer|jailbreak|dan|god|unrestricted)\s{1,8}mode\b", "mode_hijack"),
    (rf"\b(?:reveal|print|output|show|repeat|leak|dump|disclose)\s{{1,8}}{_FILLER}(?:your\s{{1,8}})?(?:hidden\s{{1,8}}|initial\s{{1,8}}|full\s{{1,8}}|entire\s{{1,8}})?system\s{{1,8}}prompt\b", "leak_system_prompt"),
    (rf"\b(?:respond|answer|reply)\s{{1,8}}without\s{{1,8}}{_FILLER}(?:restrictions|limitations|filters|safety)\b", "remove_filters"),
    (r"\b(?:curl|wget)\b[^\n|]{0,300}\|\s{0,8}(?:sudo\s{1,8})?(?:ba|z|da)?sh\b", "pipe_to_shell"),
    (r"\b(?:curl|wget)\b[^\n]{0,300}\$\{?\w{0,64}(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b", "exfil_secret_var"),
    (r"\bcat\s{1,8}[^\n]{0,200}(?:\.env\b|\.netrc|\.pgpass|\.npmrc|\.pypirc|credentials\b|id_rsa)", "read_secrets"),
    (r"\b(?:send|post|upload|transmit|forward|email)\s{1,8}[^\n]{0,200}\s(?:to|at)\s{1,8}(?:https?://|\S+@\S+\.\S+)", "send_to_destination"),
    (r"\bauthorized_keys\b", "ssh_backdoor"),
    (r"(?:\$HOME|~)/\.hermes/\.env", "hermes_env"),
    (r"\b(?:update|modify|edit|write|change|append\s{1,8}to|add\s{1,8}to)\s{1,8}[^\n]{0,200}(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules|SOUL\.md|\.hermes/config\.yaml)", "agent_config_mod"),
]
_COMPILED = [(re.compile(p, re.I), pid) for p, pid in _PATTERNS]

# Bidirectional controls, word joiner / zero-width space / BOM and the Unicode TAG block hide text from a
# human reviewer. ZWJ and ZWNJ are left alone: emoji sequences and several scripts need them.
_INVISIBLE = re.compile("[\u200b\u2060\u2062-\u2064\ufeff\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]")
_MAX_SCAN = 65536


def scan(text: str) -> list[str]:
    """Pattern ids that match ``text`` (empty when it looks like ordinary memory content)."""
    if not text:
        return []
    text = text[:_MAX_SCAN]
    found = [pid for rx, pid in _COMPILED if rx.search(text)]
    if _INVISIBLE.search(text):
        found.append("invisible_text")
    return found


def first_threat(text: str) -> str | None:
    hits = scan(text)
    return hits[0] if hits else None


def rejection_message(hit: str) -> str:
    return (f"memory rejected: the text looks like a prompt-injection or exfiltration instruction ({hit}). "
            "Store the plain fact instead, not an instruction to the agent.")
