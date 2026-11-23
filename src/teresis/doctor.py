"""One-command wiring (`teresis setup`) and health checks (`teresis doctor`).

``setup`` writes an MCP entry pointing every agent it can find at the *same* SQLite file, so
Claude Code, Cursor, Codex and Hermes all read and write one memory. It is idempotent: an
existing entry is replaced, never duplicated, and ``--dry-run`` prints the diff instead of
writing.

``doctor`` proves the install actually works: SQLite/FTS5 capabilities, a write-read-forget
round trip through the real store, the entity graph, the optional embedder, and whether each
detected client can resolve the server command.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .store import MemoryStore, default_db_path

SERVER_NAME = "teresis"


# --------------------------------------------------------------------------- command
def server_command() -> tuple[str, list[str], dict[str, str]]:
    """How an MCP client should launch this install (console script when available)."""
    env: dict[str, str] = {}
    exe = shutil.which("teresis")
    if exe:
        return exe, ["serve", "--scope", "global"], env
    src = Path(__file__).resolve().parents[1]
    if (src / "teresis" / "__init__.py").exists():
        env["PYTHONPATH"] = str(src)
    return sys.executable or "python3", ["-m", "teresis", "serve", "--scope", "global"], env


# --------------------------------------------------------------------------- clients
@dataclass(frozen=True)
class Client:
    id: str
    name: str
    config: Path
    kind: str  # "json" | "toml" | "hermes"

    def detected(self) -> bool:
        if self.kind == "hermes":
            return self.config.exists()
        if self.id == "claude-code":
            return self.config.exists() or shutil.which("claude") is not None
        return self.config.exists() or self.config.parent.exists()


def clients(home: Path | None = None) -> list[Client]:
    h = home or Path.home()
    return [
        Client("claude-code", "Claude Code", h / ".claude.json", "json"),
        Client("cursor", "Cursor", h / ".cursor" / "mcp.json", "json"),
        Client("codex", "Codex", h / ".codex" / "config.toml", "toml"),
        Client("hermes", "Hermes Agent", h / ".hermes", "hermes"),
    ]


def _mcp_entry() -> dict[str, Any]:
    command, args, env = server_command()
    entry: dict[str, Any] = {"command": command, "args": args}
    if env:
        entry["env"] = env
    return entry


def _write_json(config: Path, *, dry_run: bool) -> str:
    data: dict[str, Any] = {}
    if config.exists():
        try:
            data = json.loads(config.read_text() or "{}")
        except json.JSONDecodeError:
            return "failed: config is not valid JSON"
        if not isinstance(data, dict):
            return "failed: config root is not an object"
    servers = data.setdefault("mcpServers", {})
    entry = _mcp_entry()
    if servers.get(SERVER_NAME) == entry:
        return "already configured"
    servers[SERVER_NAME] = entry
    if dry_run:
        return f"would write {config}"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n")
    return f"configured {config}"


_TOML_BLOCK = re.compile(r"^\[mcp_servers\.teresis\]\n(?:(?!\[).*(?:\n|\Z))*", re.M)


def _toml_block() -> str:
    command, args, env = server_command()
    lines = [
        "[mcp_servers.teresis]",
        f"command = {json.dumps(command)}",
        f"args = {json.dumps(args)}",
    ]
    if env:
        lines.append("env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in env.items()) + " }")
    return "\n".join(lines) + "\n"


def _write_toml(config: Path, *, dry_run: bool) -> str:
    block = _toml_block()
    text = config.read_text() if config.exists() else ""
    if _TOML_BLOCK.search(text):
        if _TOML_BLOCK.search(text).group(0).strip() == block.strip():
            return "already configured"
        if dry_run:
            return f"would replace [mcp_servers.teresis] in {config}"
        text = _TOML_BLOCK.sub(block, text, count=1)
    else:
        if dry_run:
            return f"would append [mcp_servers.teresis] to {config}"
        text = (text.rstrip() + "\n\n" + block) if text.strip() else block
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text)
    return f"configured {config}"


def setup(home: Path | None = None, *, only: Iterable[str] | None = None, dry_run: bool = False) -> list[dict[str, str]]:
    """Wire every detected MCP client to this store. Returns one row per client."""
    wanted = {s.strip() for s in only} if only else None
    rows: list[dict[str, str]] = []
    for client in clients(home):
        if wanted and client.id not in wanted:
            continue
        if not client.detected():
            rows.append({"client": client.id, "name": client.name, "status": "skipped", "detail": "not installed"})
            continue
        if client.kind == "json":
            detail = _write_json(client.config, dry_run=dry_run)
        elif client.kind == "toml":
            detail = _write_toml(client.config, dry_run=dry_run)
        else:
            if dry_run:
                detail = f"would install Hermes provider in {client.config}"
            else:
                try:
                    from .hermes import install

                    detail = f"installed {install(client.config)}"
                except Exception as exc:  # pragma: no cover - depends on a Hermes checkout
                    detail = f"failed: {exc}"
        status = "failed" if detail.startswith("failed") else ("configured" if detail.startswith(("configured", "installed", "would")) else "already")
        rows.append({"client": client.id, "name": client.name, "status": status, "detail": detail})
    return rows


# --------------------------------------------------------------------------- doctor
@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = False


def _check_python() -> Check:
    v = sys.version_info
    return Check("python", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro} (needs ≥ 3.10)", fatal=True)


def _check_sqlite() -> Check:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        c.execute("INSERT INTO t VALUES ('postgresql')")
        hit = c.execute("SELECT count(*) FROM t WHERE t MATCH 'gre'").fetchone()[0]
        c.close()
    except sqlite3.Error as exc:
        return Check("sqlite-fts5", False, f"{sqlite3.sqlite_version}: {exc}", fatal=True)
    return Check("sqlite-fts5", hit == 1, f"{sqlite3.sqlite_version} with FTS5 + trigram", fatal=True)


def _check_store(db: Path) -> Check:
    try:
        store = MemoryStore(db, embedder=None)
    except Exception as exc:
        return Check("store", False, str(exc), fatal=True)
    try:
        res = store.remember("doctor probe: teresis can write and read", scope="__doctor__", kind="event",
                             importance=0.1, source="teresis doctor")
        hits = store.recall("doctor probe write read", scope="__doctor__", k=3, touch=False)
        found = any(m.id == res.id for m in hits)
        store.forget(res.id, hard=True)
        return Check("store", found, f"round trip ok at {db}" if found else "wrote a probe but recall missed it",
                     fatal=True)
    finally:
        store.close()


def _check_db(db: Path) -> Check:
    if not db.exists():
        return Check("db-file", False, f"{db} does not exist yet (created on first write)")
    size = db.stat().st_size
    writable = os.access(db.parent, os.W_OK)
    return Check("db-file", writable, f"{db} ({size / 1024:.0f} KB, {'writable' if writable else 'read-only'})")


def _check_embedder() -> Check:
    from . import embed as _embed

    emb = _embed.from_env()
    if emb is None:
        return Check("embedder", True, "not configured (lexical only — fully supported)")
    try:
        vec = emb.embed(["ping"])[0]
    except Exception as exc:
        return Check("embedder", False, f"{emb.name}: {exc}")
    return Check("embedder", bool(vec), f"{emb.name} → {len(vec)} dims")


def _check_client(client: Client) -> Check:
    if not client.detected():
        return Check(f"client:{client.id}", True, "not installed (skipped)")
    if client.kind == "json":
        if not client.config.exists():
            return Check(f"client:{client.id}", False, f"{client.config} missing — run `teresis setup`")
        try:
            data = json.loads(client.config.read_text() or "{}")
        except json.JSONDecodeError as exc:
            return Check(f"client:{client.id}", False, f"{client.config}: {exc}")
        entry = (data.get("mcpServers") or {}).get(SERVER_NAME)
        return Check(f"client:{client.id}", bool(entry),
                     f"{client.config}" + ("" if entry else " — run `teresis setup`"))
    if client.kind == "toml":
        text = client.config.read_text() if client.config.exists() else ""
        return Check(f"client:{client.id}", "[mcp_servers.teresis]" in text,
                     f"{client.config}" + ("" if "[mcp_servers.teresis]" in text else " — run `teresis setup`"))
    return Check(f"client:{client.id}", True, f"{client.config} (provider install is separate)")


def run_doctor(db: str | os.PathLike | None = None, *, home: Path | None = None, embed: bool = False) -> dict[str, Any]:
    path = Path(db).expanduser() if db else default_db_path()
    checks: list[Check] = [_check_python(), _check_sqlite(), _check_store(path), _check_db(path)]
    if embed:
        checks.append(_check_embedder())
    try:
        store = MemoryStore(path, embedder=None)
        stats = store.stats()
        store.close()
        checks.append(Check("graph", True, f"{stats.get('entities', 0)} entities, {stats.get('links', 0)} links"))
    except Exception as exc:
        checks.append(Check("graph", False, str(exc)))
    checks.extend(_check_client(c) for c in clients(home))
    failed = [c for c in checks if not c.ok]
    return {
        "ok": not any(c.fatal for c in failed) and not failed,
        "version": __version__,
        "db": str(path),
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail, "fatal": c.fatal} for c in checks],
        "failed": len(failed),
    }
