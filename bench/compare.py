"""Cross-provider retrieval benchmark on LongMemEval_s (Wu et al., 2024, ICLR 2025).

Every system ingests the same units (one user/assistant round, max 2000 chars) of each question's
~50-session chat history, then answers the question with a ranked list. Units map back to sessions;
we score session-level retrieval like the LongMemEval paper: recall_any@k, recall_all@k, NDCG@10.
Abstention questions (no evidence session) are skipped.

    python bench/compare.py --data .data/longmemeval_s.json --system teresis --limit 0 --out .data/results
    systems: naive | teresis | teresis-emb | holographic | mem0

`holographic` loads the plugin from a Hermes checkout (--hermes, default ~/.hermes/hermes-agent).
`mem0` needs `pip install mem0ai ollama` and Ollama (model from TERESIS_EMBED_MODEL, dims BENCH_EMBED_DIMS); it runs with infer=False (no LLM).
`teresis-emb` needs TERESIS_EMBED=ollama TERESIS_EMBED_MODEL=<model>.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
import types
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UNIT_CHARS = 2000
TOPN = 50


def parse_date(s: str) -> float:
    return datetime.strptime(s.split(" (")[0] + " " + s.split(") ")[-1], "%Y/%m/%d %H:%M").timestamp()


def units_for(q: dict) -> list[tuple[str, str, float]]:
    """(session_id, text, unix_time) per user/assistant round."""
    out = []
    for sid, date, sess in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]):
        t = parse_date(date)
        i = 0
        while i < len(sess):
            turn = sess[i]
            text = f"{turn['role']}: {turn['content']}"
            if turn["role"] == "user" and i + 1 < len(sess) and sess[i + 1]["role"] == "assistant":
                text += f"\nassistant: {sess[i + 1]['content']}"
                i += 1
            i += 1
            out.append((sid, text[:UNIT_CHARS], t))
    return out


# ----------------------------------------------------------------------------- adapters
class Naive:
    name = "naive LIKE"

    def __init__(self, tmp: Path):
        self.c = sqlite3.connect(":memory:")
        self.c.execute("CREATE TABLE u(id INTEGER PRIMARY KEY, sid TEXT, text TEXT, t REAL)")

    def add_all(self, units):
        self.c.executemany("INSERT INTO u(sid, text, t) VALUES (?,?,?)", units)

    def search(self, query, now):
        from teresis.text import tokens
        toks = tokens(query) or tokens(query, keep_stopwords=True)
        where = " OR ".join("lower(text) LIKE ?" for _ in toks) or "1"
        return [r[0] for r in self.c.execute(f"SELECT sid FROM u WHERE {where} ORDER BY t DESC LIMIT {TOPN}",
                                             [f"%{t}%" for t in toks])]

    def close(self):
        self.c.close()


class Teresis:
    name = "teresis"

    def __init__(self, tmp: Path, embed: bool = False):
        from teresis import MemoryStore
        self.clock = {"t": 0.0}
        self.embed = embed
        self.s = MemoryStore(tmp / "m.db", embedder=None, clock=lambda: self.clock["t"])
        if embed:
            from teresis.embed import from_env
            self.emb = from_env()
            if self.emb is None:
                raise SystemExit("teresis-emb needs TERESIS_EMBED / TERESIS_EMBED_MODEL")
        self.sid = {}

    def add_all(self, units):
        for sid, text, t in sorted(units, key=lambda u: u[2]):
            self.clock["t"] = t
            r = self.s.remember(text, scope="bench", kind="episode")
            self.sid.setdefault(r.id, sid)
        if self.embed:
            self.s.embedder = self.emb
            self.s.embed_missing(batch=16)

    def search(self, query, now):
        self.clock["t"] = now
        return [self.sid[m.id] for m in self.s.recall(query, scope="bench", k=TOPN, touch=False)]

    def close(self):
        self.s.close()


class Holographic:
    name = "holographic (Hermes)"

    def __init__(self, tmp: Path, hermes: Path):
        if str(hermes) not in sys.path:
            sys.path.insert(0, str(hermes))  # for hermes_state_wal
        pkg_dir = hermes / "plugins" / "memory" / "holographic"
        if "holo" not in sys.modules:  # load submodules without the plugin __init__ (it needs the agent runtime)
            pkg = types.ModuleType("holo")
            pkg.__path__ = [str(pkg_dir)]
            sys.modules["holo"] = pkg
            for mod in ("holographic", "store", "retrieval"):
                spec = importlib.util.spec_from_file_location(f"holo.{mod}", pkg_dir / f"{mod}.py")
                m = importlib.util.module_from_spec(spec)
                sys.modules[f"holo.{mod}"] = m
                spec.loader.exec_module(m)
        from holo.retrieval import FactRetriever
        from holo.store import MemoryStore
        # plugin defaults: default_trust 0.5, min_trust 0.3, hrr_dim 1024, hrr_weight 0.3
        self.store = MemoryStore(db_path=str(tmp / "h.db"), default_trust=0.5, hrr_dim=1024)
        self.ret = FactRetriever(store=self.store, hrr_dim=1024, hrr_weight=0.3, temporal_decay_half_life=0)
        self.sid = {}

    def add_all(self, units):
        for sid, text, t in units:
            self.sid.setdefault(self.store.add_fact(text), sid)

    def search(self, query, now):
        return [self.sid[r["fact_id"]] for r in self.ret.search(query, min_trust=0.3, limit=TOPN)]

    def close(self):
        self.store.close()


class Mem0:
    name = "mem0 OSS (infer=False)"
    _m = None

    def __init__(self, tmp: Path):
        os.environ.setdefault("MEM0_TELEMETRY", "False")  # mem0 phones home to PostHog by default
        from mem0 import Memory
        if Mem0._m is None:
            url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
            model = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
            dims = int(os.environ.get("BENCH_EMBED_DIMS", "384"))
            Mem0._dir = Path(tempfile.mkdtemp(prefix="mem0bench"))
            Mem0._m = Memory.from_config({
                "embedder": {"provider": "ollama", "config": {"model": model, "ollama_base_url": url}},
                "llm": {"provider": "ollama", "config": {"model": "qwen2.5vl:3b", "ollama_base_url": url}},
                "vector_store": {"provider": "qdrant", "config": {
                    "collection_name": "bench", "embedding_model_dims": dims, "path": str(Mem0._dir / "q"),
                    "on_disk": True}},
                "history_db_path": str(Mem0._dir / "hist.db"),
            })
        self.m = Mem0._m
        self.name = f"mem0 OSS (infer=False, {os.environ.get('TERESIS_EMBED_MODEL', 'all-minilm')})"
        self.user = f"q{random.getrandbits(48):x}"

    def _install_cache(self):
        """Pre-compute the same Ollama embeddings in batches and serve them to mem0's own embedder.
        Storage and search are mem0's unchanged code; a cache miss falls back to mem0's normal call."""
        if getattr(Mem0, "_cache", None) is not None:
            return
        from teresis.embed import OllamaEmbedder
        Mem0._cache, Mem0._misses = {}, 0
        Mem0._batch = OllamaEmbedder(os.environ.get("TERESIS_EMBED_MODEL", "all-minilm"),
                                     os.environ.get("OLLAMA_URL", "http://localhost:11434"))
        emb = self.m.embedding_model
        orig = emb.embed

        def cached(text, memory_action=None):
            v = Mem0._cache.get(text) if isinstance(text, str) else None
            if v is None:
                Mem0._misses += 1
                return orig(text, memory_action)
            return v

        emb.embed = cached

    def add_all(self, units):
        self._install_cache()
        texts = [t for _, t, _ in units]
        vecs = _embed_batched(Mem0._batch, texts, batch=16)
        for t, v in zip(texts, vecs):
            Mem0._cache[t] = v
        for sid, text, t in units:
            self.m.add([{"role": "user", "content": text}], user_id=self.user, infer=False, metadata={"sid": sid})
        Mem0._cache.clear()

    def search(self, query, now):
        res = self.m.search(query, filters={"user_id": self.user}, top_k=TOPN)
        res = res.get("results", res) if isinstance(res, dict) else res
        return [r["metadata"]["sid"] for r in res]

    def close(self):
        pass



class SQLiteFTS5:
    name = "SQLite FTS5 (BM25)"

    def __init__(self, tmp: Path):
        from teresis.text import tokens
        self._tokens = tokens
        self.c = sqlite3.connect(str(tmp / "fts.db"))
        self.c.execute("CREATE VIRTUAL TABLE u USING fts5(sid UNINDEXED, text, tokenize='porter unicode61')")

    def add_all(self, units):
        self.c.executemany("INSERT INTO u(sid, text) VALUES (?,?)", [(sid, text) for sid, text, _ in units])
        self.c.commit()

    def search(self, query, now):
        toks = self._tokens(query) or self._tokens(query, keep_stopwords=True)
        q = " OR ".join(f'"{t}"' for t in toks if t.isalnum())
        if not q:
            return []
        try:
            return [r[0] for r in self.c.execute(f"SELECT sid FROM u WHERE u MATCH ? ORDER BY bm25(u) LIMIT {TOPN}", (q,))]
        except sqlite3.OperationalError:
            return []

    def close(self):
        self.c.close()


def _ollama_embedder():
    from teresis.embed import OllamaEmbedder
    return OllamaEmbedder(
        os.environ.get("TERESIS_EMBED_MODEL", "all-minilm"),
        os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    )


_EMBED_CACHE_CONN = None


def _get_embed_cache():
    global _EMBED_CACHE_CONN
    path = os.environ.get("BENCH_EMBED_CACHE")
    if not path:
        return None
    if _EMBED_CACHE_CONN is None:
        _EMBED_CACHE_CONN = sqlite3.connect(path)
        _EMBED_CACHE_CONN.execute(
            "CREATE TABLE IF NOT EXISTS emb(k TEXT PRIMARY KEY, v BLOB)"
        )
    return _EMBED_CACHE_CONN


def _embed_batched(emb, texts: list[str], batch: int = 16) -> list[list[float]]:
    import hashlib, struct
    conn = _get_embed_cache()
    if conn is None:
        out: list[list[float]] = []
        for i in range(0, len(texts), batch):
            out.extend(emb.embed(texts[i:i + batch]))
        return out
    model = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
    keys = [hashlib.sha256(f"{model}::{t}".encode("utf-8", "replace")).hexdigest() for t in texts]
    found: dict[str, list[float]] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for k, blob in conn.execute(f"SELECT k, v FROM emb WHERE k IN ({ph})", chunk):
            n = len(blob) // 4
            found[k] = list(struct.unpack(f"<{n}f", blob))
    missing_idx = [i for i, k in enumerate(keys) if k not in found]
    if missing_idx:
        # deduplicate missing keys within this batch
        uniq_pos = []
        seen = set()
        for idx in missing_idx:
            if keys[idx] not in seen:
                seen.add(keys[idx])
                uniq_pos.append(idx)
        to_write = []
        for i in range(0, len(uniq_pos), batch):
            idxs = uniq_pos[i:i + batch]
            vecs = emb.embed([texts[j] for j in idxs])
            for j, v in zip(idxs, vecs):
                found[keys[j]] = v
                to_write.append((keys[j], struct.pack(f"<{len(v)}f", *v)))
        conn.executemany("INSERT OR IGNORE INTO emb(k, v) VALUES (?,?)", to_write)
        conn.commit()
    return [found[k] for k in keys]


class Chroma:
    def __init__(self, tmp: Path):
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        import chromadb
        self.model = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
        self.name = f"ChromaDB ({self.model})"
        self.emb = _ollama_embedder()
        self.client = chromadb.PersistentClient(path=str(tmp / "chroma"))
        self.col = self.client.create_collection("bench", metadata={"hnsw:space": "cosine"})

    def add_all(self, units):
        if not units:
            return
        texts = [t for _, t, _ in units]
        vecs = _embed_batched(self.emb, texts)
        for i in range(0, len(units), 500):
            sl = slice(i, i + 500)
            self.col.add(
                ids=[str(j) for j in range(i, min(i + 500, len(units)))],
                embeddings=vecs[sl],
                metadatas=[{"sid": sid} for sid, _, _ in units[sl]],
                documents=texts[sl],
            )

    def search(self, query, now):
        qv = self.emb.embed([query])[0]
        n = min(TOPN, self.col.count())
        if n <= 0:
            return []
        res = self.col.query(query_embeddings=[qv], n_results=n)
        metas = (res.get("metadatas") or [[]])[0]
        return [m["sid"] for m in metas]

    def close(self):
        pass


class LanceDBHybrid:
    def __init__(self, tmp: Path):
        import lancedb
        from lancedb.rerankers import RRFReranker
        self.model = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
        self.name = f"LanceDB hybrid (BM25 + {self.model})"
        self.emb = _ollama_embedder()
        self.db = lancedb.connect(str(tmp / "lance"))
        self.reranker = RRFReranker()
        self.tbl = None

    def add_all(self, units):
        if not units:
            return
        texts = [t for _, t, _ in units]
        vecs = _embed_batched(self.emb, texts)
        rows = [{"sid": sid, "text": text, "vector": vec} for (sid, text, _), vec in zip(units, vecs)]
        self.tbl = self.db.create_table("mem", rows)
        self.tbl.create_fts_index("text", replace=True)

    def search(self, query, now):
        if self.tbl is None:
            return []
        qv = self.emb.embed([query])[0]
        clean_q = " ".join(w for w in query.split() if any(c.isalnum() for c in w))
        try:
            if clean_q:
                res = (self.tbl.search(query_type="hybrid")
                       .vector(qv).text(clean_q).rerank(self.reranker).limit(TOPN).to_list())
            else:
                res = self.tbl.search(qv).limit(TOPN).to_list()
        except Exception:
            res = self.tbl.search(qv).limit(TOPN).to_list()
        return [r["sid"] for r in res]

    def close(self):
        pass


class Mem0Hybrid(Mem0):
    def __init__(self, tmp: Path):
        super().__init__(tmp)
        model = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
        self.name = f"mem0 OSS hybrid (infer=False, BM25 + spaCy + {model})"
        if not getattr(self.m.vector_store, "_has_bm25_slot", False):
            raise SystemExit("mem0-hybrid requires fastembed BM25 slot in Qdrant (run under .venv-bench312)")


class TotalAgentMemory:
    name = "total-agent-memory 14.10 (FastEmbed + FTS + RRF, no reranker)"
    _patched_loader = False

    def __init__(self, tmp: Path):
        import total_agent_memory.server as tam_srv
        tam_src = str(Path(tam_srv.__file__).parent.parent / "src")
        if tam_src not in sys.path:
            sys.path.insert(0, tam_src)
        if not TotalAgentMemory._patched_loader:
            import memory_core.fastembed_loader as fel
            _orig_load = fel.load_model
            _model_cache = {}
            def _cached_load(cls, model_name, *args, **kwargs):
                key = (cls, model_name)
                if key not in _model_cache:
                    _model_cache[key] = _orig_load(cls, model_name, *args, **kwargs)
                return _model_cache[key]
            fel.load_model = _cached_load
            TotalAgentMemory._patched_loader = True
        import cli_store
        import server as tam_server
        self._ctx = cli_store.open_store(tmp / "tam")
        self.store = self._ctx.__enter__()
        worker = getattr(self.store, "_enrich_worker", None)
        if worker is not None:
            worker.stop()
        self.recall = tam_server.Recall(self.store)

    def add_all(self, units):
        vecs = None
        fe = getattr(self.store, "fastembed", None)
        if fe is not None and units:
            vecs = [v.tolist() for v in fe.embed([t for _, t, _ in units], batch_size=32)]
        for i, (sid, text, _) in enumerate(units):
            self.store.save_knowledge(
                sid, text, "fact", project="bench",
                skip_dedup=True, skip_quality=True,
                embedding=vecs[i] if vecs is not None else None,
            )

    def search(self, query, now):
        hits = self.recall.search(query, project="bench", limit=TOPN, record_usage=False, defer_cross_rerank=True)
        items = []
        for bucket in (hits.get("results") or {}).values():
            if isinstance(bucket, list):
                items.extend(bucket)
        items.sort(key=lambda r: float(r.get("score") or r.get("rrf_score") or 0.0), reverse=True)
        return [r["session_id"] for r in items if r.get("session_id")]

    def close(self):
        try:
            self.recall.close()
        finally:
            self._ctx.__exit__(None, None, None)


def make(system: str, tmp: Path, hermes: Path):
    if system == "naive":
        return Naive(tmp)
    if system == "teresis":
        return Teresis(tmp)
    if system == "teresis-emb":
        a = Teresis(tmp, embed=True)
        a.name = f"teresis + {os.environ.get('TERESIS_EMBED_MODEL')}"
        return a
    if system == "holographic":
        return Holographic(tmp, hermes)
    if system == "mem0":
        return Mem0(tmp)
    if system == "mem0-hybrid":
        return Mem0Hybrid(tmp)
    if system == "fts5":
        return SQLiteFTS5(tmp)
    if system == "chroma":
        return Chroma(tmp)
    if system == "lancedb":
        return LanceDBHybrid(tmp)
    if system == "tam":
        return TotalAgentMemory(tmp)
    raise SystemExit(f"unknown system {system}")


# ----------------------------------------------------------------------------- scoring
def session_ranking(sids: list[str]) -> list[str]:
    return list(dict.fromkeys(sids))


def score(ranked: list[str], gold: set[str]) -> dict[str, float]:
    def r_any(k):
        return float(any(s in gold for s in ranked[:k]))

    def r_all(k):
        return float(gold <= set(ranked[:k]))

    dcg = sum(1 / math.log2(i + 2) for i, s in enumerate(ranked[:10]) if s in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return {"recall_any@5": r_any(5), "recall_any@10": r_any(10), "recall_all@10": r_all(10),
            "ndcg@10": dcg / idcg if idcg else 0.0}


def select(data: list[dict], limit: int, seed: int = 13) -> list[dict]:
    qs = [q for q in data if not q["question_id"].endswith("_abs") and q.get("answer_session_ids")]
    if not limit or limit >= len(qs):
        return qs
    by_type = defaultdict(list)
    for q in qs:
        by_type[q["question_type"]].append(q)
    rng = random.Random(seed)
    out = []
    for t, items in sorted(by_type.items()):  # stratified by question type
        n = max(1, round(limit * len(items) / len(qs)))
        out += rng.sample(items, min(n, len(items)))
    return out[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--limit", type=int, default=0, help="stratified subset size (0 = all non-abstention)")
    ap.add_argument("--out", default=".data/results")
    ap.add_argument("--hermes", default=str(Path.home() / ".hermes" / "hermes-agent"))
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text())
    qs = select(data, args.limit)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, ingest_s, query_ms = [], 0.0, []
    name = None
    for i, q in enumerate(qs):
        tmp = Path(tempfile.mkdtemp(prefix="lme"))
        try:
            sysm = make(args.system, tmp, Path(args.hermes))
            name = sysm.name
            units = units_for(q)
            t0 = time.perf_counter()
            sysm.add_all(units)
            ingest_s += time.perf_counter() - t0
            t0 = time.perf_counter()
            ranked = session_ranking(sysm.search(q["question"], parse_date(q["question_date"])))
            query_ms.append((time.perf_counter() - t0) * 1000)
            sysm.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        rows.append({"id": q["question_id"], "type": q["question_type"],
                     **score(ranked, set(q["answer_session_ids"]))})
        if (i + 1) % 25 == 0:
            print(f"[{args.system}] {i + 1}/{len(qs)} recall_any@5="
                  f"{statistics.mean(r['recall_any@5'] for r in rows):.3f}", flush=True)

    metrics = ["recall_any@5", "recall_any@10", "recall_all@10", "ndcg@10"]
    summary = {
        "system": name, "key": args.system, "n": len(rows), "limit": args.limit,
        **{m: round(statistics.mean(r[m] for r in rows), 4) for m in metrics},
        "by_type": {t: {m: round(statistics.mean(r[m] for r in rows if r["type"] == t), 4) for m in metrics}
                    | {"n": sum(r["type"] == t for r in rows)} for t in sorted({r["type"] for r in rows})},
        "ingest_units_per_s": round(sum(len(units_for(q)) for q in qs) / ingest_s, 1) if ingest_s else None,
        "query_p50_ms": round(sorted(query_ms)[len(query_ms) // 2], 2) if query_ms else None,
    }
    tag = f"{args.system}-n{args.limit or 'all'}"
    (out_dir / f"{tag}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
