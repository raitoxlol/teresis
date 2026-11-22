"""Deterministic secret detection and redaction (stdlib ``re`` only, no LLM).

Every write path (``MemoryStore.remember``/``update``, the MCP tools, and the Hermes
provider) passes content through ``redact_secrets`` so raw credentials can never land in
SQLite: matching spans become ``[REDACTED:<kind>]`` while the surrounding fact is kept.
``contains_secret`` answers the cheap yes/no + reason question for callers that want to
warn or block instead of redacting.

Precision over recall: provider-prefixed tokens and PEM blocks are near-unique shapes;
``NAME=value`` assignments only count when the value is long, single-token, and not a
placeholder (``your-api-key``, ``$VAR``, ``<token>``, ``xxx`` ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Published documentation/example values that match real key shapes.
_ALLOWLIST = frozenset({
    "AKIAIOSFODNN7EXAMPLE",                      # AWS docs access key
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # AWS docs secret key
})

# Words that mark a value as a placeholder rather than a live credential.
_PLACEHOLDER_WORDS = frozenset(
    """your youre placeholder example sample dummy fake test testing demo redacted change changeme
    insert replace here todo none null na notset n/a secret token key apikey password passwd pwd
    credential credentials auth user username admin root real actual some my the this put""".split()
)

_TRAIL = ".,;:!?)]}\"'"


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    check: Callable[[re.Match[str]], bool] | None = None      # extra gate on each match
    repl: Callable[[re.Match[str], str], str] | None = None  # default: whole match -> marker


def _placeholder_parts(v: str) -> set[str]:
    return {p for p in re.split(r"[^a-z0-9]+", v.lower()) if p}


def _is_placeholder(v: str) -> bool:
    """True when ``v`` looks like a doc placeholder/reference rather than a real credential."""
    v = v.strip().rstrip(_TRAIL).strip("'\"")
    if len(v) < 16 or v in _ALLOWLIST:
        return True
    if v[0] in "$<`{[(" or any(c in v for c in "([{<$"):
        return True
    if re.fullmatch(r"[x*._\-]+", v):
        return True
    return bool(_placeholder_parts(v) & _PLACEHOLDER_WORDS)


# NAME=value / NAME: value where NAME ends in key|secret|token|password|... and the value is a
# single token of 16+ chars. ``MONKEY``/``tokenizer``/``keyboard`` do not match: the sensitive
# word must be the whole name or follow a separator.
_ENV_NAME = (
    r"(?:[a-z][a-z0-9]*[_-])+"
    r"(?:key|secret|token|password|passwd|pwd|credentials?|auth|apikey)"
    r"|api[_-]?key|access[_-]?key|secret[_-]?key|private[_-]?key|client[_-]?secret"
    r"|(?:auth|access|refresh|session|bearer|id|api)[_-]?token|apikey"
    r"|key|secret|token|password|passwd|pwd|credentials?"
)
_ENV = re.compile(
    rf"(?i)\b(?P<n>{_ENV_NAME})(?P<qc>['\"]?)(?P<s>[\t ]*[:=][\t ]*)(?P<q>['\"]?)(?P<v>[^\s'\";,#]+)")


def _env_check(m: re.Match[str]) -> bool:
    return not _is_placeholder(m.group("v"))


def _env_repl(m: re.Match[str], marker: str) -> str:
    v = m.group("v").rstrip(_TRAIL)
    keep = m.group("n") + (m.group("qc") or "") + m.group("s") + m.group("q")
    return keep + marker + m.group("v")[len(v):]


def _uri_check(m: re.Match[str]) -> bool:
    v = m.group(1)
    if len(v) < 4 or v in _ALLOWLIST or v[0] in "$<`{[(":
        return False
    if re.fullmatch(r"[x*._\-]+", v):
        return False
    return not (_placeholder_parts(v) & _PLACEHOLDER_WORDS)


def _uri_repl(m: re.Match[str], marker: str) -> str:
    return m.group(0)[: -(len(m.group(1)) + 1)] + marker + "@"


def _bearer_repl(m: re.Match[str], marker: str) -> str:
    return marker if not m.group(1) else m.group(0)[: -len(m.group(1))] + marker


# Order matters: more specific shapes first (sk-ant- before sk-, github before hf_, PEM first),
# env assignments last so provider-prefixed values keep their precise kind.
_RULES: list[_Rule] = [
    _Rule("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
        r"(?:.*?-----END [A-Z0-9 ]*PRIVATE KEY-----|.*)", re.S)),
    _Rule("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    _Rule("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    _Rule("stripe_key", re.compile(r"\b(?:[sr]k_(?:live|test)_|whsec_)[A-Za-z0-9]{16,}")),
    _Rule("resend_key", re.compile(r"\bre_[A-Za-z0-9_]{20,}")),
    _Rule("github_token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    _Rule("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    _Rule("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    _Rule("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}"),
          check=lambda m: m.group(0) not in _ALLOWLIST),
    _Rule("bearer_token", re.compile(
        r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{20,})"
        r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), repl=_bearer_repl),
    _Rule("uri_credential", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]+)@"),
          check=_uri_check, repl=_uri_repl),
    _Rule("env_secret", _ENV, check=_env_check, repl=_env_repl),
]


def _ok(rule: _Rule, m: re.Match[str]) -> bool:
    return rule.check is None or rule.check(m)


def contains_secret(text: str) -> str | None:
    """Kind of the first credential-looking span in ``text`` (e.g. ``"openai_key"``), else None."""
    for rule in _RULES:
        for m in rule.pattern.finditer(text or ""):
            if _ok(rule, m):
                return rule.kind
    return None


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Replace every credential-looking span with ``[REDACTED:<kind>]``.

    Returns ``(scrubbed_text, kinds)`` — ``kinds`` lists each matched kind once, in rule
    order (see ``_RULES``). Placeholder-looking values are left alone.
    """
    text = text or ""
    kinds: list[str] = []

    def _sub(rule: _Rule):
        def inner(m: re.Match[str]) -> str:
            if not _ok(rule, m):
                return m.group(0)
            if rule.kind not in kinds:
                kinds.append(rule.kind)
            marker = f"[REDACTED:{rule.kind}]"
            return rule.repl(m, marker) if rule.repl else marker
        return inner

    for rule in _RULES:
        text = rule.pattern.sub(_sub(rule), text)
    return text, kinds
