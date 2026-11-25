"""Pin desktop MCP launchers to one SQLite file and check their saved configuration."""

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

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no standard-library TOML parser.
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

from . import __version__
from .store import MemoryStore, default_db_path

SERVER_NAME = "teresis"


# --------------------------------------------------------------------------- command
def _db_path(db: str | os.PathLike | None) -> Path:
    return (Path(db).expanduser() if db else default_db_path()).resolve()


def server_command(db: Path) -> tuple[str, list[str], dict[str, str]]:
    """How an MCP client should launch this install (console script when available)."""
    serve = ["serve", "--scope", "global", "--db", str(db)]
    env: dict[str, str] = {}
    exe = shutil.which("teresis")
    if exe:
        return os.path.abspath(exe), serve, env
    src = Path(__file__).resolve().parents[1]
    if (src / "teresis" / "__init__.py").exists():
        env["PYTHONPATH"] = str(src)
    return sys.executable or "python3", ["-m", "teresis", *serve], env


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


def _mcp_entry(db: Path) -> dict[str, Any]:
    command, args, env = server_command(db)
    entry: dict[str, Any] = {"command": command, "args": args}
    if env:
        entry["env"] = env
    return entry


def _configured_entry(data: Any, key: str) -> Any:
    servers = data.get(key) if isinstance(data, dict) else None
    return servers.get(SERVER_NAME) if isinstance(servers, dict) else None


def _without_codex_entry(data: dict[str, Any]) -> dict[str, Any]:
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return data
    result = dict(data)
    others = {key: val for key, val in servers.items() if key != SERVER_NAME}
    if others:
        result["mcp_servers"] = others
    else:
        result.pop("mcp_servers")
    return result


def _write_json(config: Path, db: Path, *, dry_run: bool) -> str:
    data: dict[str, Any] = {}
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return "failed: config is not valid JSON"
        if not isinstance(data, dict):
            return "failed: config root is not an object"
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return "failed: mcpServers is not an object"
    entry = _mcp_entry(db)
    if servers.get(SERVER_NAME) == entry:
        return "already configured"
    servers[SERVER_NAME] = entry
    if dry_run:
        return f"would write {config}"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"configured {config}"


_TOML_BLOCK = re.compile(r"^\[mcp_servers\.teresis\]\n(?:(?!\[).*(?:\n|\Z))*", re.M)


def _toml_block(db: Path) -> str:
    command, args, env = server_command(db)

    def quote(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        "[mcp_servers.teresis]",
        f"command = {quote(command)}",
        f"args = {quote(args)}",
    ]
    if env:
        lines.append("env = { " + ", ".join(f"{k} = {quote(v)}" for k, v in env.items()) + " }")
    return "\n".join(lines) + "\n"


def _write_toml(config: Path, db: Path, *, dry_run: bool) -> str:
    block = _toml_block(db)
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    current = _TOML_BLOCK.search(text)
    before = None
    if tomllib is None and text.strip():
        return "failed: preserving existing Codex TOML requires Python 3.11+ or optional tomli"
    if tomllib is not None:
        try:
            before = tomllib.loads(text)
        except ValueError:
            return "failed: config is not valid TOML"
    if current:
        if current.group(0).strip() == block.strip():
            return "already configured"
        action = "replace [mcp_servers.teresis] in"
        text = _TOML_BLOCK.sub(lambda _: block, text, count=1)
    else:
        action = "append [mcp_servers.teresis] to"
        text = (text.rstrip() + "\n\n" + block) if text.strip() else block
    if tomllib is not None:
        try:
            parsed = tomllib.loads(text)
        except ValueError:
            return "failed: updating this Teresis entry would produce invalid TOML"
        if _configured_entry(parsed, "mcp_servers") != _mcp_entry(db):
            return "failed: could not verify the updated Teresis entry"
        if _without_codex_entry(parsed) != _without_codex_entry(before):
            return "failed: updating the Teresis entry would change other Codex settings"
    if dry_run:
        return f"would {action} {config}"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text, encoding="utf-8")
    return f"configured {config}"


def setup(home: Path | None = None, *, db: str | os.PathLike | None = None,
          only: Iterable[str] | None = None, dry_run: bool = False) -> list[dict[str, str]]:
    """Wire detected MCP clients to one absolute DB; Hermes still needs profile setup."""
    path = _db_path(db)
    wanted = {s.strip() for s in only} if only else None
    rows: list[dict[str, str]] = []
    for client in clients(home):
        if wanted and client.id not in wanted:
            continue
        if not client.detected():
            rows.append({"client": client.id, "name": client.name, "status": "skipped", "detail": "not installed"})
            continue
        try:
            if client.kind == "json":
                detail = _write_json(client.config, path, dry_run=dry_run)
            elif client.kind == "toml":
                detail = _write_toml(client.config, path, dry_run=dry_run)
            else:
                plugin_root = client.config / "plugins"
                dest = plugin_root / "teresis"
                if os.path.lexists(dest):
                    install_detail = f"existing Hermes plugin path (unchanged, not verified): {dest}; verify it works before continuing"
                elif plugin_root.is_symlink():
                    raise ValueError("refusing to install through a symlinked Hermes plugin directory")
                elif dry_run:
                    install_detail = f"would install Hermes provider in {client.config}"
                else:
                    from .hermes import install

                    install_detail = f"installed {install(client.config)}"
                detail = (f"{install_detail}; select memory.provider=teresis and set "
                          f"plugins.teresis.db_path to {path} in the active Hermes profile")
                rows.append({"client": client.id, "name": client.name, "status": "partial", "detail": detail})
                continue
        except (OSError, ValueError) as exc:
            detail = f"failed: {exc}"
        status = ("failed" if detail.startswith("failed")
                  else "configured" if detail.startswith(("configured", "would")) else "already")
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


def _check_provenance(db: Path) -> tuple[Check, dict[str, Any]]:
    """Counts by origin/kind, the candidate queue, and rows whose origin is not trusted."""
    from . import review

    try:
        store = MemoryStore(db, embedder=None)
        try:
            rep = review.report(store)
        finally:
            store.close()
    except Exception as exc:
        return Check("provenance", False, str(exc)), {}
    origins = ", ".join(f"{k} {v}" for k, v in sorted(rep["by_origin"].items())) or "no rows"
    detail = f"{rep['active']} active ({origins}); {rep['candidates']} candidate(s) waiting for review"
    bad = len(rep["untrusted"])
    if bad:
        detail += f"; {bad} row(s) with an untrusted origin: run `teresis review` or `teresis scrub`"
    return Check("provenance", bad == 0, detail), rep


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


def _check_client(client: Client, db: Path) -> Check:
    name = f"client:{client.id}"
    if not client.detected():
        return Check(name, True, "not installed (skipped)")
    if client.kind == "hermes":
        return Check(name, False, f"{client.config}: active Hermes provider and db_path not verified; "
                     f"check the selected profile uses Teresis and {db}")
    if not client.config.exists():
        return Check(name, False, f"{client.config} missing — run `teresis setup`")
    try:
        raw = client.config.read_text(encoding="utf-8")
        if client.kind == "json":
            entry = _configured_entry(json.loads(raw or "{}"), "mcpServers")
        else:
            if tomllib is None:
                return Check(name, False, "Codex config unverified: needs Python 3.11+ or optional tomli")
            entry = _configured_entry(tomllib.loads(raw), "mcp_servers")
    except (OSError, ValueError) as exc:
        return Check(name, False, f"{client.config}: {exc}")
    expected = _mcp_entry(db)
    if (not isinstance(entry, dict) or entry.get("command") != expected["command"]
            or entry.get("args") != expected["args"] or entry.get("env", {}) != expected.get("env", {})
            or entry.get("enabled", True) is not True or entry.get("disabled", False) is not False
            or entry.get("url") or not os.access(expected["command"], os.X_OK)):
        return Check(name, False, f"{client.config}: no matching enabled launcher pinned to {db} "
                     f"— review configuration or run `teresis setup` with the same DB")
    return Check(name, True, f"{client.config}: saved launcher pins {db} (agent not started)")


def run_doctor(db: str | os.PathLike | None = None, *, home: Path | None = None, embed: bool = False) -> dict[str, Any]:
    path = _db_path(db)
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
    prov_check, prov = _check_provenance(path)
    checks.append(prov_check)
    checks.extend(_check_client(c, path) for c in clients(home))
    failed = [c for c in checks if not c.ok]
    return {
        "provenance": prov,
        "ok": not any(c.fatal for c in failed) and not failed,
        "version": __version__,
        "db": str(path),
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail, "fatal": c.fatal} for c in checks],
        "failed": len(failed),
    }
