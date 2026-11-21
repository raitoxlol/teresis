"""The memory store: one SQLite file, safe for many concurrent agent processes."""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import embed as _embed
from . import text as T

log = logging.getLogger("mnemo")

SCHEMA_VERSION = 1
DAY = 86400.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    scope         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'fact',
    key           TEXT,
    content       TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '',
    meta          TEXT NOT NULL DEFAULT '{}',
    source        TEXT,
    importance    REAL NOT NULL DEFAULT 0.5,
    pinned        INTEGER NOT NULL DEFAULT 0,
    content_hash  TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    accessed_at   REAL,
    access_count  INTEGER NOT NULL DEFAULT 0,
    expires_at    REAL,
    superseded_by TEXT,
    superseded_at REAL,
    deleted_at    REAL
);
CREATE INDEX IF NOT EXISTS ix_mem_scope_active ON memories(scope) WHERE superseded_by IS NULL AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_mem_key ON memories(scope, key) WHERE key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_mem_hash ON memories(scope, content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, tags, key, content='memories', content_rowid='rowid',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_tri USING fts5(
    content, content='memories', content_rowid='rowid', tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tags, key) VALUES (new.rowid, new.content, new.tags, coalesce(new.key, ''));
    INSERT INTO memories_tri(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags, key) VALUES ('delete', old.rowid, old.content, old.tags, coalesce(old.key, ''));
    INSERT INTO memories_tri(memories_tri, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE OF content, tags, key ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags, key) VALUES ('delete', old.rowid, old.content, old.tags, coalesce(old.key, ''));
    INSERT INTO memories_tri(memories_tri, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content, tags, key) VALUES (new.rowid, new.content, new.tags, coalesce(new.key, ''));
    INSERT INTO memories_tri(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS vectors (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    model     TEXT NOT NULL,
    vec       BLOB NOT NULL
);
"""


def default_db_path() -> Path:
    if env := os.environ.get("MNEMO_DB"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / "mnemo" / "memory.db"


def scope_chain(scope: str) -> list[str]:
    """'project/mnemo/agent-a' -> ['project/mnemo/agent-a', 'project/mnemo', 'project', 'global']."""
    parts = [p for p in scope.strip("/").split("/") if p]
    chain = ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]
    if "global" not in chain:
        chain.append("global")
    return chain


@dataclass
class Memory:
    id: str
    scope: str
    kind: str
    content: str
    key: str | None = None
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    importance: float = 0.5
    pinned: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    accessed_at: float | None = None
    access_count: int = 0
    expires_at: float | None = None
    superseded_by: str | None = None
    superseded_at: float | None = None
    deleted_at: float | None = None
    score: float | None = None
    why: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Memory":
        d = dict(row)
        d.pop("content_hash", None)
        d.pop("rowid", None)
        d["tags"] = [t for t in (d.get("tags") or "").split() if t]
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["pinned"] = bool(d.get("pinned"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self, compact: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if compact:
            d = {k: v for k, v in d.items() if v not in (None, [], {}, False, 0) or k in ("importance",)}
        return d


@dataclass
class RememberResult:
    id: str
    status: str  # created | duplicate | superseded | refined
    replaced: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Weights:
    """Retrieval tuning. Defaults were picked on the bundled benchmark (see mnemo.bench)."""

    fts: float = 1.0
    trigram: float = 0.35
    vector: float = 1.0
    candidates: int = 60
    half_life_days: float = 30.0
    recency: float = 0.15  # max share of the score that recency can remove
    importance: float = 0.2  # importance scales score within [1 - w/2, 1 + w/2]
    access: float = 0.02
    pinned_boost: float = 1.05
    min_trigram_overlap: float = 0.5
    min_cosine: float = 0.2
    dup_jaccard: float = 0.9
    refine_containment: float = 0.9


class MemoryStore:
    def __init__(
        self,
        path: str | os.PathLike | None = None,
        *,
        embedder: _embed.Embedder | None | str = "env",
        weights: Weights | None = None,
        clock=time.time,
    ):
        self.path = Path(path) if path is not None else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = _embed.from_env() if embedder == "env" else embedder
        self.w = weights or Weights()
        self.clock = clock
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        c = self._conn
        if str(self.path) != ":memory:":
            c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        with self._lock:  # executescript manages its own transaction
            c.executescript(f"BEGIN IMMEDIATE;{SCHEMA}PRAGMA user_version={SCHEMA_VERSION};COMMIT;")

    # ------------------------------------------------------------------ infra
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _q(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _active_sql(self, alias: str = "m", as_of: float | None = None) -> tuple[str, list[Any]]:
        if as_of is None:
            now = self.clock()
            return (
                f"{alias}.superseded_by IS NULL AND {alias}.deleted_at IS NULL "
                f"AND ({alias}.expires_at IS NULL OR {alias}.expires_at > ?)",
                [now],
            )
        return (
            f"{alias}.created_at <= ? AND ({alias}.superseded_at IS NULL OR {alias}.superseded_at > ?) "
            f"AND ({alias}.deleted_at IS NULL OR {alias}.deleted_at > ?)",
            [as_of, as_of, as_of],
        )

    def _embed_one(self, content: str) -> bytes | None:
        if not self.embedder:
            return None
        try:
            return _embed.pack(self.embedder.embed([content])[0])
        except Exception as exc:  # never lose a memory because the embedder is down
            log.warning("embedding failed, storing without vector: %s", exc)
            return None

    # ------------------------------------------------------------------ write
    def remember(
        self,
        content: str,
        *,
        scope: str = "global",
        kind: str = "fact",
        key: str | None = None,
        tags: Iterable[str] = (),
        importance: float = 0.5,
        pinned: bool = False,
        ttl_days: float | None = None,
        source: str | None = None,
        meta: dict[str, Any] | None = None,
        replaces: str | None = None,
    ) -> RememberResult:
        """Store a memory. Dedupes exact/near repeats and supersedes stale values.

        * Same normalized content in scope -> reinforce the existing memory ("duplicate").
        * Same ``key`` in scope (e.g. ``user.editor``) -> old value is superseded, history kept.
        * Near-duplicate that the new text strictly refines -> old one superseded ("refined").
        * ``replaces=<id>`` -> explicit supersession.
        """
        content = (content or "").strip()
        if not content:
            raise ValueError("content must be non-empty")
        scope = scope.strip("/") or "global"
        importance = min(1.0, max(0.0, float(importance)))
        tag_str = " ".join(dict.fromkeys(t.strip().lower().replace(" ", "-") for t in tags if t.strip()))
        h = T.content_hash(content)
        now = self.clock()
        vec = self._embed_one(content)  # outside the write lock: may be slow
        active, active_params = self._active_sql("m")

        refined = False
        with self._write() as c:
            dup = c.execute(
                f"SELECT * FROM memories m WHERE scope=? AND content_hash=? AND {active}",
                [scope, h, *active_params],
            ).fetchone()
            if dup is None and not key and not replaces:
                near = self._near_duplicate(c, content, scope, kind, active, active_params)
                if near is not None and near[1] == "refine":
                    replaces, refined = near[0]["id"], True
                elif near is not None:
                    dup = near[0]
            if dup is not None and (not key or dup["key"] == key):
                c.execute(
                    "UPDATE memories SET access_count=access_count+1, updated_at=?, importance=max(importance, ?),"
                    " pinned=max(pinned, ?) WHERE id=?",
                    [now, importance, int(pinned), dup["id"]],
                )
                return RememberResult(dup["id"], "duplicate")

            new_id = uuid.uuid4().hex[:16]
            replaced: list[str] = []
            if key:
                rows = c.execute(
                    f"SELECT id FROM memories m WHERE scope=? AND key=? AND {active}", [scope, key, *active_params]
                ).fetchall()
                replaced += [r["id"] for r in rows]
            if replaces:
                row = c.execute("SELECT id FROM memories WHERE id=? AND superseded_by IS NULL", [replaces]).fetchone()
                if row is None:
                    raise KeyError(f"no active memory {replaces!r}")
                replaced.append(row["id"])
            replaced = list(dict.fromkeys(replaced))

            c.execute(
                "INSERT INTO memories (id, scope, kind, key, content, tags, meta, source, importance, pinned,"
                " content_hash, created_at, updated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    new_id, scope, kind, key, content, tag_str, json.dumps(meta or {}), source,
                    importance, int(pinned), h, now, now,
                    now + ttl_days * DAY if ttl_days else None,
                ],
            )
            for rid in replaced:
                c.execute(
                    "UPDATE memories SET superseded_by=?, superseded_at=? WHERE id=?", [new_id, now, rid]
                )
            if vec is not None:
                c.execute(
                    "INSERT INTO vectors(memory_id, model, vec) VALUES (?,?,?)", [new_id, self.embedder.name, vec]
                )
        status = "created" if not replaced else ("refined" if refined else "superseded")
        return RememberResult(new_id, status, replaced)

    def _near_duplicate(self, c, content, scope, kind, active, active_params):
        q = T.fts_query(content)
        if not q:
            return None
        rows = c.execute(
            f"SELECT m.* FROM memories_fts f JOIN memories m ON m.rowid=f.rowid "
            f"WHERE memories_fts MATCH ? AND m.scope=? AND m.kind=? AND {active} "
            f"ORDER BY bm25(memories_fts) LIMIT 5",
            [q, scope, kind, *active_params],
        ).fetchall()
        new_terms = T.term_set(content)
        for row in rows:
            old_terms = T.term_set(row["content"])
            if T.jaccard(new_terms, old_terms) >= self.w.dup_jaccard:
                return row, "dup"
            if (
                len(old_terms) >= 3
                and len(new_terms) > len(old_terms)
                and T.containment(new_terms, old_terms) >= self.w.refine_containment
            ):
                return row, "refine"
        return None

    def update(self, memory_id: str, content: str | None = None, **changes: Any) -> RememberResult:
        """Revise a memory. Content changes create a new version (history preserved)."""
        old = self.get(memory_id)
        if old is None or old.superseded_by or old.deleted_at:
            raise KeyError(f"no active memory {memory_id!r}")
        if content is None or content.strip() == old.content:
            sets, params = [], []
            for k in ("importance", "pinned", "kind", "source", "expires_at"):
                if k in changes:
                    sets.append(f"{k}=?")
                    params.append(int(changes[k]) if k == "pinned" else changes[k])
            if "tags" in changes:
                sets.append("tags=?")
                params.append(" ".join(changes["tags"]))
            if "meta" in changes:
                sets.append("meta=?")
                params.append(json.dumps({**old.meta, **changes["meta"]}))
            if sets:
                with self._write() as c:
                    c.execute(
                        f"UPDATE memories SET {', '.join(sets)}, updated_at=? WHERE id=?",
                        [*params, self.clock(), memory_id],
                    )
            return RememberResult(memory_id, "updated")
        res = self.remember(
            content,
            scope=old.scope,
            kind=changes.get("kind", old.kind),
            key=old.key,
            tags=changes.get("tags", old.tags),
            importance=changes.get("importance", old.importance),
            pinned=changes.get("pinned", old.pinned),
            source=changes.get("source", old.source),
            meta={**old.meta, **changes.get("meta", {})},
            replaces=None if old.key else memory_id,
        )
        return res

    def forget(self, memory_id: str | None = None, *, scope: str | None = None, key: str | None = None,
               hard: bool = False) -> int:
        """Soft-delete (default) or hard-delete by id, or by scope+key. Returns rows affected."""
        if memory_id:
            where, params = "id=?", [memory_id]
        elif scope and key:
            where, params = "scope=? AND key=?", [scope.strip("/"), key]
        else:
            raise ValueError("forget needs an id, or scope and key")
        with self._write() as c:
            if hard:
                return c.execute(f"DELETE FROM memories WHERE {where}", params).rowcount
            return c.execute(
                f"UPDATE memories SET deleted_at=? WHERE {where} AND deleted_at IS NULL", [self.clock(), *params]
            ).rowcount

    # ------------------------------------------------------------------ read
    def get(self, memory_id: str) -> Memory | None:
        rows = self._q("SELECT * FROM memories WHERE id=?", [memory_id])
        return Memory.from_row(rows[0]) if rows else None

    def history(self, memory_id: str | None = None, *, scope: str | None = None, key: str | None = None) -> list[Memory]:
        """All versions of a fact, oldest first."""
        if scope and key:
            rows = self._q("SELECT * FROM memories WHERE scope=? AND key=? ORDER BY created_at", [scope.strip("/"), key])
            return [Memory.from_row(r) for r in rows]
        if not memory_id:
            raise ValueError("history needs an id, or scope and key")
        chain: list[Memory] = []
        seen: set[str] = set()
        cur = self.get(memory_id)
        # walk back to the root
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.insert(0, cur)
            prev = self._q("SELECT * FROM memories WHERE superseded_by=? ORDER BY created_at DESC LIMIT 1", [cur.id])
            cur = Memory.from_row(prev[0]) if prev else None
        # walk forward
        cur = chain[-1] if chain else None
        while cur is not None and cur.superseded_by and cur.superseded_by not in seen:
            nxt = self.get(cur.superseded_by)
            if nxt is None:
                break
            seen.add(nxt.id)
            chain.append(nxt)
            cur = nxt
        return chain

    def _scope_filter(self, scope: str | Sequence[str] | None, inherit: bool) -> tuple[str, list[str]]:
        if scope is None:
            return "1", []
        scopes = [scope] if isinstance(scope, str) else list(scope)
        allowed: list[str] = []
        for s in scopes:
            allowed += scope_chain(s) if inherit else [s.strip("/") or "global"]
        allowed = list(dict.fromkeys(allowed))
        return f"m.scope IN ({','.join('?' * len(allowed))})", allowed

    def recall(
        self,
        query: str = "",
        *,
        scope: str | Sequence[str] | None = None,
        inherit: bool = True,
        kinds: Sequence[str] | None = None,
        exclude_kinds: Sequence[str] | None = None,
        tags: Sequence[str] | None = None,
        k: int = 8,
        budget_tokens: int | None = None,
        as_of: float | None = None,
        touch: bool = True,
        explain: bool = False,
    ) -> list[Memory]:
        """Hybrid retrieval: BM25 (Porter) + trigram fuzzy + optional vectors, fused by per-channel normalized scores,
        then re-weighted by recency, importance, reinforcement and pinning.

        ``scope='project/x'`` also searches parents ('project', 'global') unless ``inherit=False``.
        ``budget_tokens`` packs the best memories that fit, instead of a fixed ``k``.
        ``as_of`` (unix time) answers "what did I believe then?" including superseded versions.
        """
        w = self.w
        active, aparams = self._active_sql("m", as_of)
        scope_sql, sparams = self._scope_filter(scope, inherit)
        extra, eparams = "", []
        if kinds:
            extra += f" AND m.kind IN ({','.join('?' * len(kinds))})"
            eparams += list(kinds)
        if exclude_kinds:
            extra += f" AND m.kind NOT IN ({','.join('?' * len(exclude_kinds))})"
            eparams += list(exclude_kinds)
        for tag in tags or ():
            extra += " AND (' ' || m.tags || ' ') LIKE ?"
            eparams.append(f"% {tag.lower()} %")
        base_where = f"{active} AND {scope_sql}{extra}"
        base_params = [*aparams, *sparams, *eparams]
        n = max(w.candidates, k * 3)

        query = (query or "").strip()
        if not query:
            return self._browse(base_where, base_params, k, budget_tokens, touch)

        # Each channel yields {id: raw_score}; scores are normalized per channel (score / channel max)
        # and combined as a weighted mean, so a strong BM25 match is not flattened the way rank-only
        # fusion (RRF) flattens it.
        channels: dict[str, dict[str, float]] = {}
        rows_by_id: dict[str, sqlite3.Row] = {}

        if w.fts > 0 and (fq := T.fts_query(query)):
            rows = self._q(
                f"SELECT m.*, -bm25(memories_fts, 1.0, 0.6, 1.5) AS _s FROM memories_fts f "
                f"JOIN memories m ON m.rowid=f.rowid WHERE memories_fts MATCH ? AND {base_where} "
                f"ORDER BY _s DESC LIMIT ?",
                [fq, *base_params, n],
            )
            channels["fts"] = {r["id"]: max(0.0, r["_s"]) for r in rows}
            rows_by_id.update((r["id"], r) for r in rows)

        if w.trigram > 0 and (tq := T.trigram_query(query)):
            rows = self._q(
                f"SELECT m.* FROM memories_tri t JOIN memories m ON m.rowid=t.rowid "
                f"WHERE memories_tri MATCH ? AND {base_where} ORDER BY bm25(memories_tri) LIMIT ?",
                [tq, *base_params, n],
            )
            grams = {g.strip('"') for g in tq.split(" OR ")}
            tri: dict[str, float] = {}
            for r in rows:
                body = r["content"].casefold()
                overlap = sum(g in body for g in grams) / len(grams)
                if overlap >= w.min_trigram_overlap:
                    tri[r["id"]] = overlap
                    rows_by_id.setdefault(r["id"], r)
            channels["trigram"] = tri

        if w.vector > 0 and self.embedder:
            try:
                qv = self.embedder.embed([query])[0]
                vrows = self._q(
                    f"SELECT v.memory_id, v.vec FROM vectors v JOIN memories m ON m.id=v.memory_id "
                    f"WHERE v.model=? AND {base_where}",
                    [self.embedder.name, *base_params],
                )
                hits = _embed.top_k(qv, [(r[0], r[1]) for r in vrows], n)
                channels["vector"] = {mid: max(0.0, sim) for mid, sim in hits if sim >= w.min_cosine}
                missing = [mid for mid in channels["vector"] if mid not in rows_by_id]
                if missing:
                    for r in self._q(
                        f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(missing))})", missing
                    ):
                        rows_by_id[r["id"]] = r
            except Exception as exc:
                log.warning("vector channel unavailable: %s", exc)

        weights = {"fts": w.fts, "trigram": w.trigram, "vector": w.vector}
        live = {ch: s for ch, s in channels.items() if s}
        if not live:
            return []
        total_w = sum(weights[ch] for ch in live)
        parts: dict[str, dict[str, float]] = {}
        for ch, scores in live.items():
            top = max(scores.values()) or 1.0
            for mid, s in scores.items():
                parts.setdefault(mid, {})[ch] = s / top
        now = as_of or self.clock()

        scored: list[Memory] = []
        for mid, p in parts.items():
            mem = Memory.from_row(rows_by_id[mid])
            relevance = sum(weights[ch] * v for ch, v in p.items()) / total_w
            age_days = max(0.0, now - (mem.updated_at or mem.created_at)) / DAY
            recency = math.exp(-math.log(2) * age_days / w.half_life_days)
            score = (
                relevance
                * ((1 - w.recency) + w.recency * recency)
                * ((1 - w.importance / 2) + w.importance * mem.importance)
                * (1 + w.access * math.log1p(mem.access_count))
                * (w.pinned_boost if mem.pinned else 1.0)
            )
            mem.score = round(score, 6)
            if explain:
                mem.why = {"channels": {c: round(v, 3) for c, v in p.items()},
                           "relevance": round(relevance, 4), "recency": round(recency, 4)}
            scored.append(mem)
        scored.sort(key=lambda m: m.score or 0, reverse=True)
        out = self._pack(scored, k, budget_tokens)
        if touch and as_of is None:
            self._touch([m.id for m in out])
        return out

    def _browse(self, where, params, k, budget_tokens, touch) -> list[Memory]:
        rows = self._q(f"SELECT * FROM memories m WHERE {where} ORDER BY pinned DESC, importance DESC, "
                       f"updated_at DESC LIMIT ?", [*params, max(k, 200 if budget_tokens else k)])
        out = self._pack([Memory.from_row(r) for r in rows], k, budget_tokens)
        if touch:
            self._touch([m.id for m in out])
        return out

    @staticmethod
    def _pack(mems: list[Memory], k: int, budget_tokens: int | None) -> list[Memory]:
        if not budget_tokens:
            return mems[:k]
        out, used = [], 0
        for m in mems:
            cost = T.estimate_tokens(m.content) + 8
            if used + cost > budget_tokens:
                continue
            out.append(m)
            used += cost
        return out

    def _touch(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            with self._write() as c:
                c.executemany(
                    "UPDATE memories SET access_count=access_count+1, accessed_at=? WHERE id=?",
                    [(self.clock(), i) for i in ids],
                )
        except sqlite3.OperationalError as exc:  # reads must not fail because a writer is busy
            log.debug("touch skipped: %s", exc)

    def context(self, scope: str | Sequence[str] = "global", *, query: str = "", budget_tokens: int = 1200,
                exclude_kinds: Sequence[str] = ("episode",)) -> str:
        """A ready-to-inject prompt block: pinned + relevant + important memories within a token budget."""
        active, aparams = self._active_sql("m")
        scope_sql, sparams = self._scope_filter(scope, True)
        pinned = self._q(
            f"SELECT * FROM memories m WHERE m.pinned=1 AND {active} AND {scope_sql} ORDER BY importance DESC",
            [*aparams, *sparams],
        )
        chosen = {r["id"]: Memory.from_row(r) for r in pinned}

        def fill(mems: list[Memory]) -> None:
            used = sum(T.estimate_tokens(m.content) + 8 for m in chosen.values())
            for m in mems:
                cost = T.estimate_tokens(m.content) + 8
                if m.id not in chosen and used + cost <= budget_tokens:
                    chosen[m.id] = m
                    used += cost

        if query:  # task-relevant first, then important/recent background
            fill(self.recall(query, scope=scope, k=50, exclude_kinds=exclude_kinds))
        fill(self.recall("", scope=scope, k=200, exclude_kinds=exclude_kinds))
        if not chosen:
            return ""
        label_scope = scope if isinstance(scope, str) else ",".join(scope)
        lines = [f"<memory scope=\"{label_scope}\">"]
        for m in chosen.values():
            label = m.kind + (f" {m.key}" if m.key else "")
            lines.append(f"- [{label}] {m.content}")
        lines.append("</memory>")
        return "\n".join(lines)

    def find(self, content: str, *, scope: str | None = None) -> Memory | None:
        """The active memory whose normalized content equals ``content`` (newest first)."""
        active, aparams = self._active_sql("m")
        sql = f"SELECT * FROM memories m WHERE content_hash=? AND {active}"
        params: list[Any] = [T.content_hash(content), *aparams]
        if scope:
            sql += " AND scope=?"
            params.append(scope.strip("/"))
        rows = self._q(sql + " ORDER BY updated_at DESC LIMIT 1", params)
        return Memory.from_row(rows[0]) if rows else None

    def feedback(self, memory_id: str, helpful: bool, *, step: float = 0.1) -> dict[str, Any]:
        """Agent rates a recalled memory: helpful ones rise, unhelpful ones sink (and are flagged at <= 0.1)."""
        delta = step if helpful else -step
        with self._write() as c:
            n = c.execute(
                "UPDATE memories SET importance=min(1.0, max(0.0, importance + ?)), updated_at=updated_at WHERE id=?",
                [delta, memory_id],
            ).rowcount
        if not n:
            raise KeyError(f"no memory {memory_id!r}")
        m = self.get(memory_id)
        return {"id": memory_id, "importance": round(m.importance, 3), "flagged": m.importance <= 0.1}

    def conflicts(self, scope: str | Sequence[str] | None = None, *, limit: int = 20,
                  low: float = 0.3, high: float = 0.9) -> list[dict[str, Any]]:
        """Pairs of active memories that talk about the same thing but differ: likely contradictions or
        stale facts to resolve with a key, update, or forget. Lexical overlap between ``low`` and ``high``."""
        active, aparams = self._active_sql("m")
        scope_sql, sparams = self._scope_filter(scope, False)
        rows = self._q(
            f"SELECT * FROM memories m WHERE {active} AND {scope_sql} AND m.kind != 'episode' "
            f"ORDER BY updated_at DESC LIMIT 2000",
            [*aparams, *sparams],
        )
        mems = [(Memory.from_row(r), T.term_set(r["content"])) for r in rows]
        out = []
        for i, (a, ta) in enumerate(mems):
            for b, tb in mems[i + 1:]:
                if a.scope != b.scope or (a.key and a.key == b.key):
                    continue
                j = T.jaccard(ta, tb)
                if low <= j < high and len(ta & tb) >= 2:
                    out.append({"similarity": round(j, 3), "newer": a.to_dict(compact=True), "older": b.to_dict(compact=True)})
        out.sort(key=lambda d: d["similarity"], reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------ admin
    def stats(self) -> dict[str, Any]:
        now = self.clock()
        row = self._q(
            "SELECT count(*) total,"
            " sum(superseded_by IS NULL AND deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)) active,"
            " sum(superseded_by IS NOT NULL) superseded, sum(deleted_at IS NOT NULL) deleted FROM memories",
            [now],
        )[0]
        scopes = self._q(
            "SELECT scope, count(*) n FROM memories WHERE superseded_by IS NULL AND deleted_at IS NULL "
            "GROUP BY scope ORDER BY n DESC LIMIT 50"
        )
        vecs = self._q("SELECT count(*) FROM vectors")[0][0]
        return {
            "path": str(self.path),
            **{k: int(row[k] or 0) for k in ("total", "active", "superseded", "deleted")},
            "vectors": vecs,
            "embedder": self.embedder.name if self.embedder else None,
            "scopes": {r["scope"]: r["n"] for r in scopes},
        }

    def maintain(self, *, purge_deleted_days: float = 30.0, vacuum: bool = False) -> dict[str, int]:
        """Hard-delete expired and long-soft-deleted memories; optimize the indexes."""
        now = self.clock()
        with self._write() as c:
            expired = c.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", [now]).rowcount
            purged = c.execute(
                "DELETE FROM memories WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                [now - purge_deleted_days * DAY],
            ).rowcount
            c.execute("INSERT INTO memories_fts(memories_fts) VALUES ('optimize')")
            c.execute("INSERT INTO memories_tri(memories_tri) VALUES ('optimize')")
        if vacuum:
            with self._lock:
                self._conn.execute("VACUUM")
        return {"expired": expired, "purged": purged}

    def embed_missing(self, batch: int = 32) -> int:
        """Backfill vectors (after enabling an embedder or an outage)."""
        if not self.embedder:
            raise RuntimeError("no embedder configured (set MNEMO_EMBED)")
        done = 0
        while True:
            rows = self._q(
                "SELECT m.id, m.content FROM memories m LEFT JOIN vectors v ON v.memory_id=m.id AND v.model=? "
                "WHERE v.memory_id IS NULL AND m.deleted_at IS NULL LIMIT ?",
                [self.embedder.name, batch],
            )
            if not rows:
                return done
            vecs = self.embedder.embed([r["content"] for r in rows])
            with self._write() as c:
                c.executemany(
                    "INSERT OR REPLACE INTO vectors(memory_id, model, vec) VALUES (?,?,?)",
                    [(r["id"], self.embedder.name, _embed.pack(v)) for r, v in zip(rows, vecs)],
                )
            done += len(rows)

    def export(self) -> Iterator[dict[str, Any]]:
        for r in self._q("SELECT * FROM memories ORDER BY created_at"):
            yield Memory.from_row(r).to_dict()

    def import_(self, records: Iterable[dict[str, Any]]) -> int:
        """Restore an export verbatim (ids, history and timestamps preserved)."""
        n = 0
        with self._write() as c:
            for d in records:
                tags = d.get("tags") or []
                c.execute(
                    "INSERT OR IGNORE INTO memories (id, scope, kind, key, content, tags, meta, source, importance,"
                    " pinned, content_hash, created_at, updated_at, accessed_at, access_count, expires_at,"
                    " superseded_by, superseded_at, deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        d["id"], d["scope"], d.get("kind", "fact"), d.get("key"), d["content"],
                        " ".join(tags) if isinstance(tags, list) else tags, json.dumps(d.get("meta") or {}),
                        d.get("source"), d.get("importance", 0.5), int(bool(d.get("pinned"))),
                        T.content_hash(d["content"]), d["created_at"], d.get("updated_at", d["created_at"]),
                        d.get("accessed_at"), d.get("access_count", 0), d.get("expires_at"),
                        d.get("superseded_by"), d.get("superseded_at"), d.get("deleted_at"),
                    ],
                )
                n += c.execute("SELECT changes()").fetchone()[0]
        return n
