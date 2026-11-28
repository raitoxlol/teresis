"""Candidate quarantine: list, promote, reject, corroborate.

Auto-extracted claims are stored as kind ``candidate``. They are searchable by tool recall
and invisible to prefetch until promoted:

1. the user stated it in a human turn with a strong marker (done at capture time),
2. the same claim is seen in 2+ distinct sessions on 2+ distinct days, or
3. someone promotes it with ``teresis review promote``.

Unpromoted candidates expire (default 14 days) because they carry an ``expires_at``.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt
    except ImportError:
        msvcrt = None  # type: ignore[assignment]
else:
    msvcrt = None  # type: ignore[assignment]

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


# ----------------------------------------------------------------- chat review
_KEEP_VERBS = {"keep", "promote", "approve", "save"}
_DROP_VERBS = {"drop", "reject", "discard", "forget"}


def parse_reply(text: str) -> list[tuple[str, str | list[int]]] | None:
    """Parse a whole-message review reply into ``(action, targets)`` clauses.

    Returns None unless the entire message is review commands: ``keep 1 3``,
    ``drop 2``, ``keep all``. Anything else (mixed prose, missing targets) is
    not a review reply.
    """
    t = (text or "").strip()
    if not t or len(t) > 120:
        return None
    t = t.casefold().rstrip(".!").strip()
    t = re.sub(r"^please[ ,]+|[ ,]+please$", "", t).strip()
    if not t:
        return None
    tokens = re.sub(r"[,;&]", " ", t).split()
    clauses: list[tuple[str, list[Any]]] = []
    action: str | None = None
    targets: list[Any] = []

    def flush() -> bool:
        if action is None:
            return True
        if not targets:
            return False
        clauses.append((action, list(targets)))
        return True

    for tok in tokens:
        tok = tok.lstrip("#")
        if tok in _KEEP_VERBS or tok in _DROP_VERBS:
            if not flush():
                return None
            action = "keep" if tok in _KEEP_VERBS else "drop"
            targets = []
        elif tok == "and":
            continue
        elif action is None:
            return None
        elif tok in ("all", "everything"):
            targets.append("all")
        elif tok.isdigit():
            targets.append(int(tok))
        else:
            return None
    if not flush() or not clauses:
        return None
    return [(a, "all" if "all" in ts else ts) for a, ts in clauses]


def offer_path(db_path: Any) -> Path | None:
    """Sidecar file holding pending review offers, next to the db. None for memory dbs."""
    if not db_path or str(db_path) == ":memory:":
        return None
    return Path(str(db_path) + ".review.json")


# A numbered offer belongs to the conversation that showed it. Several Hermes processes
# (a gateway and a dashboard, say) share one db and one scope, so the key is (scope,
# session). Offers older than OFFER_MAX_AGE_DAYS are dropped and only the newest
# OFFER_MAX_COUNT are kept, so the file stays small.
OFFER_MAX_AGE_DAYS = 14.0
OFFER_MAX_COUNT = 200


def _offer_key(scope: str, session: str) -> str:
    return json.dumps([scope, session])


def prune_offers(offers: dict[str, Any], now: float) -> dict[str, Any]:
    """Well-formed offers younger than OFFER_MAX_AGE_DAYS, newest OFFER_MAX_COUNT only."""
    live = {}
    for key, e in offers.items():
        if (isinstance(e, dict) and isinstance(e.get("scope"), str) and isinstance(e.get("session"), str)
                and isinstance(e.get("at"), (int, float)) and math.isfinite(e["at"])
                and isinstance(e.get("ids"), list) and key == _offer_key(e["scope"], e["session"])
                and now - float(e["at"]) <= OFFER_MAX_AGE_DAYS * DAY):
            live[key] = e
    newest = sorted(live.items(), key=lambda kv: float(kv[1]["at"]), reverse=True)
    return dict(newest[:OFFER_MAX_COUNT])


def put_offer(offers: dict[str, Any], scope: str, session: str, ids: list[str], now: float) -> dict[str, Any]:
    """``offers`` with this session's offer replaced, then pruned."""
    out = dict(offers)
    out[_offer_key(scope, session)] = {"scope": scope, "session": session, "at": now,
                                       "ids": [str(i) for i in ids]}
    return prune_offers(out, now)


def get_offer(offers: dict[str, Any], scope: str, session: str, now: float) -> list[str]:
    """Offer ids shown in ``session`` for ``scope``; [] when absent, malformed or stale."""
    entry = prune_offers(offers, now).get(_offer_key(scope, session))
    return [str(i) for i in entry["ids"]] if entry else []


def carry_offer(offers: dict[str, Any], scope: str, parent: str, child: str, now: float) -> dict[str, Any]:
    """Copy the parent session's offer to ``child`` (a compressed or branched conversation).

    The copy keeps the parent's timestamp, so it expires when the original would. A newer
    offer already shown in ``child`` is kept.
    """
    live = prune_offers(offers, now)
    src = live.get(_offer_key(scope, parent))
    dst = live.get(_offer_key(scope, child))
    if not src or parent == child or (dst and float(dst["at"]) >= float(src["at"])):
        return live
    live[_offer_key(scope, child)] = {**src, "session": child}
    return prune_offers(live, now)


def _read_offers(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    offers = data.get("offers") if isinstance(data, dict) else None
    return offers if isinstance(offers, dict) else {}


@contextmanager
def _offer_lock(path: Path) -> Iterator[None]:
    """Exclusive lock on ``<path>.lock`` across processes. The data file itself is
    replaced atomically, so readers never need the lock."""
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is None and msvcrt is not None:  # pragma: no cover - Windows
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(fd)  # closing also releases a flock


def edit_offers(path: Path, change: Callable[[dict[str, Any]], dict[str, Any]], now: float) -> None:
    """Locked read-modify-write of the offer file, then an atomic replace."""
    with _offer_lock(path):
        data = {"offers": prune_offers(change(_read_offers(path)), now)}
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def save_offer(path: Path, scope: str, session: str, ids: list[str], now: float) -> None:
    """Record the offer ``session`` just showed for ``scope``. Other sessions' offers are kept."""
    edit_offers(path, lambda offers: put_offer(offers, scope, session, ids, now), now)


def load_offer(path: Path, scope: str, session: str, now: float) -> list[str]:
    """Offer ids shown in ``session`` for ``scope``; [] when absent, corrupt or stale."""
    return get_offer(_read_offers(path), scope, session, now)


def apply_reply(store: MemoryStore, offer_ids: list[str], actions: list[tuple[str, Any]],
                *, by: str = "chat-review", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply a parsed human reply to a pending offer. Returns kept/dropped/skipped rows.

    Numbers are 1-based positions in ``offer_ids``; ``all`` covers positions no clause
    names. A position named under both keep and drop, or a row no longer waiting, is
    skipped.
    """
    now = store.clock()
    named = {n for _, ts in actions if isinstance(ts, list) for n in ts}
    plan: dict[int, set[str]] = {}
    for action, ts in actions:
        targets = [n for n in range(1, len(offer_ids) + 1) if n not in named] if ts == "all" else ts
        for n in targets:
            plan.setdefault(int(n), set()).add(action)
    out: dict[str, Any] = {"kept": [], "dropped": [], "skipped": []}
    for n in sorted(plan):
        acts = plan[n]
        mem = store.get(offer_ids[n - 1]) if 1 <= n <= len(offer_ids) else None
        active = (mem is not None and not mem.deleted_at and not mem.superseded_by
                  and (mem.expires_at is None or mem.expires_at > now)
                  and P.needs_review(mem.kind, mem.meta, mem.source))
        row = {"n": n, "id": mem.id if mem else "", "content": mem.content if mem else ""}
        if len(acts) != 1 or not active:
            out["skipped"].append(row)
            continue
        try:
            if acts == {"keep"}:
                if meta:
                    store.update(mem.id, meta=meta)
                promote(store, mem.id, by=by)
                out["kept"].append(row)
            else:
                reject(store, mem.id)
                out["dropped"].append(row)
        except (KeyError, ValueError):
            out["skipped"].append(row)
    return out
