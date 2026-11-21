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

import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import extract as _extract
from .mcp import TOOLS, Server
from .store import MemoryStore, default_db_path
from .text import containment, term_set

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
    "capture_turns": True,
    "episode_ttl_days": 30,
    "auto_extract": True,
}


def _load_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly

        return dict(cfg_get(load_config_readonly(), "plugins", PLUGIN_KEY, default={}) or {})
    except Exception:
        return {}


def _truthy(v: Any) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "on"}


def _trim(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _openai_schemas() -> List[Dict[str, Any]]:
    return [{"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]} for t in TOOLS]


class TeresisMemoryProvider(_Base):  # type: ignore[misc,valid-type]
    """Local hybrid-search memory shared with every other teresis client on the machine."""

    pre_compress_checkpoint_api_version = 1

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = {**DEFAULTS, **(config if config is not None else _load_config())}
        self._store: Optional[MemoryStore] = None
        self._server: Optional[Server] = None
        self._scope = "hermes/default"
        self._read_scopes: List[str] = [self._scope]
        self._write_enabled = True
        self._session_id = ""
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
        raw = str(self._config.get("db_path") or "").strip()
        if not raw:
            return str(default_db_path())
        return os.path.expanduser(raw.replace("${HERMES_HOME}", hermes_home).replace("$HERMES_HOME", hermes_home))

    def initialize(self, session_id: str, **kwargs) -> None:
        hermes_home = str(kwargs.get("hermes_home") or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        identity = str(kwargs.get("agent_identity") or "default").strip() or "default"
        self._scope = (str(self._config.get("scope") or "").strip("/ ") or f"hermes/{identity}")
        extra = [s.strip("/ ") for s in str(self._config.get("extra_scopes") or "").split(",") if s.strip("/ ")]
        self._read_scopes = list(dict.fromkeys([self._scope, *extra]))
        self._write_enabled = kwargs.get("agent_context", "primary") not in _NO_WRITE_CONTEXTS
        self._session_id = session_id
        self._platform = kwargs.get("platform", "")
        self._store = MemoryStore(self._db_path(hermes_home))
        self._server = Server(self._store, default_scope=self._read_scopes)

    def shutdown(self) -> None:
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
            lines.append(f"- [{label}] {m.content} (id {m.id})")
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._last_count = 0
        if not self._store or _is_trivial(query):
            return ""
        try:
            k = int(self._config.get("prefetch_k", 6))
            budget = int(self._config.get("prefetch_budget_tokens", 700))
            facts = self._store.recall(query, scope=self._read_scopes, k=k, budget_tokens=budget,
                                       exclude_kinds=["episode"])
            facts = [m for m in facts if (m.score or 0) >= 0.15]
            blocks = [self._format(facts, "Long-term memory (teresis)")] if facts else []
            if _truthy(self._config.get("capture_turns", True)):
                eps = self._store.recall(query, scope=[self._scope], inherit=False, kinds=["episode"], k=2)
                known = [" ".join(m.content.casefold().split()) for m in facts]
                eps = [m for m in eps if (m.score or 0) >= 0.3
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

    def _near_dup(self, content: str):
        """Existing non-episode memory that says the same thing in different words, else None.

        Numbers and polarity words must match exactly, so a changed port or "never" -> "always"
        is a new fact, not a duplicate.
        """
        mine = term_set(content.replace("-", ""))
        if len(mine) < 3:
            return None
        try:
            cands = self._store.recall(content, scope=self._read_scopes, k=5, exclude_kinds=["episode"])
        except Exception:
            return None
        for m in cands:
            theirs = term_set(m.content.replace("-", ""))
            if containment(mine, theirs) < 0.7:
                continue
            diff = mine ^ theirs
            if any(t in self._POLARITY or any(ch.isdigit() for ch in t) for t in diff):
                continue
            return m
        return None

    # -- writes ------------------------------------------------------------
    def _save_extracted(self, text: str, source: str) -> List[str]:
        saved = []
        for c in _extract.extract(text):
            scope = "user" if c.kind == "preference" else self._scope
            content = c.content if not c.content.lower().startswith(("i ", "i'm", "my ")) else f"User: {c.content}"
            try:
                if self._near_dup(content):
                    continue
                self._store.remember(content, scope=scope, kind=c.kind, importance=c.importance,
                                     source=source, meta={"session_id": self._session_id})
                saved.append(content)
            except Exception as exc:
                log.debug("teresis extract save failed: %s", exc)
        return saved

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "",
                  messages: Optional[List[Dict[str, Any]]] = None, turn_author: Optional[Dict[str, Any]] = None) -> None:
        if not (self._store and self._write_enabled):
            return
        user_content = user_content if isinstance(user_content, str) else str(user_content or "")
        assistant_content = assistant_content if isinstance(assistant_content, str) else str(assistant_content or "")
        try:
            if _truthy(self._config.get("capture_turns", True)) and not _is_trivial(user_content):
                who = (turn_author or {}).get("name") or "User"
                self._store.remember(
                    f"{who}: {_trim(user_content, 600)}\nAssistant: {_trim(assistant_content, 900)}",
                    scope=self._scope, kind="episode", importance=0.2,
                    ttl_days=float(self._config.get("episode_ttl_days", 30)) or None,
                    source=f"hermes:{self._platform or 'turn'}",
                    meta={"session_id": session_id or self._session_id},
                )
            if _truthy(self._config.get("auto_extract", True)):
                self._save_extracted(user_content, "hermes:auto-extract")
        except Exception as exc:
            log.debug("teresis sync_turn failed: %s", exc)

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> None:
        if not (self._store and self._write_enabled):
            return
        scope = "user" if target == "user" else self._scope
        kind = "preference" if target == "user" else "fact"
        prev = (metadata or {}).get("previous_content")
        try:
            if action == "add" and content:
                if self._near_dup(content):
                    return
                self._store.remember(content, scope=scope, kind=kind, importance=0.7, source="hermes:memory-tool")
            elif action == "replace" and content:
                old = self._store.find(prev, scope=scope) if prev else None
                if old:
                    self._store.update(old.id, content)
                else:
                    self._store.remember(content, scope=scope, kind=kind, importance=0.7, source="hermes:memory-tool")
            elif action == "remove":
                old = self._store.find(prev or content, scope=scope) if (prev or content) else None
                if old:
                    self._store.forget(old.id)
        except Exception as exc:
            log.debug("teresis on_memory_write failed: %s", exc)

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        if not (self._store and self._write_enabled and _truthy(self._config.get("auto_extract", True))):
            return ""
        saved: List[str] = []
        for msg in messages or []:
            content = msg.get("content")
            if msg.get("role") == "user" and isinstance(content, str) and "summary" not in content[:80].lower():
                saved += self._save_extracted(content, "hermes:pre-compress")
        if not saved:
            return ""
        return "Saved to long-term memory before compression:\n" + "\n".join(f"- {s}" for s in saved[:20])

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs) -> None:
        if not (self._store and self._write_enabled and task):
            return
        try:
            self._store.remember(
                f"Delegated: {_trim(task, 300)}\nResult: {_trim(result, 600)}", scope=self._scope, kind="episode",
                importance=0.3, ttl_days=float(self._config.get("episode_ttl_days", 30)) or None,
                source="hermes:delegation", meta={"child_session_id": child_session_id},
            )
        except Exception as exc:
            log.debug("teresis on_delegation failed: %s", exc)

    # -- tools -------------------------------------------------------------
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return _openai_schemas()

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if not self._server:
            return json.dumps({"error": "teresis is not initialized"})
        if tool_name in _WRITE_TOOLS and not self._write_enabled:
            return json.dumps({"error": "memory writes are disabled in this agent context (subagent/cron/flush)"})
        try:
            text, data = self._server.call_tool(tool_name, dict(args or {}))
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
            {"key": "capture_turns", "description": "Store each turn as a short-lived episode.", "type": "boolean",
             "default": True},
            {"key": "auto_extract", "description": "Save stated preferences/decisions automatically.",
             "type": "boolean", "default": True},
            {"key": "episode_ttl_days", "description": "Days to keep episodes (0 = forever).", "type": "integer",
             "default": 30, "minimum": 0},
            {"key": "prefetch_k", "description": "Max memories injected per turn.", "type": "integer", "default": 6,
             "minimum": 0, "maximum": 30},
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

_PLUGIN_YAML = """name: teresis
version: {version}
description: "teresis — local hybrid-search memory (SQLite FTS5 + trigram + optional embeddings), shared with MCP agents."
"""


def install(hermes_home: str | os.PathLike, *, link: bool = False) -> Path:
    """Install the plugin into ``$HERMES_HOME/plugins/teresis``. ``link`` symlinks the package (dev mode)."""
    from . import __version__

    pkg = Path(__file__).resolve().parent
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
    (dest / "plugin.yaml").write_text(_PLUGIN_YAML.format(version=__version__))
    return dest
