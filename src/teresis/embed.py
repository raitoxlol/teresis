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
import urllib.error
import urllib.parse
import urllib.request
from array import array
from ipaddress import ip_address
from typing import Callable, Protocol, Sequence

try:  # optional fast path
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - numpy is optional
    _np = None


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A configured Hermes endpoint is the disclosure boundary, not any redirect target.
        raise urllib.error.HTTPError(req.full_url, code, "embedding endpoint redirected", headers, fp)


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float | None = None,
          *, no_redirect: bool = False) -> dict:
    timeout = timeout or float(os.environ.get("TERESIS_EMBED_TIMEOUT", "120"))
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    if no_redirect:
        handlers = [_NoRedirect()]
        if _is_loopback_host(urllib.parse.urlsplit(url).hostname):
            # Don't send a configured loopback service (or its bearer) to an ambient HTTP proxy.
            handlers.append(urllib.request.ProxyHandler({}))
        open_request = urllib.request.build_opener(*handlers).open
    else:
        open_request = urllib.request.urlopen
    with open_request(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _is_loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return bool(host and ip_address(host).is_loopback)
    except ValueError:
        return False


def _can_send_bearer(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" or (parsed.scheme == "http" and _is_loopback_host(parsed.hostname))


class OllamaEmbedder:
    def __init__(self, model: str, url: str = "http://localhost:11434", *,
                 timeout: float | None = None, no_redirect: bool = False):
        self.model, self.url = model, url.rstrip("/")
        self.timeout, self.no_redirect = timeout, no_redirect
        self.name = f"ollama:{model}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        data = _post(f"{self.url}/api/embed", {"model": self.model, "input": list(texts)},
                     timeout=self.timeout, no_redirect=self.no_redirect)
        return data["embeddings"]


class OpenAIEmbedder:
    def __init__(self, model: str, url: str, key: str | None = None, *,
                 key_lookup: Callable[[], str | None] | None = None,
                 timeout: float | None = None, no_redirect: bool = False):
        self.model, self.url, self.key = model, url.rstrip("/"), key
        self.key_lookup, self.timeout, self.no_redirect = key_lookup, timeout, no_redirect
        self.name = f"openai:{model}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        key = self.key_lookup() if self.key_lookup is not None else self.key
        if key and self.key_lookup is not None and not _can_send_bearer(self.url):
            raise ValueError("Hermes embedding credentials require HTTPS or a loopback endpoint")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = _post(f"{self.url}/embeddings", {"model": self.model, "input": list(texts)}, headers,
                     timeout=self.timeout, no_redirect=self.no_redirect)
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


class InvalidEmbeddingBatch(ValueError):
    def __init__(self, message: str, *, has_vectors: bool):
        super().__init__(message)
        self.has_vectors = has_vectors


def pack_batch(vectors: Sequence[Sequence[float]], expected: int) -> list[bytes]:
    if len(vectors) != expected:
        raise InvalidEmbeddingBatch(f"embedding vector count mismatch: expected {expected}, got {len(vectors)}",
                                    has_vectors=any(vectors))
    if not all(vectors):
        raise InvalidEmbeddingBatch("incomplete embedding response: a vector is empty",
                                    has_vectors=any(vectors))
    return [pack(vector) for vector in vectors]


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


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, docs: Sequence[str]) -> list[float]: ...


class FastEmbedReranker:
    """Optional local ONNX cross-encoder reranker (requires `pip install fastembed`)."""

    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # type: ignore

        self.model = model
        self.name = f"fastembed:{model}"
        self._enc = TextCrossEncoder(model_name=model)

    def rerank(self, query: str, docs: Sequence[str]) -> list[float]:
        if not docs:
            return []
        return [float(s) for s in self._enc.rerank(query, list(docs))]


def reranker_from_settings(kind: str, model: str = "") -> Reranker | None:
    kind = kind.strip().lower()
    if not kind or kind == "none":
        return None
    if kind == "fastembed":
        return FastEmbedReranker(model or "Xenova/ms-marco-MiniLM-L-6-v2")
    raise ValueError(f"unknown TERESIS_RERANK provider: {kind!r}")


def reranker_from_env() -> Reranker | None:
    return reranker_from_settings(os.environ.get("TERESIS_RERANK", ""), os.environ.get("TERESIS_RERANK_MODEL", ""))
