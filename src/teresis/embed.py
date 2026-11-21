"""Optional embedding providers. The core works without any of them.

Configure with environment variables:

    TERESIS_EMBED=ollama   TERESIS_EMBED_MODEL=nomic-embed-text   [TERESIS_EMBED_URL=http://localhost:11434]
    TERESIS_EMBED=openai   TERESIS_EMBED_MODEL=text-embedding-3-small  TERESIS_EMBED_URL=http://host/v1
                         [TERESIS_EMBED_KEY=...]   (any OpenAI-compatible server: llama.cpp, vLLM, LM Studio)
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from array import array
from typing import Protocol, Sequence

try:  # optional fast path
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - numpy is optional
    _np = None


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float | None = None) -> dict:
    timeout = timeout or float(os.environ.get("TERESIS_EMBED_TIMEOUT", "120"))
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class OllamaEmbedder:
    def __init__(self, model: str, url: str = "http://localhost:11434"):
        self.model, self.url = model, url.rstrip("/")
        self.name = f"ollama:{model}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        data = _post(f"{self.url}/api/embed", {"model": self.model, "input": list(texts)})
        return data["embeddings"]


class OpenAIEmbedder:
    def __init__(self, model: str, url: str, key: str | None = None):
        self.model, self.url, self.key = model, url.rstrip("/"), key
        self.name = f"openai:{model}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        data = _post(f"{self.url}/embeddings", {"model": self.model, "input": list(texts)}, headers)
        return [row["embedding"] for row in sorted(data["data"], key=lambda r: r["index"])]


def from_env() -> Embedder | None:
    kind = os.environ.get("TERESIS_EMBED", "").strip().lower()
    if not kind or kind == "none":
        return None
    model = os.environ.get("TERESIS_EMBED_MODEL")
    if not model:
        raise ValueError("TERESIS_EMBED_MODEL is required when TERESIS_EMBED is set")
    if kind == "ollama":
        return OllamaEmbedder(model, os.environ.get("TERESIS_EMBED_URL", "http://localhost:11434"))
    if kind == "openai":
        url = os.environ.get("TERESIS_EMBED_URL")
        if not url:
            raise ValueError("TERESIS_EMBED_URL is required for TERESIS_EMBED=openai")
        return OpenAIEmbedder(model, url, os.environ.get("TERESIS_EMBED_KEY"))
    raise ValueError(f"unknown TERESIS_EMBED provider: {kind!r}")


def pack(vec: Sequence[float]) -> bytes:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array("f", (x / norm for x in vec)).tobytes()


def unpack(blob: bytes) -> array:
    out = array("f")
    out.frombytes(blob)
    return out


def top_k(query: Sequence[float], rows: list[tuple[str, bytes]], k: int) -> list[tuple[str, float]]:
    """Cosine similarity over unit vectors. Brute force: fine to ~100k memories."""
    if not rows:
        return []
    q = unpack(pack(query))
    if _np is not None:
        mat = _np.frombuffer(b"".join(b for _, b in rows), dtype=_np.float32).reshape(len(rows), -1)
        sims = mat @ _np.frombuffer(q.tobytes(), dtype=_np.float32)
        idx = _np.argsort(-sims)[:k]
        return [(rows[i][0], float(sims[i])) for i in idx]
    scored = []
    for mid, blob in rows:
        v = unpack(blob)
        if len(v) != len(q):
            continue
        scored.append((mid, sum(a * b for a, b in zip(q, v))))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]
