"""Explicit opt-in to Teresis in a single named Hermes profile."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .hermes import PLUGIN_KEY, _PLUGIN_INIT, install
from .store import default_db_path

_BUILTIN = {"", "default", "builtin", "built-in", "none"}
_PROVIDER_KEY = "memory.provider"
_DB_KEY = "plugins.teresis.db_path"


def activate(profile: str, db: str | os.PathLike | None = None, *, dry_run: bool = False) -> dict[str, str]:
    """Install and select Teresis without switching away from another provider or pin."""
    hermes = shutil.which("hermes")
    if not hermes:
        raise ValueError("Hermes CLI was not found on PATH")
    if not profile.strip() or profile.startswith("-"):
        raise ValueError("specify an existing Hermes profile (use 'default' for the default)")
    path = (Path(db).expanduser() if db else default_db_path()).resolve()

    def run(*args: str, missing: str | None = None) -> str | None:
        command = [hermes, "--profile", profile, "config", *args]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"could not run Hermes config {args[0]} for profile {profile!r}") from exc
        if result.returncode:
            if missing and f"Config key not set: {missing}" in result.stderr:
                return None
            raise ValueError(f"Hermes config {args[0]} failed for profile {profile!r}; "
                             "check the profile name, Hermes version and saved config")
        return result.stdout.strip()

    def get(key: str):
        raw = run("get", key, "--json", missing=key)
        try:
            return None if raw is None else json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"Hermes did not return a JSON value for {key}") from exc

    raw_config = run("path")
    config = Path(raw_config or "")
    if not config.is_absolute() or config.name != "config.yaml" or not config.parent.is_dir():
        raise ValueError(f"Hermes did not resolve an existing profile directory for {profile!r}")
    home = config.parent.resolve()
    plugin_root = home / "plugins"
    dest = plugin_root / PLUGIN_KEY

    def require_compatible_provider() -> str:
        value = get(_PROVIDER_KEY)
        if value is not None and not isinstance(value, str):
            raise ValueError("Hermes memory.provider is not a provider name")
        current = (value or "").strip()
        if current not in _BUILTIN and current != PLUGIN_KEY:
            raise ValueError(f"Hermes profile {profile!r} already selects {current!r}; "
                             "nothing was switched")
        return current

    provider = require_compatible_provider()
    disabled = get("plugins.disabled")
    if disabled is not None and not isinstance(disabled, list):
        raise ValueError("Hermes plugins.disabled is not a list")
    if disabled and PLUGIN_KEY in disabled:
        raise ValueError("Teresis is explicitly disabled in this profile; enable it in Hermes first")
    db_config = get(_DB_KEY)
    if db_config is not None and not isinstance(db_config, str):
        raise ValueError("Hermes Teresis db_path is not a path string")
    if db_config:
        existing = Path(os.path.expanduser(db_config.replace("${HERMES_HOME}", str(home))
                                                           .replace("$HERMES_HOME", str(home))))
        if not existing.is_absolute() or existing.resolve() != path:
            raise ValueError(f"Hermes profile {profile!r} already has a different Teresis db_path; "
                             "choose the same database or change the path explicitly in Hermes")

    if plugin_root.is_symlink() or dest.is_symlink():
        raise ValueError("refusing to install through a symlinked Hermes plugin directory")
    if dest.exists():
        wrapper = dest / "__init__.py"
        if (not wrapper.is_file() or wrapper.read_text(encoding="utf-8") != _PLUGIN_INIT
                or not (dest / "plugin.yaml").is_file() or not (dest / "teresis/hermes.py").is_file()):
            raise ValueError("a non-Teresis-CLI plugin already occupies this slot; use Hermes' native memory setup")

    unchanged = dest.is_dir() and db_config == str(path) and provider == PLUGIN_KEY
    if not dry_run and not unchanged:
        if not dest.exists():
            install(home)
        if db_config != str(path):
            run("set", _DB_KEY, str(path))
            if get(_DB_KEY) != str(path):
                raise ValueError("Hermes did not persist the selected Teresis db_path; provider not switched")
        # Recheck before selecting (another app may have changed the slot since preflight).
        if require_compatible_provider() != PLUGIN_KEY:
            run("set", _PROVIDER_KEY, PLUGIN_KEY)
        if get(_PROVIDER_KEY) != PLUGIN_KEY:
            raise ValueError("Hermes did not persist memory.provider=teresis; provider not verified")
    return {"profile": profile, "plugin": str(dest), "db": str(path),
            "status": "already" if unchanged else "planned" if dry_run else "configured"}
