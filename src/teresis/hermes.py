"""Hermes Agent memory provider (``memory.provider: teresis``).

Install into a Hermes home with ``teresis hermes install`` (copies this package to
``$HERMES_HOME/plugins/teresis/``), or ``pip install`` teresis into the Hermes venv (entry point
``hermes_agent.memory_providers``). Config lives in ``config.yaml`` under ``plugins.teresis``.

Behavior, per Hermes' MemoryProvider contract:
- prefetch: hybrid recall over the agent scope + ``user`` scope, injected before each turn.
- sync_turn: stores the turn as a short-lived ``episode`` and extracts durable preferences/decisions.
- on_memory_write: mirrors Hermes' built-in memory tool (add / replace / remove) into teresis.
- on_pre_compress / on_delegation: saves what would otherwise be lost to compression or a subagent.
- Subagent, cron and flush contexts never write (they only read).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import sqlite3
import threading
from contextvars import copy_context
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlsplit

from . import embed as _embed
from . import extract as _extract
from . import provenance as _prov
from . import review as _review
from . import secrets as _secrets
from . import threats as _threats
from .mcp import TOOLS, Server
from .store import MemoryStore, default_db_path
from .text import containment, term_set, tokens

log = logging.getLogger("teresis.hermes")

try:  # running inside Hermes
    from agent.memory_provider import MemoryProvider as _Base
    from agent.memory_provider import RecallStatus as _RecallStatus
except Exception:  # pragma: no cover - lets the module import (and be tested) without Hermes
    _Base = object  # type: ignore[assignment,misc]
    _RecallStatus = None

try:
    from agent.memory_provider import is_trivial_prompt as _is_trivial
except Exception:
    def _is_trivial(text: Optional[str]) -> bool:
        t = (text or "").strip().lower().strip("!?. ")
        return not t or t.startswith("/") or t in {"ok", "okay", "yes", "no", "thanks", "thank you", "hi", "hey",
                                                    "continue", "go ahead", "do it", "done", "next", "lgtm", "k"}

PLUGIN_KEY = "teresis"
_NO_WRITE_CONTEXTS = {"subagent", "cron", "flush"}
_WRITE_TOOLS = {"memory_remember", "memory_update", "memory_forget", "memory_feedback"}

DEFAULTS: Dict[str, Any] = {
    "db_path": "",             # empty: $TERESIS_DB, else ~/.local/share/teresis/memory.db (shared with MCP agents)
    "scope": "",               # empty: hermes/<agent_identity>
    "extra_scopes": "user",    # comma-separated scopes also searched on recall
    "prefetch_k": 6,
    "prefetch_budget_tokens": 700,
    # Lexical ranking normalizes the best hit to ~1.0, so a shared weak word
    # ("want", "like") looks relevant. Prefetch also requires a distinctive
    # term overlap; this floor drops the leftovers. Tool recall stays open.
    "prefetch_min_score": 0.45,
    "capture_turns": True,
    "episode_ttl_days": 30,
    "auto_extract": True,
    # Trust gate. Extraction needs a turn that is provably typed by a person.
    "system_authors": "",          # extra comma-separated author names/ids treated as non-human
    "untrusted_platforms": "",     # extra platforms whose user-role turns are never human
    "interactive_platforms": "",   # extra platforms where a turn without turn_author is a person
    # Compaction summaries are model-written. Never extract from them unless explicitly opted in,
    # and even then only into the candidate quarantine.
    "extract_on_pre_compress": False,
    "pre_compress_checkpoint": True,   # metadata-only episode, never a preference/decision/procedure row
    "candidate_ttl_days": 14,
    "embed_timeout": 120,
    "embed_auth": "profile",
    "rerank": "",            # "fastembed" enables the local ONNX cross-encoder; empty/none = off
    "rerank_model": "Xenova/ms-marco-MiniLM-L-6-v2",
}


def _profile_db_path(configured: str, home: str | os.PathLike) -> Path:
    raw = configured.strip()
    if not raw:
        return default_db_path()
    path = Path(raw.replace("${HERMES_HOME}", os.fspath(home)).replace("$HERMES_HOME", os.fspath(home)))
    try:
        return path.expanduser()
    except RuntimeError as exc:
        raise ValueError("cannot expand the user home in Hermes Teresis db_path") from exc


def _load_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly

        return dict(cfg_get(load_config_readonly(), "plugins", PLUGIN_KEY, default={}) or {})
    except Exception:
        return {}


def _truthy(v: Any) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "on"}


def _hermes_embedding_key() -> str | None:
    from agent.secret_scope import get_secret

    return get_secret("TERESIS_EMBED_KEY") or None


class _ProfileEmbedder:
    def __init__(self, delegate: _embed.Embedder, hermes_home: str):
        self._delegate = delegate
        self._home = Path(hermes_home).resolve()
        self.name = delegate.name

    def embed(self, texts):
        from hermes_constants import get_hermes_home

        if get_hermes_home().resolve() != self._home:
            raise RuntimeError("Teresis embedding request is outside its owning Hermes profile")
        # Automatic and explicit tool recall both use the store. Protect both egress paths.
        return self._delegate.embed([_secrets.redact_secrets(s)[0] for s in texts])


class _CaptureIndexer:
    def __init__(self, store: MemoryStore, embedder: _embed.Embedder, hermes_home: str):
        self.owner = hashlib.sha256(os.fsencode(Path(hermes_home).resolve())).hexdigest()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        context = copy_context()
        self.thread = threading.Thread(target=context.run, args=(self._run, store, embedder),
                                       name="teresis-index", daemon=True)
        self.thread.start()
        self.wake.set()  # Resume unfinished work from an earlier session.

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()

    def _run(self, store: MemoryStore, embedder: _embed.Embedder) -> None:
        while True:
            self.wake.wait()
            self.wake.clear()
            after = ""
            try:
                while not self.stopped.is_set():
                    rows = store.pending_embeddings(self.owner, after=after)
                    if not rows:
                        break
                    if not self._index_batch(store, embedder, rows):
                        # A wholly rejected batch may indicate a misconfigured service.
                        break
                    after = rows[-1][0]
            except Exception:
                if not self.stopped.is_set():
                    log.warning("teresis capture indexing failed; will retry on capture or restart")
            if self.stopped.is_set():
                return

    def _index_batch(self, store: MemoryStore, embedder: _embed.Embedder,
                     rows: list[tuple[str, str]]) -> bool:
        if self.stopped.is_set():
            return False
        try:
            vectors = _embed.pack_batch(embedder.embed([content for _, content in rows]), len(rows))
        except HTTPError as exc:
            exc.close()
            if exc.code not in (400, 413, 422):
                raise
        except _embed.InvalidEmbeddingBatch as exc:
            if not exc.has_vectors and len(rows) > 1:
                raise
        else:
            if not self.stopped.is_set():
                store.complete_embeddings(self.owner, embedder.name,
                                          [(mid, vec) for (mid, _), vec in zip(rows, vectors)])
            return True

        # Isolate input rejections. Transport and service failures stop the pass.
        if len(rows) == 1:
            log.warning("teresis capture embedding rejected; will retry on capture or restart")
            return False
        middle = len(rows) // 2
        indexed_left = self._index_batch(store, embedder, rows[:middle])
        indexed_right = self._index_batch(store, embedder, rows[middle:])
        return indexed_left or indexed_right


def _profile_embedder(config: Dict[str, Any], hermes_home: str) -> _embed.Embedder | None:
    kind = str(config.get("embed") or "").strip().lower()
    if kind in ("", "none"):
        return None
    model = str(config.get("embed_model") or "").strip()
    if not model or kind not in {"ollama", "openai"}:
        raise ValueError("set a supported Hermes embed backend and an embed_model")
    url = str(config.get("embed_url") or "").strip()
    if kind == "ollama" and not url:
        url = "http://localhost:11434"
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("set an HTTP(S) embedding base URL without credentials, query or fragment")
    timeout = float(config["embed_timeout"])
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("embed_timeout must be positive and finite")
    if kind == "ollama":
        engine = _embed.OllamaEmbedder(model, url, timeout=timeout, no_redirect=True)
    else:
        auth = str(config["embed_auth"]).strip().lower()
        if auth not in {"profile", "none"}:
            raise ValueError("embed_auth must be profile or none")
        engine = _embed.OpenAIEmbedder(model, url, key_lookup=_hermes_embedding_key if auth == "profile" else None,
                                       timeout=timeout, no_redirect=True)
    return _ProfileEmbedder(engine, hermes_home)


def _trim(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# Unstemmed tokens that are too common to justify injecting a memory on their own.
# Inflected forms are included so "likes" does not sneak past "like".
_PREFETCH_WEAK = frozenset(
    t + suffix
    for t in """like want need order get make use have take give please help really just more some also
    thing things stuff good bad new one user call write read file run set put see look time day
    way work said first later check about would could should done yeah yes okay thanks something
    anything remotely table place can""".split()
    for suffix in ("", "s", "es", "ed", "ing")
)


def _term_covers(query_tok: str, memory_tok: str) -> bool:
    """True when the memory token is the query token or a light inflection of it.

    Query "rolls" does not cover memory "roll". That direction is how lexical
    search pulled "roll back" into a tuna-rolls turn.
    """
    if query_tok == memory_tok:
        return True
    if len(query_tok) < 4 or not memory_tok.startswith(query_tok):
        return False
    return memory_tok[len(query_tok):] in {"s", "es", "ed", "ing", "d"}


def _prefetch_relevant(query: str, content: str, *, floor: float, score: float | None) -> bool:
    """Prefetch injection gate. Tool recall does not use this."""
    if (score or 0) < floor:
        return False
    distinctive = [t for t in tokens(query) if len(t) >= 4 and t not in _PREFETCH_WEAK]
    if not distinctive:
        return False
    memory_toks = [t for t in tokens(content) if t not in _PREFETCH_WEAK]
    return any(_term_covers(q, m) for q in distinctive for m in memory_toks)


def _min_score(config: Dict[str, Any], default: float = 0.45) -> float:
    try:
        return float(config.get("prefetch_min_score", default))
    except (TypeError, ValueError):
        return default


def _openai_schemas() -> List[Dict[str, Any]]:
    return [{"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]} for t in TOOLS]


class TeresisMemoryProvider(_Base):  # type: ignore[misc,valid-type]
    """Local hybrid-search memory shared with every other teresis client on the machine."""

    pre_compress_checkpoint_api_version = 1

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = {**DEFAULTS, **(config if config is not None else _load_config())}
        self._store: Optional[MemoryStore] = None
        self._capture_indexer: Optional[_CaptureIndexer] = None
        self._server: Optional[Server] = None
        self._scope = "hermes/default"
        self._read_scopes: List[str] = [self._scope]
        self._write_enabled = True
        self._session_id = ""
        self._platform = ""
        self._last_count: Optional[int] = None

    # -- identity ----------------------------------------------------------
    @property
    def name(self) -> str:
        return "teresis"

    def is_available(self) -> bool:
        try:
            c = sqlite3.connect(":memory:")
            c.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
            c.close()
            return True
        except sqlite3.Error:
            return False

    def unavailable_reason(self) -> str:
        return "teresis needs SQLite 3.34+ with FTS5 (trigram tokenizer) in this Python."

    # -- lifecycle ---------------------------------------------------------
    def _db_path(self, hermes_home: str) -> str:
        return str(_profile_db_path(str(self._config.get("db_path") or ""), hermes_home))

    def initialize(self, session_id: str, **kwargs) -> None:
        hermes_home = str(kwargs.get("hermes_home") or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        identity = str(kwargs.get("agent_identity") or "default").strip() or "default"
        self._scope = (str(self._config.get("scope") or "").strip("/ ") or f"hermes/{identity}")
        extra = [s.strip("/ ") for s in str(self._config.get("extra_scopes") or "").split(",") if s.strip("/ ")]
        self._read_scopes = list(dict.fromkeys([self._scope, *extra]))
        self._write_enabled = kwargs.get("agent_context", "primary") not in _NO_WRITE_CONTEXTS
        self._session_id = session_id
        self._platform = kwargs.get("platform", "")
        try:
            embedder = _profile_embedder(self._config, hermes_home)
        except (TypeError, ValueError):
            # Keep lexical memory available without logging URLs or credential-shaped config.
            log.warning("teresis embedding settings are invalid; continuing with lexical memory")
            embedder = None
        try:  # the reranker is optional: a missing fastembed install must not break the provider
            reranker = _embed.reranker_from_settings(str(self._config.get("rerank") or ""),
                                                     str(self._config.get("rerank_model") or ""))
        except Exception as exc:
            log.warning("teresis reranker unavailable (%s); continuing without rerank", exc)
            reranker = None
        self._store = MemoryStore(self._db_path(hermes_home), embedder=embedder, reranker=reranker)
        self._server = Server(self._store, default_scope=self._read_scopes)
        if embedder and self._write_enabled:
            self._capture_indexer = _CaptureIndexer(self._store, embedder, hermes_home)

    def shutdown(self) -> None:
        if self._capture_indexer is not None:
            self._capture_indexer.stop()
            self._capture_indexer = None
        if self._store is not None:
            try:
                self._store.close()
            except Exception as exc:
                log.debug("teresis close failed: %s", exc)
        self._store = self._server = None

    def on_session_switch(self, new_session_id: str, *, parent_session_id: str = "", reset: bool = False,
                          rewound: bool = False, **kwargs) -> None:
        self._session_id = str(new_session_id or "").strip() or self._session_id

    # -- prompt ------------------------------------------------------------
    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        return (
            "# Long-term memory (teresis)\n"
            f"Relevant memories are injected before each turn. Your scope: `{self._scope}`; "
            f"recall also searches {', '.join(f'`{s}`' for s in self._read_scopes[1:]) or 'nothing else'} and `global`.\n"
            "- Save durable facts, preferences, decisions and lessons with memory_remember (one fact per call). "
            "Use scope `user` for facts about the user.\n"
            "- For facts that change, pass a stable `key` (e.g. `user.editor`): the new value replaces the old.\n"
            "- Search deeper with memory_recall; rate memories you used with memory_feedback.\n"
            "- Never store secrets, credentials or tokens."
        )

    def _format(self, mems, title: str) -> str:
        lines = [f"## {title}"]
        for m in mems:
            label = m.kind + (f" {m.key}" if m.key else "")
            lines.append(f"- [{label}] {_trim(m.content, 1200)} (id {m.id})")
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._last_count = 0
        if not self._store or _is_trivial(query):
            return ""
        try:
            k = int(self._config.get("prefetch_k", 6))
            budget = int(self._config.get("prefetch_budget_tokens", 700))
            query = _secrets.redact_secrets(query)[0]  # keep raw secrets out of remote embedder calls
            facts = self._store.recall(query, scope=self._read_scopes, k=k, budget_tokens=budget,
                                       exclude_kinds=["episode", _prov.CANDIDATE_KIND])
            floor = _min_score(self._config)
            facts = [m for m in facts if _prefetch_relevant(query, m.content, floor=floor, score=m.score)
                     and _prov.injectable(m.kind, m.content, m.meta, m.source)[0]]
            blocks = [self._format(facts, "Long-term memory (teresis)")] if facts else []
            if _truthy(self._config.get("capture_turns", True)):
                eps = self._store.recall(query, scope=[self._scope], inherit=False, kinds=["episode"], k=2)
                known = [" ".join(m.content.casefold().split()) for m in facts]
                eps = [m for m in eps if _prov.injectable(m.kind, m.content, m.meta, m.source)[0]
                       and _prefetch_relevant(query, m.content, floor=max(0.3, floor), score=m.score)
                       and not any(k and k.removeprefix("user: ") in " ".join(m.content.casefold().split()) for k in known)]
                if eps:
                    blocks.append(self._format(eps, "Related past conversation"))
                facts += eps
            self._last_count = len(facts)
            return "\n\n".join(blocks)
        except Exception as exc:
            log.debug("teresis prefetch failed: %s", exc)
            return ""

    def recall_status(self):
        if not self._last_count or _RecallStatus is None:
            return None
        return _RecallStatus(provider_label="teresis", count=self._last_count)

    _POLARITY = {"never", "always", "not", "no", "dont", "don't", "stop", "avoid", "without"}

    def _near_dup(self, content: str, *, lexical_only: bool = False):
        """Compare against existing non-episode memories about the same subject.

        Returns ("dup", m) when an existing memory says the same thing in different words,
        ("supersede", m) when it is the same statement with a different number (a changed port or
        version: the old value is revised, history kept), else None. Opposite polarity
        ("never" vs "always") is always a new fact.
        """
        strip = lambda t: t.replace("-", "").removeprefix("User: ")
        mine = term_set(strip(content))
        if len(mine) < 3:
            return None
        try:
            cands = self._store.recall(content, scope=self._read_scopes, k=5,
                                       exclude_kinds=["episode", _prov.CANDIDATE_KIND],
                                       lexical_only=lexical_only)
        except Exception:
            return None
        for m in cands:
            theirs = term_set(strip(m.content))
            words = lambda ts: {t for t in ts if not any(ch.isdigit() for ch in t)}
            if containment(words(mine), words(theirs)) < 0.8:
                continue
            diff = mine ^ theirs
            if any(t in self._POLARITY for t in diff):
                continue
            num_mine = {t for t in mine if any(ch.isdigit() for ch in t)}
            num_theirs = {t for t in theirs if any(ch.isdigit() for ch in t)}
            if num_mine == num_theirs:
                return ("dup", m)
            if num_mine and num_theirs:
                return ("supersede", m)
        return None

    def _write_or_skip(self, content: str, *, automatic: bool = False, **kw) -> bool:
        """remember() unless it duplicates an existing memory; revise in place if it supersedes one."""
        content, _ = _secrets.redact_secrets(content)  # belt: store.remember scrubs too
        if not content.strip():
            return False
        hit = self._near_dup(content, lexical_only=automatic)
        if hit and hit[0] == "dup":
            return False
        indexer = self._capture_indexer if automatic else None
        owner = indexer.owner if indexer else None
        if hit:
            extra = {"meta": kw["meta"]} if kw.get("meta") else {}
            self._store.update(hit[1].id, content, embedding_owner=owner, **extra)
        else:
            self._store.remember(content, embedding_owner=owner, **kw)
        if indexer:
            indexer.wake.set()
        return True

    # -- writes ------------------------------------------------------------
    def _remember_episode(self, content: str, **kw) -> None:
        indexer = self._capture_indexer
        self._store.remember(content, scope=self._scope, kind="episode",
                             embedding_owner=indexer.owner if indexer else None, **kw)
        if indexer:
            indexer.wake.set()

    def _turn_is_human(self, turn_author: Optional[Dict[str, Any]], text: str,
                       turn_origin: Optional[str] = None) -> tuple[bool, str]:
        """Allowlist gate: True only when the turn is provably typed by a person."""
        if turn_origin:  # explicit label from the host (not sent by Hermes yet) beats guessing
            human, reason = str(turn_origin).strip().lower() == "human", f"origin:{turn_origin}"
        else:
            human, reason = _prov.turn_trust(
                turn_author, self._platform,
                system_authors=self._config.get("system_authors"),
                untrusted_platforms=self._config.get("untrusted_platforms"),
                interactive_platforms=self._config.get("interactive_platforms"),
            )
        if human and (_prov.wrapper_shaped(text) or _prov.structural_injected(text)):
            return False, "wrapper-shaped"
        return human, reason

    def _remember_auto(self, content: str, **kw) -> None:
        indexer = self._capture_indexer
        self._store.remember(content, embedding_owner=indexer.owner if indexer else None, **kw)
        if indexer:
            indexer.wake.set()

    def _store_explicit(self, c: "_extract.Candidate", scope: str, source: str) -> bool:
        """A person said it with a strong marker: store (or promote) it as a standing memory."""
        sid = self._session_id
        meta = {"session_id": sid, "origin": _prov.USER_TYPED, "trust": "human",
                "promoted_by": "explicit-marker"}
        cand = _review.find_candidate(self._store, c.content, scope)
        if cand is not None:
            self._store.update(cand.id, meta={"origin": _prov.USER_TYPED, "trust": "human"})
            _review.promote(self._store, cand.id, by="explicit-marker")
            return True
        return self._write_or_skip(c.content, automatic=True, scope=scope, kind=c.kind,
                                   importance=c.importance, source=source, meta=meta)

    def _store_candidate(self, c: "_extract.Candidate", scope: str, source: str, *, human: bool) -> bool:
        """Quarantine: stored as kind ``candidate``, never injected, expires unless promoted."""
        now = self._store.clock()
        sid = self._session_id
        hit = self._near_dup(c.content, lexical_only=True)
        if hit and hit[0] == "dup":
            return False  # a trusted row already says this
        existing = _review.find_candidate(self._store, c.content, scope)
        if existing is not None:
            if not human:
                return False
            meta = _review.add_sighting(existing.meta, sid, now)
            self._store.update(existing.id, meta=meta)
            if _review.corroborated(meta):
                _review.promote(self._store, existing.id, by="corroboration")
            return True
        meta = {
            "session_id": sid, "origin": _prov.AUTO_CANDIDATE, "trust": "untrusted",
            "candidate_kind": c.kind, "candidate_importance": c.importance,
            "seen": [{"s": sid or "unknown", "d": _review.day_of(now)}] if human else [],
        }
        if hit:  # same statement, different number: promotion revises the old row
            meta["supersedes"] = hit[1].id
        ttl = float(self._config.get("candidate_ttl_days", _prov.DEFAULT_CANDIDATE_TTL_DAYS)) or None
        self._remember_auto(c.content, scope=scope, kind=_prov.CANDIDATE_KIND,
                            importance=_prov.CANDIDATE_IMPORTANCE, tags=["candidate"], ttl_days=ttl,
                            source=source, meta=meta)
        return True

    def _save_extracted(self, text: str, source: str, *, human: bool = False) -> List[str]:
        """Extract claims. Explicitly marked human statements are stored; everything else is quarantined.

        ``human`` must come from the trust gate. Without it nothing is promoted by marker and
        nothing counts toward corroboration.
        """
        saved = []
        for c in _extract.extract(text):
            if _threats.first_threat(c.content):
                continue  # an instruction aimed at the agent is not a fact about the user
            scope = "user" if c.kind == "preference" else self._scope
            try:
                ok = (self._store_explicit(c, scope, source) if (human and c.explicit)
                      else self._store_candidate(c, scope, source, human=human))
                if ok:
                    saved.append(c.content)
            except Exception as exc:
                log.debug("teresis extract save failed: %s", exc)
        return saved

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "",
                  messages: Optional[List[Dict[str, Any]]] = None, turn_author: Optional[Dict[str, Any]] = None,
                  turn_origin: Optional[str] = None) -> None:
        if not (self._store and self._write_enabled):
            return
        user_content = user_content if isinstance(user_content, str) else str(user_content or "")
        assistant_content = assistant_content if isinstance(assistant_content, str) else str(assistant_content or "")
        user_content = _secrets.redact_secrets(user_content)[0]
        assistant_content = _secrets.redact_secrets(assistant_content)[0]
        authored = _extract.user_authored_text(user_content)
        if not authored.strip():
            return
        human, reason = self._turn_is_human(turn_author, authored, turn_origin)
        try:
            if _truthy(self._config.get("capture_turns", True)) and not _is_trivial(authored):
                who = (turn_author or {}).get("name") or "User"
                self._remember_episode(
                    f"{who}: {_trim(authored, 600)}\nAssistant: {_trim(assistant_content, 900)}",
                    importance=0.2,
                    ttl_days=float(self._config.get("episode_ttl_days", 30)) or None,
                    source=f"hermes:{self._platform or 'turn'}",
                    meta={"session_id": session_id or self._session_id,
                          "origin": _prov.USER_TYPED if human else _prov.SYSTEM_TURN,
                          "trust": "human" if human else "system", "trust_reason": reason},
                )
            if human and _truthy(self._config.get("auto_extract", True)):
                if session_id:
                    self._session_id = session_id
                self._save_extracted(authored, "hermes:auto-extract", human=True)
        except Exception as exc:
            log.debug("teresis sync_turn failed: %s", exc)

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> None:
        if not (self._store and self._write_enabled):
            return
        scope = "user" if target == "user" else self._scope
        kind = "preference" if target == "user" else "fact"
        prev = (metadata or {}).get("previous_content")
        # Stored content is the redacted form, so scrub prev too for find()/update() to match.
        if prev:
            prev = _secrets.redact_secrets(prev)[0]
        if content:
            content = _secrets.redact_secrets(content)[0]
        if action in ("add", "replace") and content and _threats.first_threat(content):
            return  # Hermes' own scanner normally stops this first; never mirror it if it slips through
        try:
            if action == "add" and content:
                self._write_or_skip(content, scope=scope, kind=kind, importance=0.7, source="hermes:memory-tool",
                                    meta={"origin": _prov.ASSISTANT_TOOL, "trust": "assistant"})
            elif action == "replace" and content:
                old = self._store.find(prev, scope=scope) if prev else None
                if old:
                    self._store.update(old.id, content)
                else:
                    self._store.remember(content, scope=scope, kind=kind, importance=0.7, source="hermes:memory-tool",
                                         meta={"origin": _prov.ASSISTANT_TOOL, "trust": "assistant"})
            elif action == "remove":
                old = self._store.find(prev or content, scope=scope) if (prev or content) else None
                if old:
                    self._store.forget(old.id)
        except Exception as exc:
            log.debug("teresis on_memory_write failed: %s", exc)

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Compaction hook. Never writes preference/decision/procedure/fact rows by default.

        The message list holds model-written compaction summaries, system prompts, assistant and
        tool messages, and notices, none of which are user-authored. A metadata-only episode is
        checkpointed. With ``extract_on_pre_compress: true`` user-role text goes through the
        candidate quarantine only (unverified, never promoted by marker or corroboration).
        """
        if not (self._store and self._write_enabled):
            return ""
        msgs = [m for m in (messages or []) if isinstance(m, dict)]
        try:
            if _truthy(self._config.get("pre_compress_checkpoint", True)) and msgs:
                users = sum(1 for m in msgs if m.get("role") == "user")
                self._remember_episode(
                    f"Context compaction checkpoint: {len(msgs)} messages ({users} user-role) in session "
                    f"{self._session_id or 'unknown'}",
                    importance=0.1, ttl_days=float(self._config.get("episode_ttl_days", 30)) or None,
                    source="hermes:pre-compress",
                    meta={"session_id": self._session_id, "origin": _prov.SYSTEM_TURN, "trust": "system"},
                )
            if _truthy(self._config.get("extract_on_pre_compress", False)) and _truthy(
                    self._config.get("auto_extract", True)):
                for msg in msgs:
                    content = msg.get("content")
                    if msg.get("role") != "user" or not isinstance(content, str):
                        continue
                    authored = _extract.user_authored_text(_secrets.redact_secrets(content)[0])
                    if authored and not _prov.wrapper_shaped(authored) and not _prov.structural_injected(authored):
                        self._save_extracted(authored, "hermes:pre-compress", human=False)
        except Exception as exc:
            log.debug("teresis pre-compress failed: %s", exc)
        return ""

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs) -> None:
        if not (self._store and self._write_enabled and task):
            return
        try:
            task, result = _secrets.redact_secrets(task)[0], _secrets.redact_secrets(result)[0]
            self._remember_episode(
                f"Delegated: {_trim(task, 300)}\nResult: {_trim(result, 600)}",
                importance=0.3, ttl_days=float(self._config.get("episode_ttl_days", 30)) or None,
                source="hermes:delegation", meta={"child_session_id": child_session_id},
            )
        except Exception as exc:
            log.debug("teresis on_delegation failed: %s", exc)

    # -- tools -------------------------------------------------------------
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return _openai_schemas()

    def _scope_allowed(self, scope: Any) -> bool:
        """``hermes/<identity>`` is one profile's namespace. Everything outside ``hermes/`` (user, global,
        project/...) is shared by design. Without this a model could name another profile's scope in a
        tool argument and read, forge or delete its memories in a shared database."""
        if not isinstance(scope, str):
            return False
        s = scope.strip("/ ")
        if not s.startswith("hermes/") and s != "hermes":
            return True
        return any(s == a or s.startswith(a + "/") for a in self._read_scopes)

    def _tool_scope_error(self, tool_name: str, args: Dict[str, Any]) -> Optional[str]:
        refused = (f"scope belongs to another Hermes profile; this profile can use `{self._scope}`, "
                   f"{', '.join(f'`{s}`' for s in self._read_scopes[1:]) or 'no extra scopes'} and shared scopes (user, global, project/...).")
        if "scope" in args and args["scope"] not in (None, "") and not self._scope_allowed(args["scope"]):
            return refused
        mid = args.get("id")
        if mid and tool_name in {"memory_update", "memory_forget", "memory_feedback", "memory_history"}:
            row = self._store.get(str(mid)) if self._store else None
            if row is not None and not self._scope_allowed(row.scope):
                return refused
        return None

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if not self._server:
            return json.dumps({"error": "teresis is not initialized"})
        if tool_name in _WRITE_TOOLS and not self._write_enabled:
            return json.dumps({"error": "memory writes are disabled in this agent context (subagent/cron/flush)"})
        try:
            args = dict(args or {})
            denied = self._tool_scope_error(tool_name, args)
            if denied:
                return json.dumps({"error": denied})
            text, data = self._server.call_tool(tool_name, args)
            if tool_name == "memory_stats" and isinstance(data, dict) and isinstance(data.get("scopes"), dict):
                data = {**data, "scopes": {k: v for k, v in data["scopes"].items() if self._scope_allowed(k)}}
                text = json.dumps(data, indent=2, default=str)
            return json.dumps({"result": text, **(data if isinstance(data, dict) else {"data": data})}, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # -- setup -------------------------------------------------------------
    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "db_path", "description": "SQLite file. Empty = shared ~/.local/share/teresis/memory.db "
             "(same store your MCP agents use). Use $HERMES_HOME/teresis.db to isolate per profile.", "default": ""},
            {"key": "scope", "description": "Write scope. Empty = hermes/<profile>.", "default": ""},
            {"key": "extra_scopes", "description": "Comma-separated scopes also searched on recall.", "default": "user"},
            {"key": "embed", "description": "Embedder backend: ollama or openai. Empty = lexical only.",
             "default": ""},
            {"key": "embed_model", "description": "Embedding model name, e.g. all-minilm.", "default": ""},
            {"key": "embed_url", "description": "Embedder base URL. Empty = http://localhost:11434 for ollama.", "default": ""},
            {"key": "embed_auth", "description": "OpenAI-compatible backend only: profile reads the optional Hermes "
             "TERESIS_EMBED_KEY; none never sends a bearer key.", "default": "profile"},
            {"key": "embed_timeout", "description": "Embedding request timeout in seconds.",
             "type": "number", "default": 120, "minimum": 0.1},
            {"key": "rerank", "description": "Cross-encoder reranker: fastembed. Empty = off. "
             "Needs `pip install fastembed`; falls back gracefully if missing.", "default": ""},
            {"key": "rerank_model", "description": "Reranker model name.", "default": "Xenova/ms-marco-MiniLM-L-6-v2"},
            {"key": "capture_turns", "description": "Store each turn as a short-lived episode.", "type": "boolean",
             "default": True},
            {"key": "auto_extract", "description": "Save stated preferences/decisions automatically. Claims stored from a "
             "human turn without a strong marker are quarantined as candidates.",
             "type": "boolean", "default": True},
            {"key": "extract_on_pre_compress", "description": "Extract from messages about to be compressed. Off by "
             "default: compaction summaries are model-written. When on, results are candidates only.",
             "type": "boolean", "default": False},
            {"key": "candidate_ttl_days", "description": "Days an unpromoted candidate lives before it expires.",
             "type": "integer", "default": 14, "minimum": 1},
            {"key": "system_authors", "description": "Extra comma-separated turn_author names or ids that are never human.",
             "default": ""},
            {"key": "untrusted_platforms", "description": "Extra comma-separated platforms whose turns are never human.",
             "default": ""},
            {"key": "interactive_platforms", "description": "Extra comma-separated platforms where a turn without a "
             "turn_author is a person.", "default": ""},
            {"key": "episode_ttl_days", "description": "Days to keep episodes (0 = forever).", "type": "integer",
             "default": 30, "minimum": 0},
            {"key": "prefetch_k", "description": "Max memories injected per turn.", "type": "integer", "default": 6,
             "minimum": 0, "maximum": 30},
            {"key": "prefetch_min_score", "description": "Score floor for automatic prefetch. Tool recall is not filtered. "
             "Lexical search normalizes the best hit, so also require a distinctive shared term.",
             "type": "number", "default": 0.45, "minimum": 0, "maximum": 1},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        from hermes_cli.config import save_config

        save_config({"plugins": {PLUGIN_KEY: dict(values)}}, merge_existing=True)

    def backup_paths(self) -> List[str]:
        hermes_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        path = Path(self._db_path(hermes_home))
        return [str(p) for p in (path, Path(f"{path}-wal")) if p.exists()]


def register(ctx) -> None:
    """Hermes plugin entry point."""
    ctx.register_memory_provider(TeresisMemoryProvider())


_PLUGIN_INIT = '''"""teresis memory provider for Hermes (MemoryProvider). Generated by `teresis hermes install`."""
from .teresis.hermes import TeresisMemoryProvider, register  # noqa: F401  (register_memory_provider)
'''

def install(hermes_home: str | os.PathLike, *, link: bool = False) -> Path:
    """Install the plugin into ``$HERMES_HOME/plugins/teresis``. ``link`` symlinks the package (dev mode)."""
    pkg = Path(__file__).resolve().parent
    manifest = (pkg / "plugin.yaml").read_text(encoding="utf-8")
    dest = Path(hermes_home).expanduser() / "plugins" / PLUGIN_KEY
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "teresis"
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    if link:
        target.symlink_to(pkg, target_is_directory=True)
    else:
        shutil.copytree(pkg, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dest / "__init__.py").write_text(_PLUGIN_INIT)
    (dest / "plugin.yaml").write_text(manifest, encoding="utf-8")
    return dest


def _read_teresis_yaml_config(hermes_home: Path) -> Dict[str, str]:
    """Read plugins.teresis scalar fields (db_path, scope) from config.yaml with zero deps."""
    cfg_path = hermes_home / "config.yaml"
    if not cfg_path.is_file():
        return {}
    lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: Dict[str, str] = {}
    in_plugins = False
    in_teresis = False
    teresis_indent = -1
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_plugins = stripped == "plugins:"
            in_teresis = False
            continue
        if in_plugins and not in_teresis and stripped == f"{PLUGIN_KEY}:":
            in_teresis = True
            teresis_indent = indent
            continue
        if in_teresis:
            if indent <= teresis_indent:
                in_teresis = False
                continue
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                val = v.strip().strip("'\"")
                if val:
                    out[k.strip()] = val
    return out


def parse_hermes_memory_file(text: str) -> List[str]:
    """Split a Hermes MEMORY.md / USER.md file on its '§' entry separator (or paragraphs)."""
    import re

    raw = (text or "").strip()
    if not raw:
        return []
    if re.search(r"(?:^|\n)\s*§\s*(?:\n|$)", raw):
        parts = re.split(r"(?:^|\n)\s*§\s*(?:\n|$)", raw)
    else:
        parts = re.split(r"\n\s*\n+", raw)
    out: List[str] = []
    for p in parts:
        cleaned = " ".join(line.strip() for line in p.strip().splitlines() if line.strip())
        if cleaned:
            out.append(cleaned)
    return out


def import_memories(
    hermes_home: str | os.PathLike,
    *,
    db_path: str | os.PathLike | None = None,
    scope: str | None = None,
    user_scope: str = "user",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Import Hermes built-in MEMORY.md and USER.md entries into a Teresis store (non-destructive, idempotent)."""
    home = Path(hermes_home).expanduser()
    cfg = _read_teresis_yaml_config(home)
    target_db = Path(db_path).expanduser() if db_path else _profile_db_path(cfg.get("db_path", ""), home.absolute())
    if not db_path and cfg.get("db_path", "").strip() and not target_db.is_absolute():
        raise ValueError("Hermes Teresis db_path must be absolute or start with $HERMES_HOME; "
                         "use --db to choose the import destination")
    default_scope = f"hermes/{home.name}" if home.parent.name == "profiles" else "hermes/default"
    target_scope = (scope or cfg.get("scope") or default_scope).strip()

    mem_dir = home / "memories"
    mem_entries = parse_hermes_memory_file((mem_dir / "MEMORY.md").read_text(encoding="utf-8", errors="replace")) if (mem_dir / "MEMORY.md").is_file() else []
    user_entries = parse_hermes_memory_file((mem_dir / "USER.md").read_text(encoding="utf-8", errors="replace")) if (mem_dir / "USER.md").is_file() else []

    stats: Dict[str, Any] = {
        "hermes_home": str(home),
        "db_path": str(target_db),
        "scope": target_scope,
        "user_scope": user_scope,
        "memory_entries": len(mem_entries),
        "user_entries": len(user_entries),
        "created": 0,
        "duplicates": 0,
        "redacted": 0,
        "dry_run": dry_run,
    }
    if dry_run or not (mem_entries or user_entries):
        return stats

    with MemoryStore(target_db, embedder=None, reranker=None) as store:
        for entry in mem_entries:
            res = store.remember(entry, scope=target_scope, kind="fact", importance=0.7,
                                 source="hermes:import:MEMORY.md", meta={"origin": "import", "trust": "import"})
            if res.status == "created":
                stats["created"] += 1
            else:
                stats["duplicates"] += 1
            if res.redacted:
                stats["redacted"] += 1
        for entry in user_entries:
            res = store.remember(entry, scope=user_scope, kind="preference", importance=0.7,
                                 source="hermes:import:USER.md", meta={"origin": "import", "trust": "import"})
            if res.status == "created":
                stats["created"] += 1
            else:
                stats["duplicates"] += 1
            if res.redacted:
                stats["redacted"] += 1
    return stats
