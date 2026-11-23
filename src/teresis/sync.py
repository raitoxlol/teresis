"""Encrypted multi-machine sync (`teresis sync`), standard library only.

A bundle is a single JSON file: PBKDF2-HMAC-SHA256 derives an encryption key and a MAC key
from a passphrase, ChaCha20 (IETF 96-bit nonce) encrypts the JSONL payload, and
HMAC-SHA256 over the metadata plus ciphertext authenticates it (encrypt-then-MAC). Nothing
leaves the machine unencrypted and no third-party crypto dependency is required.

Merging is deterministic and idempotent: memories are matched by ``id`` and ordered by
``updated_at``; a keyed slot (``scope`` + ``key``) that exists under two different ids keeps
the newer value and supersedes the older one, so history survives a merge in both directions.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import shlex
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .store import MemoryStore

FORMAT = "teresis-sync/1"
DEFAULT_KEY_ENV = "TERESIS_SYNC_KEY"
KDF_ITERATIONS = 200_000
_M = 0xFFFFFFFF

_FIELDS = (
    "id", "scope", "kind", "key", "content", "tags", "meta", "source", "importance", "pinned",
    "created_at", "updated_at", "accessed_at", "access_count", "expires_at",
    "superseded_by", "superseded_at", "deleted_at",
)


# --------------------------------------------------------------------------- crypto
def _rotl(v: int, n: int) -> int:
    return ((v << n) & _M) | (v >> (32 - n))


def _quarter(s: list[int], a: int, b: int, c: int, d: int) -> None:
    s[a] = (s[a] + s[b]) & _M; s[d] ^= s[a]; s[d] = _rotl(s[d], 16)
    s[c] = (s[c] + s[d]) & _M; s[b] ^= s[c]; s[b] = _rotl(s[b], 12)
    s[a] = (s[a] + s[b]) & _M; s[d] ^= s[a]; s[d] = _rotl(s[d], 8)
    s[c] = (s[c] + s[d]) & _M; s[b] ^= s[c]; s[b] = _rotl(s[b], 7)


def chacha20_xor(key: bytes, nonce: bytes, data: bytes) -> bytes:
    """ChaCha20 (RFC 8439, 96-bit nonce, 32-bit block counter). Symmetric."""
    if len(key) != 32:
        raise ValueError("chacha20 needs a 32-byte key")
    if len(nonce) != 12:
        raise ValueError("chacha20 needs a 12-byte nonce")
    const = struct.unpack("<4I", b"expand 32-byte k")
    key_words = struct.unpack("<8I", key)
    nonce_words = struct.unpack("<3I", nonce)
    out = bytearray()
    for counter in range((len(data) + 63) // 64):
        state = list(const) + list(key_words) + [counter & _M, *nonce_words]
        w = state[:]
        for _ in range(10):
            _quarter(w, 0, 4, 8, 12); _quarter(w, 1, 5, 9, 13)
            _quarter(w, 2, 6, 10, 14); _quarter(w, 3, 7, 11, 15)
            _quarter(w, 0, 5, 10, 15); _quarter(w, 1, 6, 11, 12)
            _quarter(w, 2, 7, 8, 13); _quarter(w, 3, 4, 9, 14)
        block = struct.pack("<16I", *[((w[i] + state[i]) & _M) for i in range(16)])
        out += bytes(a ^ b for a, b in zip(data[len(out): len(out) + 64], block))
    return bytes(out)


def _keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, KDF_ITERATIONS, dklen=64)
    return raw[:32], raw[32:]


def _meta_bytes(meta: dict[str, Any]) -> bytes:
    return json.dumps(meta, sort_keys=True, separators=(",", ":")).encode()


def encrypt(payload: bytes, passphrase: str) -> dict[str, Any]:
    salt, nonce = os.urandom(16), os.urandom(12)
    enc_key, mac_key = _keys(passphrase, salt)
    ciphertext = chacha20_xor(enc_key, nonce, payload)
    meta = {
        "format": FORMAT,
        "kdf": {"name": "pbkdf2-hmac-sha256", "iterations": KDF_ITERATIONS,
                "salt": base64.b64encode(salt).decode()},
        "cipher": {"name": "chacha20-hmac-sha256", "nonce": base64.b64encode(nonce).decode()},
    }
    mac = hmac.new(mac_key, _meta_bytes(meta) + ciphertext, hashlib.sha256).digest()
    return {
        **meta,
        "mac": base64.b64encode(mac).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "plain_bytes": len(payload),
    }


def decrypt(bundle: dict[str, Any], passphrase: str) -> bytes:
    if bundle.get("format") != FORMAT:
        raise ValueError(f"unsupported bundle format {bundle.get('format')!r}")
    salt = base64.b64decode(bundle["kdf"]["salt"])
    nonce = base64.b64decode(bundle["cipher"]["nonce"])
    ciphertext = base64.b64decode(bundle["ciphertext"])
    enc_key, mac_key = _keys(passphrase, salt)
    meta = {k: bundle[k] for k in ("format", "kdf", "cipher")}
    want = hmac.new(mac_key, _meta_bytes(meta) + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(want, base64.b64decode(bundle["mac"])):
        raise ValueError("wrong passphrase or corrupted bundle (MAC mismatch)")
    return chacha20_xor(enc_key, nonce, ciphertext)


def passphrase(env: str = DEFAULT_KEY_ENV, *, confirm: bool = False) -> str:
    value = os.environ.get(env, "")
    if value:
        return value
    if not os.isatty(0):
        raise SystemExit(f"set {env} (or pass --key-env NAME) to encrypt or decrypt a sync bundle")
    first = getpass.getpass("sync passphrase: ")
    if not value and confirm and getpass.getpass("confirm passphrase: ") != first:
        raise SystemExit("passphrases did not match")
    if not first:
        raise SystemExit("passphrase must be non-empty")
    return first


# --------------------------------------------------------------------------- bundle
def _payload(store: MemoryStore, scopes: Iterable[str] | None = None) -> bytes:
    wanted = {s.strip("/") for s in scopes} if scopes else None
    lines = []
    for rec in store.export():
        if wanted and rec["scope"] not in wanted:
            continue
        lines.append(json.dumps(rec, sort_keys=True))
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def export_bundle(store: MemoryStore, out: Path, passphrase_value: str, scopes: Iterable[str] | None = None) -> dict[str, Any]:
    payload = _payload(store, scopes)
    bundle = encrypt(payload, passphrase_value)
    bundle["memories"] = payload.count(b"\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(bundle, indent=1) + "\n")
    tmp.replace(out)
    return {"path": str(out), "memories": bundle["memories"], "bytes": out.stat().st_size,
            "plain_bytes": bundle["plain_bytes"]}


def read_bundle(path: Path, passphrase_value: str) -> list[dict[str, Any]]:
    bundle = json.loads(path.read_text())
    payload = decrypt(bundle, passphrase_value)
    return [json.loads(line) for line in payload.decode().splitlines() if line.strip()]


# --------------------------------------------------------------------------- merge
def merge(store: MemoryStore, records: Iterable[dict[str, Any]], *, dry_run: bool = False) -> dict[str, int]:
    """Deterministic, idempotent merge. Newer ``updated_at`` wins; keyed slots supersede."""
    counts = {"inserted": 0, "updated": 0, "skipped": 0, "superseded": 0}
    with store._write() as c:
        for rec in records:
            rec = {k: rec.get(k) for k in _FIELDS if k in rec}
            if not rec.get("id") or not rec.get("content"):
                counts["skipped"] += 1
                continue
            rec.setdefault("scope", "global")
            rec.setdefault("kind", "fact")
            rec.setdefault("created_at", rec.get("updated_at") or store.clock())
            rec.setdefault("updated_at", rec["created_at"])
            rec["scope"] = str(rec["scope"]).strip("/") or "global"
            tags = rec.get("tags") or []
            rec["tags"] = " ".join(tags) if isinstance(tags, list) else str(tags)
            if not isinstance(rec.get("meta"), str):
                rec["meta"] = json.dumps(rec.get("meta") or {})
            rec["content_hash"] = hashlib.sha256(
                " ".join(str(rec["content"]).casefold().split()).encode()
            ).hexdigest()[:32]

            local = c.execute("SELECT * FROM memories WHERE id=?", [rec["id"]]).fetchone()
            if local is not None:
                if float(rec["updated_at"] or 0) <= float(local["updated_at"] or 0):
                    counts["skipped"] += 1
                    continue
                if not dry_run:
                    c.execute(
                        "UPDATE memories SET scope=?, kind=?, key=?, content=?, tags=?, meta=?, source=?,"
                        " importance=?, pinned=?, created_at=?, updated_at=?, accessed_at=?, access_count=?,"
                        " expires_at=?, superseded_by=?, superseded_at=?, deleted_at=?, content_hash=?"
                        " WHERE id=?",
                        [rec["scope"], rec["kind"], rec.get("key"), rec["content"], rec["tags"], rec["meta"],
                         rec.get("source"), rec.get("importance", 0.5), int(bool(rec.get("pinned"))),
                         rec["created_at"], rec["updated_at"], rec.get("accessed_at"),
                         rec.get("access_count", 0), rec.get("expires_at"), rec.get("superseded_by"),
                         rec.get("superseded_at"), rec.get("deleted_at"), rec["content_hash"], rec["id"]],
                    )
                    store._link_entities(c, rec["id"], rec["content"], float(rec["updated_at"]))
                counts["updated"] += 1
                continue

            # Keyed slot arriving under a different id: keep the newer value, keep both histories.
            if rec.get("key") and not rec.get("deleted_at"):
                clash = c.execute(
                    "SELECT id, updated_at FROM memories WHERE scope=? AND key=? AND superseded_by IS NULL"
                    " AND deleted_at IS NULL AND id<>?",
                    [rec["scope"], rec["key"], rec["id"]],
                ).fetchone()
                if clash is not None and float(clash["updated_at"] or 0) >= float(rec["updated_at"] or 0):
                    counts["skipped"] += 1
                    continue
                if clash is not None:
                    counts["superseded"] += 1
                    if not dry_run:
                        rec["superseded_by"] = rec.get("superseded_by") or None
                        c.execute(
                            "UPDATE memories SET superseded_by=?, superseded_at=? WHERE id=?",
                            [rec["id"], rec["updated_at"], clash["id"]],
                        )
            if dry_run:
                counts["inserted"] += 1
                continue
            c.execute(
                "INSERT INTO memories (id, scope, kind, key, content, tags, meta, source, importance, pinned,"
                " content_hash, created_at, updated_at, accessed_at, access_count, expires_at, superseded_by,"
                " superseded_at, deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [rec["id"], rec["scope"], rec["kind"], rec.get("key"), rec["content"], rec["tags"], rec["meta"],
                 rec.get("source"), rec.get("importance", 0.5), int(bool(rec.get("pinned"))),
                 rec["content_hash"], rec["created_at"], rec["updated_at"], rec.get("accessed_at"),
                 rec.get("access_count", 0), rec.get("expires_at"), rec.get("superseded_by"),
                 rec.get("superseded_at"), rec.get("deleted_at")],
            )
            store._link_entities(c, rec["id"], rec["content"], float(rec["updated_at"]))
            counts["inserted"] += 1
    return counts


# --------------------------------------------------------------------------- transport
def _split_target(target: str) -> tuple[str, str]:
    if ":" not in target:
        raise SystemExit("target must look like host:/path/to/bundle.json")
    host, path = target.split(":", 1)
    if not host or not path:
        raise SystemExit("target must look like host:/path/to/bundle.json")
    return host, path


def push(bundle_path: Path, target: str) -> None:
    host, remote = _split_target(target)
    if shutil.which("ssh") is None:
        raise SystemExit("ssh is not available")
    data = bundle_path.read_bytes()
    subprocess.run(["ssh", host, f"cat > {shlex.quote(remote)}"], input=data, check=True)
    print(f"pushed {bundle_path} → {host}:{remote} ({len(data) / 1024:.0f} KB)")


def pull(target: str, out: Path) -> None:
    host, remote = _split_target(target)
    if shutil.which("ssh") is None:
        raise SystemExit("ssh is not available")
    res = subprocess.run(["ssh", host, f"cat {shlex.quote(remote)}"], check=True, capture_output=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(res.stdout)
    print(f"pulled {host}:{remote} → {out} ({len(res.stdout) / 1024:.0f} KB)")
