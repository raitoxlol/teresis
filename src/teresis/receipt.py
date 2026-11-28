"""Receipts: where a memory came from, who said it, and what it replaced.

``memory_why`` / ``teresis why`` answer "why do you know this" with a receipt per id:
origin and trust, platform/profile/author of the write, status, and the versions it
replaced. Core module, zero dependencies.
"""

from __future__ import annotations

from typing import Any

from . import provenance as P
from .review import day_of

_SAID = {
    P.USER_TYPED: "you said this",
    P.USER_TOOL: "saved from the command line",
    P.ASSISTANT_TOOL: "the assistant saved this",
    P.IMPORT: "imported from Hermes memory files",
    P.AUTO_CANDIDATE: "picked up automatically from conversation",
    P.SYSTEM_TURN: "from an automated turn, not typed by a person",
    P.LEGACY: "saved before sources were tracked",
}


def receipt(store, memory_id: str) -> dict[str, Any] | None:
    """One receipt for ``memory_id``, or None when the id does not exist."""
    m = store.get(memory_id)
    if m is None:
        return None
    meta = m.meta or {}
    origin = P.effective_origin(meta, m.source, m.kind)
    if m.deleted_at:
        status = "forgotten"
    elif m.superseded_by:
        status = "superseded"
    elif m.expires_at is not None and m.expires_at <= store.clock():
        status = "expired"
    elif P.is_candidate(m.kind):
        status = "candidate"
    else:
        status = "current"
    chain = store.history(memory_id)
    earlier = [v for v in chain[: chain.index(m)] if v.id != m.id][-3:]
    replaced = [{"id": v.id, "content": v.content, "created": day_of(v.created_at),
                 "until": day_of(v.superseded_at) if v.superseded_at else None} for v in earlier]
    return {
        "id": m.id,
        "content": m.content,
        "kind": m.kind,
        "key": m.key,
        "scope": m.scope,
        "origin": origin,
        "trust": P.trust_of(origin),
        "said": _SAID.get(origin, _SAID[P.LEGACY]),
        "source": m.source,
        "platform": meta.get("platform") or None,
        "profile": meta.get("profile") or None,
        "author": meta.get("author") or None,
        "session_id": meta.get("session_id") or None,
        "created": day_of(m.created_at),
        "status": status,
        "superseded_by": m.superseded_by,
        "kept_via": meta.get("promoted_by") or None,
        "replaced": replaced,
    }


def _lines(r: dict[str, Any]) -> list[str]:
    lines = [f"[{r['id']}] {r['content']}"]
    kind = r["kind"] + (f" {r['key']}" if r.get("key") else "")
    status = r["status"] + (f" (replaced by {r['superseded_by']})" if r.get("superseded_by") else "")
    if r["status"] == "candidate":
        status += " (unreviewed, never injected)"
    lines.append(f"- {kind} in {r['scope']}; status: {status}")
    said = r["said"]
    if r.get("platform"):
        said += f" on {r['platform']}"
    if r.get("author"):
        said += f" by {r['author']}"
    if r.get("profile"):
        said += f", profile {r['profile']}"
    lines.append(f"- source: {said}, {r['created']}")
    if r.get("kept_via"):
        lines.append(f"- kept via: {r['kept_via']}")
    for v in r.get("replaced") or []:
        lines.append(f'- replaced: "{v["content"]}" ({v["created"]} to {v["until"]})')
    return lines


def render(receipts: list[dict[str, Any]], missing: list[str]) -> str:
    """Human-readable receipts, one block each, separated by a blank line."""
    if not receipts and not missing:
        return "No memories to explain."
    blocks = ["\n".join(_lines(r)) for r in receipts]
    blocks += [f"[{i}] not found" for i in missing]
    return "\n\n".join(blocks)


def explain(store, ids: list[str]) -> tuple[str, dict[str, Any]]:
    """Receipts for ``ids`` (de-duplicated, order kept) plus the rendered text."""
    seen: dict[str, None] = {}
    for i in ids:
        if i:
            seen[str(i)] = None
    receipts, missing = [], []
    for i in seen:
        r = receipt(store, i)
        (receipts if r else missing).append(r if r else i)
    return render(receipts, missing), {"receipts": receipts, "missing": missing}
