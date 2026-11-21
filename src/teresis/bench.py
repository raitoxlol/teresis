"""Retrieval benchmark: quality (hit@k, MRR, leaks) with distractors, ablations, and latency at scale.

Run: `teresis bench` or `python -m teresis.bench`.
Categories are reported separately so weak spots (e.g. paraphrase without embeddings) stay visible.
"""

from __future__ import annotations

import json
import random
import sqlite3
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import text as T
from .store import DAY, MemoryStore, Weights, scope_chain

NOW = 1_800_000_000.0

# label, scope, content, days_ago, extras
MEMORIES: list[tuple[str, str, str, float, dict]] = [
    ("editor_old", "user", "User prefers VS Code as their editor", 200, {"key": "user.editor", "kind": "preference"}),
    ("editor_new", "user", "User switched to Neovim as their editor", 10, {"key": "user.editor", "kind": "preference"}),
    ("tz", "user", "User is based in Tokyo, timezone JST (UTC+9)", 90, {"kind": "fact"}),
    ("tone", "user", "User dislikes apologetic filler; wants terse, direct answers", 40, {"kind": "preference", "importance": 0.8}),
    ("shell", "user", "User's default shell is zsh with starship prompt", 60, {"kind": "preference"}),
    ("pkgmgr", "user", "Always use pnpm, never npm or yarn, for JavaScript projects", 30, {"kind": "preference", "importance": 0.9}),
    ("no_secrets", "global", "Never commit .env files or API keys to git repositories", 300, {"kind": "procedure", "importance": 1.0, "pinned": True}),
    ("commit_style", "global", "Commit messages use conventional commits: feat:, fix:, chore:", 120, {"kind": "procedure"}),
    ("db_old", "project/atlas", "Atlas stores data in MySQL 5.7", 400, {"key": "atlas.database"}),
    ("db_new", "project/atlas", "Atlas migrated its database to PostgreSQL 16 with pgvector", 20, {"key": "atlas.database"}),
    ("atlas_deploy", "project/atlas", "Atlas deployment runs through GitHub Actions to Fly.io on merge to main", 50, {"kind": "procedure"}),
    ("atlas_tests", "project/atlas", "Run Atlas tests with `make test`; integration tests need docker compose up", 45, {"kind": "procedure"}),
    ("atlas_flaky", "project/atlas", "The checkout e2e test is flaky because of a race in the payment webhook mock", 8, {"kind": "lesson"}),
    ("atlas_owner", "project/atlas", "Priya owns the billing service and approves schema changes", 70, {"kind": "fact"}),
    ("atlas_port", "project/atlas", "Atlas dev server listens on port 4321", 33, {"kind": "fact"}),
    ("atlas_redis", "project/atlas", "Session cache uses Redis with a 15 minute TTL", 25, {"kind": "fact"}),
    ("atlas_decision", "project/atlas", "Decided to use server-sent events instead of WebSockets for live order updates", 15, {"kind": "decision", "importance": 0.8}),
    ("atlas_incident", "project/atlas", "Incident 2026-03: OOM crash in the image resizer, fixed by streaming uploads", 120, {"kind": "event"}),
    ("atlas_incident2", "project/atlas", "Incident 2026-10: image resizer OOM again after a library upgrade; pinned sharp to 0.33", 5, {"kind": "event"}),
    ("atlas_k8s", "project/atlas", "Kubernetes manifests live in infra/k8s and are applied by Argo CD", 80, {"kind": "fact"}),
    ("helios_db", "project/helios", "Helios uses SQLite with Litestream replication to S3", 30, {"key": "helios.database"}),
    ("helios_deploy", "project/helios", "Helios deploys manually with `just release` from a tagged commit", 35, {"kind": "procedure"}),
    ("helios_port", "project/helios", "Helios dev server listens on port 8080", 40, {"kind": "fact"}),
    ("helios_lang", "project/helios", "Helios backend is written in Rust using axum and tokio", 60, {"kind": "fact"}),
    ("helios_lint", "project/helios", "Run cargo clippy with -D warnings before every pull request", 22, {"kind": "procedure"}),
    ("agent_note", "project/atlas/agent-reviewer", "Reviewer agent should flag any SQL built with string concatenation", 12, {"kind": "procedure"}),
    ("tmp_branch", "project/atlas", "Currently working on branch feat/refund-flow", 1, {"kind": "event", "ttl_days": 7}),
    ("expired", "project/atlas", "Temporary freeze on deployments during the audit", 40, {"kind": "event", "ttl_days": 14}),
    ("coffee", "user", "User drinks oat milk flat whites, no sugar", 150, {"kind": "preference"}),
    ("meeting", "user", "Weekly planning meeting is Monday 10:00 JST", 55, {"kind": "fact"}),
    ("kubectl", "global", "Use kubectx and kubens to switch Kubernetes contexts safely", 100, {"kind": "procedure"}),
    ("backup", "global", "Nightly backups run at 03:00 via restic to Backblaze B2", 75, {"kind": "fact"}),
    ("gpu", "global", "The workstation GPU is an RTX 4090 with 24 GB VRAM", 65, {"kind": "fact"}),
    ("python_ver", "global", "Default Python version across projects is 3.12, managed with uv", 28, {"kind": "preference"}),
]

# query, scope, gold labels (any counts), forbidden labels, category
QUERIES: list[tuple[str, str, list[str], list[str], str]] = [
    ("what editor does the user use", "user", ["editor_new"], ["editor_old"], "supersession"),
    ("which database does atlas use", "project/atlas", ["db_new"], ["db_old", "helios_db"], "supersession"),
    ("atlas mysql", "project/atlas", ["db_new"], ["db_old"], "supersession"),
    ("what timezone is the user in", "user", ["tz"], [], "exact"),
    ("how to run atlas tests", "project/atlas", ["atlas_tests"], [], "exact"),
    ("redis session cache ttl", "project/atlas", ["atlas_redis"], [], "exact"),
    ("who owns billing", "project/atlas", ["atlas_owner"], [], "exact"),
    ("argo cd kubernetes manifests", "project/atlas", ["atlas_k8s"], [], "exact"),
    ("restic backups", "global", ["backup"], [], "exact"),
    ("deploying atlas", "project/atlas", ["atlas_deploy"], ["helios_deploy"], "morphology"),
    ("migrations of the database", "project/atlas", ["db_new"], ["db_old"], "morphology"),
    ("flakiness in checkout tests", "project/atlas", ["atlas_flaky"], [], "morphology"),
    ("crashes in the image resizer", "project/atlas", ["atlas_incident2", "atlas_incident"], [], "morphology"),
    ("postgress", "project/atlas", ["db_new"], [], "typo"),
    ("kubernetis manifests", "project/atlas", ["atlas_k8s"], [], "typo"),
    ("websocket decision", "project/atlas", ["atlas_decision"], [], "typo"),
    ("litstream replication", "project/helios", ["helios_db"], [], "typo"),
    ("clipy warnings", "project/helios", ["helios_lint"], [], "typo"),
    ("dev server port", "project/atlas", ["atlas_port"], ["helios_port"], "isolation"),
    ("dev server port", "project/helios", ["helios_port"], ["atlas_port"], "isolation"),
    ("how do we deploy", "project/helios", ["helios_deploy"], ["atlas_deploy"], "isolation"),
    ("database", "project/helios", ["helios_db"], ["db_new", "db_old"], "isolation"),
    ("never commit secrets api keys", "project/atlas", ["no_secrets"], [], "inheritance"),
    ("commit message format", "project/helios", ["commit_style"], [], "inheritance"),
    ("SQL string concatenation", "project/atlas/agent-reviewer", ["agent_note"], [], "inheritance"),
    ("which package manager for javascript", "user", ["pkgmgr"], [], "exact"),
    ("latest image resizer incident", "project/atlas", ["atlas_incident2"], [], "recency"),
    ("what branch am I on", "project/atlas", ["tmp_branch"], [], "recency"),
    ("deployment freeze", "project/atlas", [], ["expired"], "expiry"),
    ("how should I phrase replies to the user", "user", ["tone"], [], "paraphrase"),
    ("graphics card memory", "global", ["gpu"], [], "paraphrase"),
    ("what coffee order", "user", ["coffee"], [], "paraphrase"),
    ("live updates transport", "project/atlas", ["atlas_decision"], [], "paraphrase"),
    ("where do I live", "user", ["tz"], [], "paraphrase"),
    ("javascript dependency installer", "user", ["pkgmgr"], [], "paraphrase"),
]

_VOCAB = (
    "service module config retry cache team meeting ticket release branch review docs api endpoint queue worker "
    "metric alert dashboard latency budget roadmap sprint customer invoice report schema migration index token "
    "session login build pipeline container image cluster node volume secret rotation script cron job backup "
    "logging trace span profile benchmark feature flag rollout experiment design mockup copy onboarding email "
    "notification webhook payment refund order cart search ranking model prompt dataset label eval storage bucket"
).split()


def _distractor(rng: random.Random) -> str:
    words = rng.sample(_VOCAB, rng.randint(6, 12))
    return f"Note {rng.randint(1, 99999)}: " + " ".join(words)


def build_store(path: Path, weights: Weights | None, distractors: int, seed: int = 7) -> tuple[MemoryStore, dict[str, str]]:
    clock = {"t": NOW}
    store = MemoryStore(path, embedder="env", weights=weights, clock=lambda: clock["t"])
    rng = random.Random(seed)
    scopes = ["global", "user", "project/atlas", "project/helios", "project/misc"]
    for i in range(distractors):
        clock["t"] = NOW - rng.uniform(0, 365) * DAY
        store.remember(_distractor(rng), scope=rng.choice(scopes), kind="note")
    labels: dict[str, str] = {}
    for label, scope, content, days, ex in sorted(MEMORIES, key=lambda m: -m[3]):
        clock["t"] = NOW - days * DAY
        r = store.remember(content, scope=scope, **ex)
        labels[label] = r.id
    clock["t"] = NOW
    return store, labels


@dataclass
class Result:
    name: str
    by_cat: dict[str, dict[str, float]]
    overall: dict[str, float]


def evaluate(name: str, search, labels: dict[str, str]) -> Result:
    inv = {v: k for k, v in labels.items()}
    rows: dict[str, list[tuple[float, float, float, float]]] = {}
    for query, scope, gold, forbidden, cat in QUERIES:
        got = [inv.get(mid, "_") for mid in search(query, scope)]
        top5 = got[:5]
        rank = next((i + 1 for i, g in enumerate(got) if g in gold), None)
        hit1 = 1.0 if (rank == 1 or (not gold and True)) else 0.0
        hit5 = 1.0 if (rank is not None and rank <= 5) or not gold else 0.0
        rr = 1.0 / rank if rank else (1.0 if not gold else 0.0)
        leak = 1.0 if any(f in top5 for f in forbidden) else 0.0
        rows.setdefault(cat, []).append((hit1, hit5, rr, leak))

    def agg(rs):
        return {
            "n": len(rs),
            "hit@1": statistics.mean(r[0] for r in rs),
            "hit@5": statistics.mean(r[1] for r in rs),
            "mrr": statistics.mean(r[2] for r in rs),
            "leak@5": statistics.mean(r[3] for r in rs),
        }

    return Result(name, {c: agg(rs) for c, rs in rows.items()}, agg([r for rs in rows.values() for r in rs]))


def naive_search(db: Path):
    """Baseline: what simple memory tools do - substring match on any word, newest first, no supersession."""
    conn = sqlite3.connect(db)

    def search(query: str, scope: str) -> list[str]:
        toks = T.tokens(query) or T.tokens(query, keep_stopwords=True)
        if not toks:
            return []
        chain = scope_chain(scope)
        where = " OR ".join("lower(content) LIKE ?" for _ in toks)
        sql = (f"SELECT id FROM memories WHERE deleted_at IS NULL AND scope IN ({','.join('?' * len(chain))}) "
               f"AND ({where}) ORDER BY created_at DESC LIMIT 10")
        return [r[0] for r in conn.execute(sql, [*chain, *[f"%{t}%" for t in toks]])]

    return search


def quality(distractors: int = 2000) -> list[Result]:
    results = []
    configs = {
        "teresis (full)": Weights(),
        "teresis w/o trigram": Weights(trigram=0.0),
        "teresis w/o recency+importance": Weights(recency=0.0, importance=0.0, access=0.0),
    }
    with tempfile.TemporaryDirectory() as d:
        for name, w in configs.items():
            path = Path(d) / f"{len(results)}.db"
            store, labels = build_store(path, w, distractors)
            results.append(evaluate(name, lambda q, s: [m.id for m in store.recall(q, scope=s, k=10, touch=False)], labels))
            if name == "teresis (full)":
                results.append(evaluate("naive LIKE baseline", naive_search(path), labels))
            store.close()
    return results


def latency(scale: int = 10000) -> dict[str, float]:
    rng = random.Random(11)
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(Path(d) / "lat.db", embedder="env")
        t0 = time.perf_counter()
        for _ in range(scale):
            store.remember(_distractor(rng), scope=rng.choice(["global", "project/a", "project/b"]), kind="note")
        write_s = time.perf_counter() - t0
        qs = [" ".join(rng.sample(_VOCAB, 3)) for _ in range(200)]
        times = []
        for q in qs:
            t = time.perf_counter()
            store.recall(q, scope="project/a", k=8, touch=False)
            times.append((time.perf_counter() - t) * 1000)
        times.sort()
        size = (Path(d) / "lat.db").stat().st_size
        store.close()
    return {
        "memories": scale,
        "writes_per_s": round(scale / write_s, 1),
        "recall_p50_ms": round(times[len(times) // 2], 2),
        "recall_p95_ms": round(times[int(len(times) * 0.95)], 2),
        "db_mb": round(size / 1e6, 2),
    }


def main(scale: int = 10000, as_json: bool = False) -> int:
    res = quality()
    lat = latency(scale)
    if as_json:
        print(json.dumps({"quality": [r.__dict__ for r in res], "latency": lat}, indent=2))
        return 0
    cats = list(res[0].by_cat)
    print(f"Quality — {len(QUERIES)} queries, {len(MEMORIES)} target memories, 2000 distractors\n")
    head = f"{'system':32} {'hit@1':>6} {'hit@5':>6} {'MRR':>6} {'leak@5':>7}"
    print(head)
    print("-" * len(head))
    for r in res:
        o = r.overall
        print(f"{r.name:32} {o['hit@1']:6.2f} {o['hit@5']:6.2f} {o['mrr']:6.2f} {o['leak@5']:7.2f}")
    print("\nhit@1 by category")
    print(f"{'system':32} " + " ".join(f"{c[:10]:>10}" for c in cats))
    for r in res:
        print(f"{r.name:32} " + " ".join(f"{r.by_cat[c]['hit@1']:10.2f}" for c in cats))
    print("\nLatency")
    for k, v in lat.items():
        print(f"  {k:16} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
