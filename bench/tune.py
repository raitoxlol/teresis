"""Tune teresis's retrieval weights on a LongMemEval dev split, then score the untouched test split.

Stores are built once per question (ingest + embeddings) and cached under .data/stores/<split>/.
Weights only affect query time, so every grid point is a cheap re-query.

    python bench/tune.py build --split dev        # 80 questions disjoint from the test split
    python bench/tune.py build --split test       # the 100-question split used in README/chart
    python bench/tune.py grid  --split dev        # grid search, prints the top configs
    python bench/tune.py eval  --split test --weights '{"vector": 2.0}'

Objective: mean of recall_all@10 and NDCG@10 (recall_any@5 is saturated on LongMemEval_s).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import statistics
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

import compare as C  # noqa: E402
from teresis import MemoryStore, Weights  # noqa: E402
from teresis.embed import OllamaEmbedder  # noqa: E402

DATA = ROOT / ".data" / "longmemeval_s.json"
STORES = ROOT / ".data" / "stores"
MODEL = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")


def splits() -> dict[str, list[dict]]:
    data = json.loads(DATA.read_text())
    test = C.select(data, 100)  # identical to the README/chart split (seed 13)
    test_ids = {q["question_id"] for q in test}
    rest = [q for q in data if q["question_id"] not in test_ids]
    dev = C.select(rest, 80, seed=7)
    assert not test_ids & {q["question_id"] for q in dev}
    return {"test": test, "dev": dev}


class CachedEmbedder:
    def __init__(self, inner):
        self.inner, self.name, self.cache = inner, inner.name, {}

    def embed(self, texts):
        missing = [t for t in texts if t not in self.cache]
        if missing:
            for t, v in zip(missing, self.inner.embed(missing)):
                self.cache[t] = v
        return [self.cache[t] for t in texts]


def build(split: str, shard: int, shards: int) -> None:
    out = STORES / split
    out.mkdir(parents=True, exist_ok=True)
    emb = OllamaEmbedder(MODEL)
    qs = splits()[split]
    for i, q in enumerate(qs):
        if i % shards != shard:
            continue
        path = out / f"{q['question_id']}.db"
        if path.exists() and path.with_suffix(".ok").exists():
            continue
        path.unlink(missing_ok=True)
        clock = {"t": 0.0}
        s = MemoryStore(path, embedder=None, clock=lambda: clock["t"])
        for sid, text, t in sorted(C.units_for(q), key=lambda u: u[2]):
            clock["t"] = t
            s.remember(text, scope="bench", kind="episode", source=sid)
        s.embedder = emb
        s.embed_missing(batch=16)
        s.close()
        path.with_suffix(".ok").write_text("ok")
        print(f"[build {split} {shard}] {i + 1}/{len(qs)}", flush=True)


def evaluate(split: str, w: Weights, embed: bool, qcache: dict) -> dict:
    rows = []
    emb = qcache.setdefault("_emb", CachedEmbedder(OllamaEmbedder(MODEL))) if embed else None
    for q in splits_cached()[split]:
        path = STORES / split / f"{q['question_id']}.db"
        clock = {"t": C.parse_date(q["question_date"])}
        s = MemoryStore(path, embedder=emb, weights=w, clock=lambda: clock["t"])
        mems = s.recall(q["question"], scope="bench", k=C.TOPN, touch=False)
        s.close()
        ranked = C.session_ranking([m.source for m in mems])
        rows.append({"type": q["question_type"], **C.score(ranked, set(q["answer_session_ids"]))})
    agg = {m: round(statistics.mean(r[m] for r in rows), 4) for m in ("recall_any@5", "recall_all@10", "ndcg@10")}
    agg["objective"] = round((agg["recall_all@10"] + agg["ndcg@10"]) / 2, 4)
    agg["n"] = len(rows)
    return agg


_SPLITS = None


def splits_cached():
    global _SPLITS
    if _SPLITS is None:
        _SPLITS = splits()
    return _SPLITS


def grid(split: str) -> None:
    base = Weights()
    qcache: dict = {}
    results = []
    lexical = [dict(trigram=t, recency=r, mmr=m)
               for t, r, m in itertools.product([0.0, 0.35, 0.6], [0.0, 0.15], [0.0, 0.3, 0.6])]
    semantic = [dict(vector=v, trigram=t, min_cosine=mc, mmr=m)
                for v, t, mc, m in itertools.product([1.0, 2.0, 3.0, 5.0], [0.0, 0.35], [0.0, 0.2], [0.0, 0.3, 0.6])]
    for mode, configs in (("lexical", lexical), ("embed", semantic)):
        for cfg in configs:
            w = replace(base, **cfg)
            r = evaluate(split, w, mode == "embed", qcache)
            results.append({"mode": mode, "cfg": cfg, **r})
            print(json.dumps(results[-1]), flush=True)
    for mode in ("lexical", "embed"):
        top = sorted((r for r in results if r["mode"] == mode), key=lambda r: -r["objective"])[:5]
        default = evaluate(split, base, mode == "embed", qcache)
        print(f"\n== {mode}: default objective {default['objective']}  {default}")
        for r in top:
            print(f"   {r['objective']}  {r['cfg']}  r_all={r['recall_all@10']} ndcg={r['ndcg@10']}")
    (ROOT / ".data" / f"grid-{split}.json").write_text(json.dumps(results, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "grid", "eval"])
    ap.add_argument("--split", default="dev")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--weights", default="{}")
    ap.add_argument("--embed", action="store_true")
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.split, args.shard, args.shards)
    elif args.cmd == "grid":
        grid(args.split)
    else:
        w = replace(Weights(), **json.loads(args.weights))
        print(json.dumps({"weights": asdict(w), **evaluate(args.split, w, args.embed, {})}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
