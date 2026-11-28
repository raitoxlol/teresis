"""Model Context Protocol server over stdio (newline-delimited JSON-RPC 2.0). No dependencies."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from . import __version__
from . import temporal as _temporal
from . import threats as _threats
from .store import MemoryStore

SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """teresis is persistent long-term memory shared across sessions and agents.
- At the start of a task call memory_context (or memory_recall with the task) for the relevant scope.
- Save durable facts, user preferences, decisions, and lessons with memory_remember. One fact per call.
- For facts that change over time, pass a stable `key` (e.g. "user.editor", "project.db"): the new value
  supersedes the old one and history is kept.
- Scopes are paths: "global", "user", "project/<name>", "project/<name>/agent-x". Recall in a scope also
  sees its parents. Never store secrets or credentials.
- When asked why you know or said something, call memory_why with the memory id and cite it."""

_SCOPE = {"type": "string", "description": "Scope path, e.g. 'global', 'user', 'project/acme'. Default 'global'."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memory_remember",
        "description": "Save one durable memory (fact, preference, decision, lesson, procedure). "
        "Exact and near duplicates are merged automatically; a `key` makes it an updatable slot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "A single self-contained statement."},
                "scope": _SCOPE,
                "kind": {"type": "string", "description": "fact | preference | decision | event | procedure | lesson",
                         "default": "fact"},
                "key": {"type": "string", "description": "Stable slot id; a new value supersedes the old one."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "pinned": {"type": "boolean", "description": "Always include in memory_context."},
                "ttl_days": {"type": "number", "description": "Expire after N days (for temporary facts)."},
                "source": {"type": "string", "description": "Who/what produced this memory."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_recall",
        "description": "Search memories by relevance (keyword + fuzzy + semantic when configured), "
        "weighted by recency and importance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "scope": _SCOPE,
                "inherit": {"type": "boolean", "default": True, "description": "Include parent scopes."},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 100},
                "budget_tokens": {"type": "integer", "description": "Pack results to fit this many tokens."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_context",
        "description": "A compact prompt block of pinned, important and (optionally) task-relevant memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": _SCOPE,
                "query": {"type": "string", "description": "Current task, to bias toward relevant memories."},
                "budget_tokens": {"type": "integer", "default": 1200},
            },
        },
    },
    {
        "name": "memory_update",
        "description": "Revise a memory by id. Changing content creates a new version; history is kept.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "content": {"type": "string"},
                "importance": {"type": "number"},
                "pinned": {"type": "boolean"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
    {
        "name": "memory_forget",
        "description": "Delete a memory by id, or a keyed slot by scope+key. This is a real delete: the "
        "text, its older versions and its search entries are removed. Pass hard=false only for a recoverable soft-delete.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "scope": _SCOPE, "key": {"type": "string"},
                           "hard": {"type": "boolean", "default": True}},
        },
    },
    {
        "name": "memory_history",
        "description": "All versions of a fact (by id, or by scope+key), oldest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "scope": _SCOPE, "key": {"type": "string"}},
        },
    },
    {
        "name": "memory_why",
        "description": "Explain where a memory came from: who said it, when, on which platform and "
        "profile, what it replaced, and whether it is current. Use it when asked why you know or "
        "said something.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "memory_feedback",
        "description": "Rate a recalled memory after using it: helpful ones rank higher, unhelpful ones sink.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "helpful": {"type": "boolean"}},
            "required": ["id", "helpful"],
        },
    },
    {
        "name": "memory_conflicts",
        "description": "List pairs of memories that look like contradictions or stale duplicates, for cleanup "
        "(resolve with memory_update, memory_forget, or by re-saving with a key).",
        "inputSchema": {
            "type": "object",
            "properties": {"scope": _SCOPE, "limit": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "memory_stats",
        "description": "Counts per scope and store configuration.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_READONLY = {"memory_recall", "memory_context", "memory_history", "memory_stats", "memory_conflicts",
             "memory_why"}
for _t in TOOLS:
    _t["annotations"] = {"readOnlyHint": _t["name"] in _READONLY, "destructiveHint": _t["name"] == "memory_forget"}


MAX_MEMORY_CHARS = 4000        # one memory is one self-contained statement, not a document
MAX_TOOL_ITEM_CHARS = 1200     # per memory in a tool reply
MAX_TOOL_OUTPUT_CHARS = 20000  # whole tool reply


def _clip(text: str, n: int = MAX_TOOL_ITEM_CHARS) -> str:
    text = text or ""
    return text if len(text) <= n else f"{text[:n]}... [truncated, {len(text)} chars]"


def _clip_dicts(mems) -> list[dict]:
    """Compact dicts for the structured half of a reply, bounded like the text half."""
    out, used = [], 0
    for m in mems:
        d = m.to_dict(compact=True)
        d["content"] = _clip(d.get("content", ""))
        used += len(d["content"]) + 200
        if used > MAX_TOOL_OUTPUT_CHARS:
            break
        out.append(d)
    return out


def _clip_receipt(r: dict) -> dict:
    """A receipt with every text field clipped like a recalled memory; the keys are unchanged."""
    out = {k: _clip(v) if isinstance(v, str) else v for k, v in r.items()}
    out["replaced"] = [{k: _clip(v) if isinstance(v, str) else v for k, v in rep.items()}
                       for rep in r.get("replaced") or []]
    return out


def why_reply(store: MemoryStore, groups: list[tuple[str, list[str]]],
              notes: dict[str, str] | None = None) -> tuple[str, dict]:
    """memory_why text and data for ``(label, ids)`` groups, bounded like other tool replies.

    Each text field is clipped to MAX_TOOL_ITEM_CHARS. Receipts and missing ids stop at
    MAX_TOOL_OUTPUT_CHARS of JSON (``omitted`` counts the rest), and the text is cut at
    MAX_TOOL_OUTPUT_CHARS. A group with a label is rendered under ``<label>:``. ``notes``
    (id -> why the packet injected it) adds a text line per receipt; the data keys are unchanged.
    """
    from . import receipt as _receipt

    sections: list[str] = []
    receipts: list[dict] = []
    missing: list[str] = []
    used = omitted = 0
    for label, ids in groups:
        if not ids:
            continue
        _, data = _receipt.explain(store, ids)
        shown: list[dict] = []
        gone: list[str] = []
        for item in [_clip_receipt(r) for r in data["receipts"]] + [_clip(i) for i in data["missing"]]:
            size = len(json.dumps(item, default=str)) + 2  # with its ", " in the list
            if used + size > MAX_TOOL_OUTPUT_CHARS:
                omitted += 1
                continue
            used += size
            (shown if isinstance(item, dict) else gone).append(item)
        if not shown and not gone:
            continue
        text = _receipt.render(shown, gone, {k: _clip(v) for k, v in (notes or {}).items()})
        sections.append(f"{label}:\n{text}" if label else text)
        receipts += shown
        missing += gone
    text = "\n\n".join(sections) or "No memories to explain."
    if omitted:
        text += f"\n\n... [{omitted} more not shown; ask for fewer ids]"
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[:MAX_TOOL_OUTPUT_CHARS] + "\n... [truncated; ask for fewer ids]"
    data = {"receipts": receipts, "missing": missing}
    if omitted:
        data["omitted"] = omitted
    return text, data


def _fmt(mems) -> str:
    if not mems:
        return "No memories found."
    lines = []
    for m in mems:
        bits = [m.kind, m.scope]
        if m.kind == "candidate":
            bits = [f"candidate:{m.meta.get('candidate_kind', '?')}, unreviewed, not injected", m.scope]
        if m.key:
            bits.append(f"key={m.key}")
        if m.superseded_by:
            bits.append(f"superseded_by={m.superseded_by}")
        content = _temporal.with_saved_note(m.content, m.created_at, display_content=_clip(m.content))
        lines.append(f"[{m.id}] ({', '.join(bits)}) {content}")
    text = "\n".join(lines)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[:MAX_TOOL_OUTPUT_CHARS] + f"\n... [truncated, {len(lines)} results; narrow the query or lower k]"
    return text


class Server:
    def __init__(self, store: MemoryStore, default_scope: str | list[str] = "global"):
        """``default_scope`` may be a list: writes go to the first scope, reads search all of them."""
        self.store = store
        self.read_scopes = [default_scope] if isinstance(default_scope, str) else list(default_scope)
        self.write_scope = self.read_scopes[0]

    def _scope(self, args: dict) -> str:
        return args.get("scope") or self.write_scope

    def _read_scope(self, args: dict) -> str | list[str]:
        return args.get("scope") or self.read_scopes

    def call_tool(self, name: str, a: dict[str, Any]) -> tuple[str, Any]:
        if name in ("memory_remember", "memory_update") and len(str(a.get("content") or "")) > MAX_MEMORY_CHARS:
            raise ValueError(f"memory too long ({len(str(a['content']))} chars, max {MAX_MEMORY_CHARS}): "
                             "save a short summary, or split it into separate facts")
        s = self.store
        if name in ("memory_remember", "memory_update") and a.get("content"):
            hit = _threats.first_threat(str(a["content"]))
            if hit:
                raise ValueError(_threats.rejection_message(hit))
        if name == "memory_remember":
            r = s.remember(
                a["content"], scope=self._scope(a), kind=a.get("kind", "fact"), key=a.get("key"),
                tags=a.get("tags") or (), importance=a.get("importance", 0.5), pinned=bool(a.get("pinned")),
                ttl_days=a.get("ttl_days"), source=a.get("source"),
                meta={"origin": "assistant-tool", "trust": "assistant"},
            )
            msg = f"{r.status}: {r.id}" + (f" (replaced {', '.join(r.replaced)})" if r.replaced else "")
            return msg, r.to_dict()
        if name == "memory_recall":
            mems = s.recall(
                a.get("query", ""), scope=self._read_scope(a), inherit=a.get("inherit", True), kinds=a.get("kinds"),
                tags=a.get("tags"), k=int(a.get("k", 8)), budget_tokens=a.get("budget_tokens"),
            )
            return _fmt(mems), {"memories": _clip_dicts(mems)}
        if name == "memory_context":
            block = s.context(self._read_scope(a), query=a.get("query", ""), budget_tokens=int(a.get("budget_tokens", 1200)))
            return block or "No memories in this scope yet.", {"context": block}
        if name == "memory_update":
            changes = {k: a[k] for k in ("importance", "pinned", "tags") if k in a}
            r = s.update(a["id"], a.get("content"), **changes)
            return f"{r.status}: {r.id}", r.to_dict()
        if name == "memory_forget":
            n = s.forget(a.get("id"), scope=a.get("scope"), key=a.get("key"), hard=bool(a.get("hard", True)))
            return f"forgot {n} memor{'y' if n == 1 else 'ies'}", {"forgotten": n}
        if name == "memory_history":
            mems = s.history(a.get("id"), scope=a.get("scope"), key=a.get("key"))
            return _fmt(mems), {"versions": _clip_dicts(mems)}
        if name == "memory_why":
            ids = [str(i) for i in (a.get("ids") or [])] + ([str(a["id"])] if a.get("id") else [])
            if not ids:
                raise ValueError("memory_why needs an id")
            return why_reply(s, [("", ids)])
        if name == "memory_feedback":
            r = s.feedback(a["id"], bool(a["helpful"]))
            return f"importance now {r['importance']}" + (" (flagged for review)" if r["flagged"] else ""), r
        if name == "memory_conflicts":
            pairs = s.conflicts(a.get("scope"), limit=int(a.get("limit", 20)))
            if not pairs:
                return "No likely conflicts.", {"conflicts": []}
            text = "\n".join(f"{p['similarity']:.2f}  [{p['newer']['id']}] {p['newer']['content']}\n"
                             f"      vs [{p['older']['id']}] {p['older']['content']}" for p in pairs)
            return text, {"conflicts": pairs}
        if name == "memory_stats":
            st = s.stats()
            return json.dumps(st, indent=2), st
        raise KeyError(f"unknown tool: {name}")

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if mid is None:  # notification
            return None
        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                result = {
                    "protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "teresis", "version": __version__},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    text, data = self.call_tool(params["name"], params.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": text}], "structuredContent": data,
                              "isError": False}
                except (KeyError, ValueError, TypeError) as exc:
                    if isinstance(exc, KeyError) and str(exc).startswith("'unknown tool"):
                        raise
                    result = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}

    def serve(self, inp: TextIO = sys.stdin, out: TextIO = sys.stdout, log: Callable[[str], None] | None = None) -> None:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            else:
                resp = self.handle(msg) if isinstance(msg, dict) else None
            if resp is not None:
                out.write(json.dumps(resp) + "\n")
                out.flush()
