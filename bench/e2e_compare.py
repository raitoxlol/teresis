"""Head-to-head end-to-end agent memory benchmark (200 facts + 20 updates -> 100 questions).

Uses the exact 200-fact / 100-question scenarios and deterministic exact-match grader from
`bench/hermes_live.py` (40 direct, 20 paraphrase, 10 preference, 20 changed values where newest
must win and old is forbidden, 10 abstentions). Every arm uses the same answer LLM
(`gemini-3.5-flash-lite`, temperature 0) and deterministic grading (no LLM judge).

Arms:
  teresis       - Teresis (no model, 0 LLM calls on write) via Hermes MemoryProvider
  teresis-emb   - Teresis + local Ollama all-minilm (0 LLM calls on write)
  holographic   - Hermes holographic memory plugin (0 LLM calls on write)
  mem0-llm      - mem0 OSS 2.2.1 with infer=True (LLM extraction/reconciliation + BM25 + spaCy + all-minilm)
  honcho        - Self-hosted Honcho v3 stack (Postgres pgvector + Redis + LLM deriver + dialectic chat)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

import compare as C  # noqa: E402
import hermes_live as HL  # noqa: E402

MODEL = os.environ.get("E2E_LLM_MODEL", "gemini-3.5-flash-lite")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def answer_llm(question: str, context: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    sys_msg = (
        "Answer the user's question in one short sentence using ONLY the recalled memories below. "
        "If the memories contain an updated/newer value for the same item, give ONLY the newest value "
        "(do not mention the old superseded value). "
        "If the answer is not present in the memories, say 'I don't know.' Do not guess."
    )
    user_msg = f"Recalled memories:\n{context or '(none)'}\n\nQuestion: {question}"
    payload = {
        "model": MODEL,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
    }
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"{GEMINI_BASE}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:
            if attempt == 3:
                return f"ERROR: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return ""


def build_turns(seed: int = 42, limit: int = 0, suite: str = "scale") -> tuple[list[tuple[str, str]], list[dict]]:
    S = HL.scenarios(seed)["S"] if suite == "core" else HL.scenarios_scale(seed)["S"]
    if limit:
        S = S[:limit]
    r = random.Random(seed + 1)
    first = [s for s in S if s["tell"]]
    r.shuffle(first)
    # Ingest initial facts first, then updates later (chronological order)
    turns: list[tuple[str, str]] = []
    for s in first:
        turns.append((f"Remember this for later: {s['tell']}", "Got it, I'll remember that."))
    for s in S:
        if s.get("later"):
            turns.append((f"Remember this for later: {s['later']}", "Updated, I'll remember the new value."))
    order = [s for s in S if s.get("asked", True)]
    r.shuffle(order)
    return turns, order


# ----------------------------------------------------------------------------- arms
class TeresisArm:
    def __init__(self, tmp: Path, embed: bool = False):
        from teresis.hermes import TeresisMemoryProvider
        self.embed = embed
        self.name = "teresis + all-minilm" if embed else "teresis (no model)"
        cfg = {
            "db_path": str(tmp / "teresis.db"),
            "scope": "hermes/bench",
            "extra_scopes": "user",
            "prefetch_k": 8,
            "prefetch_budget_tokens": 1200,
            "capture_turns": True,
            "auto_extract": True,
        }
        if embed:
            cfg["embed"] = "ollama"
            cfg["embed_model"] = os.environ.get("TERESIS_EMBED_MODEL", "all-minilm")
        self.p = TeresisMemoryProvider(cfg)
        self.p.initialize("s0")
        self.write_llm_calls = 0

    def ingest(self, turns):
        for i, (u, a) in enumerate(turns):
            self.p.sync_turn(u, a, session_id=f"s{i}")

    def ask(self, question: str) -> tuple[str, float]:
        t0 = time.perf_counter()
        ctx = self.p.prefetch(question, session_id="ask")
        ret_ms = (time.perf_counter() - t0) * 1000.0
        return answer_llm(question, ctx), ret_ms

    def close(self):
        self.p.shutdown()


class HolographicArm:
    name = "holographic (Hermes plugin)"

    def __init__(self, tmp: Path, hermes_path: Path):
        self.ad = C.Holographic(tmp, hermes_path)
        self.texts: dict[str, str] = {}
        self.write_llm_calls = 0

    def ingest(self, turns):
        units = []
        for i, (u, _) in enumerate(turns):
            clean = u.removeprefix("Remember this for later: ").strip()
            sid = f"t{i}"
            self.texts[sid] = clean
            units.append((sid, clean, float(1_700_000_000 + i * 60)))
        self.ad.add_all(units)

    def ask(self, question: str) -> tuple[str, float]:
        t0 = time.perf_counter()
        sids = C.session_ranking(self.ad.search(question, 1_700_100_000.0))[:8]
        ctx = "\n".join(f"- {self.texts[s]}" for s in sids if s in self.texts)
        ret_ms = (time.perf_counter() - t0) * 1000.0
        return answer_llm(question, ctx), ret_ms

    def close(self):
        self.ad.close()


class Mem0LLMArm:
    name = f"mem0 OSS (infer=True, {MODEL} + BM25 + spaCy + all-minilm)"

    def __init__(self, tmp: Path):
        os.environ["MEM0_TELEMETRY"] = "False"
        os.environ.pop("OPENROUTER_API_KEY", None)
        from mem0 import Memory
        key = os.environ["GEMINI_API_KEY"]
        self.m = Memory.from_config({
            "embedder": {"provider": "ollama", "config": {
                "model": os.environ.get("TERESIS_EMBED_MODEL", "all-minilm"),
                "ollama_base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            }},
            "llm": {"provider": "openai", "config": {
                "model": MODEL,
                "api_key": key,
                "openai_base_url": f"{GEMINI_BASE}/",
                "temperature": 0.0,
            }},
            "vector_store": {"provider": "qdrant", "config": {
                "collection_name": "e2e_mem0",
                "embedding_model_dims": int(os.environ.get("BENCH_EMBED_DIMS", "384")),
                "path": str(tmp / "q"),
                "on_disk": True,
            }},
            "history_db_path": str(tmp / "hist.db"),
        })
        self.user = "bench_user"
        self.write_llm_calls = 0

    def ingest(self, turns):
        # Batch 5 turns per add() call just like hermes_live --scale (44 batches) so LLM calls stay bounded
        for i in range(0, len(turns), 5):
            batch = turns[i:i + 5]
            msgs = [{"role": "user", "content": u} for u, _ in batch]
            for attempt in range(3):
                try:
                    self.m.add(msgs, user_id=self.user, infer=True)
                    self.write_llm_calls += 2  # mem0 runs extraction + update reconciliation LLM calls
                    break
                except Exception as exc:
                    print(f"[mem0-llm] batch {i} retry {attempt}: {exc}", flush=True)
                    time.sleep(2 * (attempt + 1))
            if (i // 5 + 1) % 10 == 0:
                print(f"[mem0-llm] ingest batch {i // 5 + 1}/{(len(turns) + 4) // 5}", flush=True)

    def ask(self, question: str) -> tuple[str, float]:
        t0 = time.perf_counter()
        res = self.m.search(question, filters={"user_id": self.user}, top_k=8)
        items = res.get("results", res) if isinstance(res, dict) else res
        ctx = "\n".join(f"- {r.get('memory', '')}" for r in items if r.get("memory"))
        ret_ms = (time.perf_counter() - t0) * 1000.0
        return answer_llm(question, ctx), ret_ms

    def close(self):
        pass


class HonchoArm:
    name = f"Honcho v3 local ({MODEL} deriver + dialectic)"

    def __init__(self, tmp: Path):
        from honcho import Honcho
        self.base_url = os.environ.get("HONCHO_BASE_URL", "http://127.0.0.1:8001")
        ws = f"e2e-{int(time.time())}"
        self.h = Honcho(workspace_id=ws, base_url=self.base_url)
        self.u = self.h.peer("user")
        self.a = self.h.peer("assistant")
        self.write_llm_calls = 0

    def ingest(self, turns):
        sessions = []
        for i in range(0, len(turns), 5):
            batch = turns[i:i + 5]
            sess = self.h.session(f"s{i // 5}")
            msgs = []
            for u, a in batch:
                msgs.append(self.u.message(u))
                msgs.append(self.a.message(a))
            sess.add_messages(msgs)
            sessions.append(sess)
            self.write_llm_calls += 1
        # Wait for Honcho deriver queue to finish processing all sessions (cap 180s)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 180:
            pending = 0
            for sess in sessions:
                qs = sess.queue_status()
                pending += (getattr(qs, "pending_work_units", 0) or 0) + (getattr(qs, "in_progress_work_units", 0) or 0)
            if pending == 0:
                break
            print(f"[honcho] waiting on deriver: {pending} work units remaining ({time.perf_counter()-t0:.0f}s)", flush=True)
            time.sleep(3)

    def ask(self, question: str) -> tuple[str, float]:
        prompt = (
            f"Answer in one short sentence from what you know about the user. "
            f"If a fact was updated later, state ONLY the newest value (never the old value). "
            f"If never mentioned, say 'I don't know.' Question: {question}"
        )
        t0 = time.perf_counter()
        for attempt in range(3):
            try:
                ans = self.u.chat(prompt, reasoning_level="low")
                ms = (time.perf_counter() - t0) * 1000.0
                return (ans or "").strip(), ms
            except Exception as exc:
                if attempt == 2:
                    return f"ERROR: {exc}", (time.perf_counter() - t0) * 1000.0
                time.sleep(2 * (attempt + 1))
        return "", 0.0

    def close(self):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["teresis", "teresis-emb", "holographic", "mem0-llm", "honcho"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--suite", default="scale", choices=["core", "scale"])
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--hermes", default=str(Path.home() / ".hermes" / "hermes-agent"))
    args = ap.parse_args()

    turns, questions = build_turns(args.seed, args.limit, args.suite)
    with tempfile.TemporaryDirectory(prefix=f"e2e_{args.arm}_") as td:
        tmp = Path(td)
        if args.arm == "teresis":
            arm = TeresisArm(tmp, embed=False)
        elif args.arm == "teresis-emb":
            arm = TeresisArm(tmp, embed=True)
        elif args.arm == "holographic":
            arm = HolographicArm(tmp, Path(args.hermes))
        elif args.arm == "mem0-llm":
            arm = Mem0LLMArm(tmp)
        elif args.arm == "honcho":
            arm = HonchoArm(tmp)
        else:
            raise SystemExit(args.arm)

        t0 = time.perf_counter()
        arm.ingest(turns)
        ingest_s = round(time.perf_counter() - t0, 1)
        print(f"[{args.arm}] ingest complete: {len(turns)} turns in {ingest_s}s", flush=True)

        rows = []
        lat_ms = []
        for i, sc in enumerate(questions):
            ans, ms = arm.ask(sc["ask"])
            ok = HL.grade(sc, ans) and not ans.startswith("ERROR:")
            lat_ms.append(ms)
            rows.append({
                "id": sc["id"], "kind": sc["kind"], "ask": sc["ask"],
                "expect": sc["expect"], "forbid": sc["forbid"],
                "answer": ans, "ok": ok, "ms": round(ms, 1),
            })
            if (i + 1) % 20 == 0 or (i + 1) == len(questions):
                acc_so_far = sum(r["ok"] for r in rows) / len(rows)
                print(f"[{args.arm}] {i + 1}/{len(questions)} acc={acc_so_far:.3f} p50={statistics.median(lat_ms):.0f}ms", flush=True)
        arm.close()

    by_kind = {}
    for k in sorted({r["kind"] for r in rows}):
        sub = [r for r in rows if r["kind"] == k]
        by_kind[k] = {"n": len(sub), "acc": round(sum(r["ok"] for r in sub) / len(sub), 3)}
    summary = {
        "benchmark": f"e2e-{args.suite}",
        "arm": args.arm,
        "system": arm.name,
        "answer_model": MODEL,
        "n": len(rows),
        "acc": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "by_kind": by_kind,
        "ingest_s": ingest_s,
        "write_llm_calls": arm.write_llm_calls,
        "query_p50_ms": round(statistics.median(lat_ms), 1) if lat_ms else 0.0,
        "errors": sum(r["answer"].startswith("ERROR:") for r in rows),
        "seed": args.seed,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"e2e-core-{args.arm}.json" if args.suite == "core" else f"e2e-{args.arm}.json"
    out_path = out_dir / tag
    out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
