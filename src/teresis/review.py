"""Candidate quarantine: list, promote, reject, corroborate.

Auto-extracted claims are stored as kind ``candidate``. They are searchable by tool recall
and invisible to prefetch until promoted:

1. the user stated it in a human turn with a strong marker (done at capture time),
2. the same claim is seen in 2+ distinct sessions on 2+ distinct days, or
3. someone promotes it with ``teresis review promote``.

Unpromoted candidates expire (default 14 days) because they carry an ``expires_at``.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from . import provenance as P
from .store import DAY, Memory, MemoryStore
from .text import containment, term_set

MIN_SESSIONS = 2
MIN_DAYS = 2
_POLARITY = {"never", "always", "not", "no", "dont", "don't", "stop", "avoid", "without"}


def day_of(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def same_claim(a: str, b: str) -> bool:
    """Same statement in different words, same polarity, same numbers."""
    ta, tb = term_set(a.removeprefix("User: ")), term_set(b.removeprefix("User: "))
    if len(ta) < 2 or len(tb) < 2:
        return a.strip().casefold() == b.strip().casefold()
    words = lambda ts: {t for t in ts if not any(ch.isdigit() for ch in t)}
    if containment(words(ta), words(tb)) < 0.85 or abs(len(ta) - len(tb)) > max(2, len(ta) // 3):
        return False
    if any(t in _POLARITY for t in ta ^ tb):
        return False
    nums = lambda ts: {t for t in ts if any(ch.isdigit() for ch in t)}
    return nums(ta) == nums(tb)


def is_active(rec: dict[str, Any], now: float) -> bool:
    return (not rec.get("deleted_at") and not rec.get("superseded_by")
            and (rec.get("expires_at") is None or rec["expires_at"] > now))


def queue(store: MemoryStore) -> list[dict[str, Any]]:
    """Active rows waiting for review: candidates plus old auto-extracted rows nobody promoted."""
    now = store.clock()
    rows = []
    for rec in store.export():
        if is_active(rec, now) and P.needs_review(rec.get("kind") or "", rec.get("meta"), rec.get("source")):
            rows.append(describe(rec, now))
    return rows


def describe(rec: dict[str, Any], now: float) -> dict[str, Any]:
    meta = rec.get("meta") or {}
    origin = P.effective_origin(meta, rec.get("source"), rec.get("kind") or "")
    seen = meta.get("seen") or []
    return {
        "id": rec["id"],
        "scope": rec.get("scope"),
        "kind": rec.get("kind"),
        "intended_kind": meta.get("candidate_kind") or rec.get("kind"),
        "origin": origin,
        "trust": P.trust_of(origin),
        "source": rec.get("source"),
        "age_days": round((now - (rec.get("created_at") or now)) / DAY, 1),
        "sessions": len({s.get("s") for s in seen}),
        "days": len({s.get("d") for s in seen}),
        "legacy": not P.is_candidate(rec.get("kind") or ""),
        "content": rec.get("content"),
    }


def corroborated(meta: dict[str, Any], *, min_sessions: int = MIN_SESSIONS, min_days: int = MIN_DAYS) -> bool:
    seen = meta.get("seen") or []
    return (len({s.get("s") for s in seen}) >= min_sessions and len({s.get("d") for s in seen}) >= min_days)


def add_sighting(meta: dict[str, Any], session_id: str, ts: float, *, cap: int = 20) -> dict[str, Any]:
    """Return meta with this (session, day) recorded once."""
    seen = list(meta.get("seen") or [])
    entry = {"s": session_id or "unknown", "d": day_of(ts)}
    if entry not in seen:
        seen.append(entry)
    return {**meta, "seen": seen[-cap:]}


def promote(store: MemoryStore, memory_id: str, by: str = "review") -> Memory:
    """Turn a candidate (or unreviewed auto row) into a standing memory. Raises KeyError if not active."""
    mem = store.get(memory_id)
    if mem is None or mem.deleted_at or mem.superseded_by:
        raise KeyError(f"no active memory {memory_id!r}")
    kind = mem.meta.get("candidate_kind") or (mem.kind if not P.is_candidate(mem.kind) else "fact")
    changes: dict[str, Any] = {
        "kind": kind, "expires_at": None,
        "importance": float(mem.meta.get("candidate_importance") or max(mem.importance, 0.6)),
        "tags": [t for t in mem.tags if t != "candidate"],
        "meta": {"promoted_by": by, "promoted_at": store.clock()},
    }
    store.update(memory_id, **changes)
    old = mem.meta.get("supersedes")
    if old:
        store.supersede(old, memory_id)
    return store.get(memory_id)  # type: ignore[return-value]


def reject(store: MemoryStore, memory_id: str) -> int:
    """Soft-delete (history kept)."""
    return store.forget(memory_id)


def find_candidate(store: MemoryStore, content: str, scope: str) -> Memory | None:
    for m in store.recall("", scope=[scope], inherit=False, kinds=[P.CANDIDATE_KIND], k=200, touch=False):
        if same_claim(content, m.content):
            return m
    return None


def promote_many(store: MemoryStore, ids: Iterable[str], by: str = "review") -> list[str]:
    done = []
    for i in ids:
        promote(store, i, by)
        done.append(i)
    return done


def report(store: MemoryStore) -> dict[str, Any]:
    """Counts of active rows by origin and kind, the review queue, and rows with an untrusted origin."""
    now = store.clock()
    by_origin: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    queued: list[dict[str, Any]] = []
    untrusted: list[dict[str, Any]] = []
    for rec in store.export():
        if not is_active(rec, now):
            continue
        kind, meta, source = rec.get("kind") or "", rec.get("meta") or {}, rec.get("source")
        origin = P.effective_origin(meta, source, kind)
        by_origin[origin] = by_origin.get(origin, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if P.needs_review(kind, meta, source):
            queued.append(describe(rec, now))
            if not P.is_candidate(kind):
                untrusted.append(describe(rec, now))
        elif kind != "episode" and (origin == P.SYSTEM_TURN or source == "hermes:pre-compress"):
            untrusted.append(describe(rec, now))
    return {"active": sum(by_kind.values()), "by_origin": by_origin, "by_kind": by_kind,
            "candidates": sum(1 for q in queued if not q["legacy"]), "queue": queued,
            "untrusted": untrusted}
