# Teresis

*τήρησις* ("faithful keeping") — local long-term memory for AI agents. It stores everything in one
SQLite file and has no dependencies. It ships a Hermes memory provider, an MCP server, a local HTTP
API, a CLI and a Python API, and all of them share the same store.

Development runs on nucbox (`/home/nuc/Projects/teresis`). Brand color: Manuscript Ochre (`#A67A2A`,
dark-mode accent `#D9AF5B`, light-mode ink `#7C591B`).

## Why it is built this way

Agent memory differs from document RAG. Agents write constantly, repeat themselves, and change
their minds. Several of them may also share one store at the same time. Teresis is designed around
the write path as much as the read path:

| Problem | What Teresis does |
| --- | --- |
| Agents save the same fact repeatedly | Exact duplicates (after normalization) and near duplicates (Jaccard ≥ 0.9) reinforce the existing memory instead of adding rows. |
| Facts change ("we moved to Postgres") | A `key` makes a memory an updatable slot. The new value supersedes the old one, and `history`/`as_of` keep the full timeline. A new memory that strictly refines an old one supersedes it automatically. |
| Projects leak into each other | Scopes are paths (`global`, `user`, `project/atlas`, `project/atlas/agent-x`). Recall sees the scope plus its parents, never its siblings. |
| Agents misspell and inflect words | BM25 over a Porter-stemmed FTS5 index, plus a trigram index for fuzzy matching (`postgress` → PostgreSQL). |
| Paraphrased questions | Optional embeddings (Ollama or any OpenAI-compatible server) add a semantic channel. Without them Teresis stays fully functional and lexical. |
| Stale and temporary facts | Recency, importance, reinforcement and pinning act as gentle tie-breakers. `ttl_days` makes memories expire. |
| Context windows are finite | `budget_tokens` packs the best memories that fit. `context()` returns a ready-to-inject block. |
| Many agents, one store | WAL mode, `BEGIN IMMEDIATE` writes, busy timeouts. The test suite runs 4 processes writing concurrently. |

### Retrieval

Each query runs up to three channels against the active, in-scope set:

1. FTS5 BM25 (Porter stemming; columns weighted content 1.0 / tags 0.6 / key 1.5; channel weight 1.0)
2. Trigram fuzzy match (kept only when ≥ 50% of the query's trigrams appear; channel weight 0.35)
3. Cosine similarity over unit vectors (when an embedder is configured; channel weight 2.0, `min_cosine=0.0`)

Scores are normalized per channel and combined as a weighted mean. Then priors are applied:
`relevance × recency(30-day half-life, ≤15%) × importance(±10%) × reinforcement × pinned`.
Optional greedy MMR diversification (`Weights(mmr=...)`) is off by default (`0.0`).

Reciprocal-rank fusion was tried first and measured worse. It flattens BM25 margins (rank 1 vs rank 6
becomes 1.00 vs 0.92), so priors overrode real relevance. Exact-match hit@1 was 0.57 with RRF and
1.00 with score fusion.

## What it borrows from other memory providers

I read the 8 providers bundled with Hermes (mem0, supermemory, holographic, honcho, hindsight,
retaindb, byterover, openviking) and the designs of Zep/Graphiti and Letta. Teresis keeps the ideas
that work locally without an LLM:

| Idea | From | In Teresis |
| --- | --- | --- |
| Reconcile writes against existing memories instead of appending | mem0 | Dedup, refinement and keyed supersession on every write |
| Facts have validity intervals; old values stay queryable | Zep/Graphiti | `superseded_at`, `history`, `recall(as_of=...)` |
| Always-in-context core memory vs searchable archive | Letta | `pinned` + `context()` vs `recall()` |
| Agents rate memories; trust rises and falls | holographic | `memory_feedback` |
| Surface contradictions for cleanup | holographic | `memory_conflicts` |
| Capture conversation turns automatically | supermemory, mem0 | Episodes with a TTL, kept out of fact recall |
| Non-primary agent contexts must not write | supermemory | Read-only in subagent, cron and flush |

Deliberately not borrowed: LLM-based extraction on every turn (mem0, honcho). It costs a model call per
turn, is non-deterministic, and needs a network or a large local model. Teresis stays deterministic.
The agent saves what matters through tools, and rules catch explicit preferences and decisions.

## Head-to-head: LongMemEval

`bench/compare.py` runs the public LongMemEval_s benchmark (Wu et al., ICLR 2025) against other
providers. Each question comes with a ~50-session chat history. Every system ingests the same units
(one user/assistant round, at most 2,000 characters) and gets the question as its query. Scoring is
at the session level, as in the paper. The 30 abstention questions have no evidence, so they are
skipped. Everything ran on nucbox: 8-core CPU, no GPU, Ollama on CPU.

Retrieval weights (`vector=2.0`, `min_cosine=0.0`) were selected via `bench/tune.py` on a disjoint
80-question dev split (seed 7; dev objective `0.942 → 0.979`, `recall_all@10 0.938 → 1.000`), then
evaluated once on the untouched 100-question test split (seed 13):

| System | recall_any@5 | recall_all@10 | NDCG@10 | ingest rounds/s | query p50 |
| --- | --- | --- | --- | --- | --- |
| **teresis + all-minilm** | **0.98** | 0.95 | **0.936** | 5.7* | 26 ms** |
| mem0 OSS 2.2.1 hybrid (BM25 + spaCy + all-minilm, infer=False) | 0.97 | 0.93 | 0.932 | 60* | 714 ms |
| LanceDB hybrid (BM25 + all-minilm, RRF) | 0.97 | 0.93 | 0.930 | cached* | 23 ms |
| ChromaDB (all-minilm) | **0.98** | **0.96** | 0.904 | 15.9* | 27 ms |
| mem0 OSS 2.2.1 (vector only, all-minilm, infer=False) | **0.98** | **0.96** | 0.903 | 8.3* | 366 ms |
| total-agent-memory 14.10 (FastEmbed + FTS + RRF, no reranker) | 0.97 | 0.92 | 0.900 | 10.8 | 108 ms |
| teresis (no model) | 0.97 | 0.89 | 0.882 | 43 | 25 ms |
| SQLite FTS5 (BM25, porter) | 0.96 | 0.87 | 0.881 | 18,983 | 0.5 ms |
| holographic (Hermes plugin) | 0.94 | 0.85 | 0.859 | 7.2 | 23 ms |
| naive LIKE, newest first | 0.35 | 0.18 | 0.195 | — | 6 ms |

All 470 non-abstention questions, teresis with no model: recall_any@5 0.968, recall_all@10 0.913,
NDCG@10 0.895. The weakest type was single-session-preference at 0.73, where questions are indirect
("can you recommend…").

How to read it:
- At recall_any@5, LongMemEval_s is close to saturated for any relevance-ranked system. The
  distractor sessions are mostly unrelated chat. The stricter metrics (`recall_all@10`, `NDCG@10`)
  are where systems differ.
- With no model at all, Teresis is within 0.01 recall_any@5 of mem0 with embeddings. It queries 15
  times faster and ingests 5 times faster.
- With the same `all-minilm` embedding model, dev-tuned Teresis jumps from `0.91 → 0.95`
  `recall_all@10` (+0.077 on `multi-session`, +0.074 on `temporal-reasoning`) and leads mem0 on
  `NDCG@10` (`0.936` vs `0.903`) and combined objective (`0.943` vs `0.932`).
- Leak check: the evidence sessions' mean position in time is 0.54 (0 is oldest, 1 is newest), and
  Teresis scores the same with its recency and importance priors turned off.
- \* Ingest speeds for embedding systems are not directly comparable: `teresis + all-minilm` and
  vector-only `mem0` shared CPU Ollama; `LanceDB` and `mem0 hybrid` reused an on-disk ingest cache
  of the exact `all-minilm` vectors computed by `ChromaDB` (all query embeddings remained live and
  uncached). `mem0` ran with telemetry disabled and `infer=False` (no LLM) in both vector-only and
  v3 hybrid (`mem0ai[nlp]` + `fastembed` BM25 + spaCy) modes; both reused one local Qdrant
  collection filtered by `user_id` across the 100 questions. `total-agent-memory` ran with its
  built-in FastEmbed `paraphrase-multilingual-MiniLM-L12-v2` and `defer_cross_rerank=True` (no
  cross-encoder) across 4 shards.
- \*\* `teresis + all-minilm` query p50 was 26 ms against idle CPU Ollama (152 ms in the earlier
  head-to-head run while sharing CPU Ollama with mem0).
- Not compared: supermemory, honcho, retaindb, byterover, openviking and hindsight. They are cloud
  services that need accounts and would send data off the machine.

Reproduce: `pip install mem0ai ollama numpy` in a venv, run `ollama pull all-minilm`, then
`python bench/compare.py --data longmemeval_s_cleaned.json --system <naive|teresis|teresis-emb|holographic|mem0> --limit 100`
and `python bench/report.py bench/results`.

## Head-to-head: LoCoMo

`bench/locomo.py` runs LoCoMo (Maharana et al., ACL 2024): 10 long multi-session conversations,
ingested one turn at a time, scored on whether the retrieved turns contain the exact evidence
`dia_id`s. It covers 1,536 QA pairs across multi-hop, temporal, open-domain and single-hop
categories. The adversarial category is excluded because it has no evidence to retrieve. The
retrieval weights are the same ones from the LongMemEval dev split. Nothing was re-tuned on LoCoMo.
Everything ran on nucbox (CPU only).

| System | recall_any@5 | recall_any@10 | recall_all@10 | NDCG@10 | ingest turns/s | query p50 |
| --- | --- | --- | --- | --- | --- | --- |
| **teresis + all-minilm** | **0.654** | **0.727** | **0.588** | **0.516** | 63 | 22 ms |
| teresis (no model) | 0.637 | 0.712 | 0.585 | 0.512 | 422 | 8.4 ms |
| total-agent-memory 14.10 (FastEmbed + FTS + RRF, no reranker) | 0.612 | 0.696 | 0.572 | 0.488 | 12.5 | 45 ms |
| SQLite FTS5 (BM25, porter) | 0.606 | 0.689 | 0.566 | 0.485 | 147,213 | 0.5 ms |
| LanceDB hybrid (BM25 + all-minilm, RRF) | 0.589 | 0.686 | 0.555 | 0.457 | 63 | 19 ms |
| mem0 OSS 2.2.1 hybrid (BM25 + spaCy + all-minilm, infer=False) | 0.564 | 0.682 | 0.553 | 0.433 | 50 | 221 ms |
| holographic (Hermes plugin) | 0.562 | 0.638 | 0.530 | 0.449 | 41 | 10 ms |
| mem0 OSS 2.2.1 (vector only, all-minilm, infer=False) | 0.449 | 0.566 | 0.440 | 0.342 | 71 | 126 ms |
| ChromaDB (all-minilm) | 0.448 | 0.563 | 0.439 | 0.341 | 60 | 11 ms |
| naive LIKE, newest first | 0.025 | 0.049 | 0.038 | 0.021 | — | 0.8 ms |

recall_any@5 by category:

| System | multi-hop (282) | temporal (321) | open-domain (92) | single-hop (841) |
| --- | --- | --- | --- | --- |
| teresis + all-minilm | **0.603** | **0.707** | 0.359 | **0.684** |
| teresis (no model) | 0.539 | 0.685 | **0.380** | 0.680 |
| total-agent-memory (no reranker) | 0.443 | 0.685 | **0.380** | 0.666 |
| SQLite FTS5 (BM25) | 0.457 | 0.682 | 0.359 | 0.653 |
| LanceDB hybrid | 0.560 | 0.654 | 0.348 | 0.601 |
| mem0 OSS hybrid (infer=False) | 0.539 | 0.660 | 0.337 | 0.560 |
| holographic | 0.372 | 0.635 | 0.337 | 0.623 |
| mem0 OSS (vector only) | 0.401 | 0.517 | 0.239 | 0.463 |
| ChromaDB | 0.401 | 0.517 | 0.239 | 0.460 |

How to read it:
- Turns are short and full of names and dates, which is where exact-term matching earns its keep.
  Teresis with no model at all beats mem0 with embeddings by 18.8 points of recall_any@5. With the
  same embedding model it leads by 20.5 points and queries 5.6 times faster.
- The embedding model mainly helps multi-hop (`0.539 → 0.603`). It does not help open-domain, where
  the no-model run is slightly ahead (`0.380` vs `0.359`, 92 questions, so within noise).
- This is retrieval only. It does not test answer generation or abstention. `mem0` ran with
  `infer=False` (no LLM) in both vector-only and v3 hybrid (`fastembed` BM25 + spaCy) modes;
  `total-agent-memory` ran with its default FastEmbed MiniLM and `defer_cross_rerank=True`.

Reproduce: download `locomo10.json` from the LoCoMo repo to `.data/`, then
`python bench/locomo.py --data .data/locomo10.json --system <naive|teresis|teresis-emb|holographic|mem0>`.

## Live in Hermes

The two benchmarks above score retrieval. `bench/hermes_live.py` runs a real Hermes agent end to end
(`gpt-6.1-terra`, medium reasoning, fast mode off) with one fresh process per session. Facts are told
in earlier sessions, then each question is asked in a new session with nothing restated. Grading is
string match, with no LLM judge. The comparison is Hermes with Teresis against stock Hermes with only
its built-in memory file.

200 facts were told, 5 per session: 120 direct facts (ports, IPs, versions), 40 where the question
shares only the project name with the fact, 20 preferences and 20 that later change value. 100
questions were asked, including all 20 changed values and 10 about things never told.

| | Teresis | Stock Hermes |
| --- | --- | --- |
| Total | **100/100** | 60/100 |
| Direct facts (40) | 40 | 21 |
| Paraphrased questions (20) | 20 | 13 |
| Preferences (10) | 10 | 3 |
| Changed values, newest must win (20) | 20 | 13 |
| Never told, must say so (10) | 10 | 10 |
| Median answer time | 12.0 s | 10.4 s |

With 200 facts the built-in memory file (3,200 characters) overflows. Stock Hermes answers "I don't
know" for what it lost, or gives the old value of a changed fact. It never invented an answer.
Lookup in the Teresis store took a median of 6.6 ms (p95 8.5 ms) over 520 KB, and the answer was in
the injected context for all 30 questions sampled.

Caveats:
- A 30-fact version of the same run was a tie (29/30 each). The built-in memory file holds that many,
  so the gap only appears once memory outgrows it.
- Both arms ran the same questions with seed 42. One run per arm, so there is no variance estimate.
- The embedding variant did not run: Hermes does not forward `TERESIS_EMBED*` env vars to
  providers, so that arm stored no vectors. Set `embed` and `embed_model` under `plugins.teresis`
  instead. Even without embeddings Teresis scored 100%, because every question here contains the
  project name, so this run cannot show what embeddings add.
- Answers were re-graded once after fixing the grader: "4,249" now matches `4249`, and "I don't
  remember" counts as a refusal. It applied to every arm, and the results files say so.

## Built-in benchmark

`teresis bench` runs 35 queries over 34 target memories hidden among 2,000 distractors. The queries
cover supersession, scope isolation, inheritance, typos, morphology, recency, expiry and paraphrase.
It also measures latency at scale. Results on nucbox (8-core, Python 3.14, SQLite 3.54):

| System | hit@1 | hit@5 | MRR | leak@5 |
| --- | --- | --- | --- | --- |
| **teresis, lexical only** | **0.86** | 0.91 | 0.89 | 0.00 |
| **teresis + all-minilm (Ollama)** | **0.97** | 0.97 | 0.97 | 0.00 |
| naive LIKE baseline (newest first) | 0.51 | 0.74 | 0.60 | 0.06 |

Ablations (lexical): removing trigram drops typo hit@1 from 1.00 to 0.80, and removing the
recency/importance priors drops recency hit@1 from 1.00 to 0.50. Embeddings raise paraphrase hit@1
from 0.33 to 0.83.

Latency, lexical, 10k memories: recall p50 14 ms / p95 21 ms, about 200 writes/s, 6 MB on disk.
With CPU embeddings and no numpy: recall p50 about 180 ms, about 20 writes/s, dominated by the
embedding call and pure-Python cosine. Install `numpy` (`pip install teresis[fast]`) for vectorized
similarity.

Caveat: the fixture was written by the author and the lexical defaults were tuned on it. Treat the
numbers as regression guards and relative comparisons, not as a public leaderboard score.

## Use

```bash
# from a checkout (no install needed)
PYTHONPATH=src python3 -m teresis remember "Atlas uses PostgreSQL 16" -s project/atlas --key atlas.database
PYTHONPATH=src python3 -m teresis recall "atlas db" -s project/atlas --explain
PYTHONPATH=src python3 -m teresis context -s project/atlas -q "fix the migration" --budget 800
PYTHONPATH=src python3 -m teresis history -s project/atlas --key atlas.database

# or install: pip install -e .   then just `teresis ...`
```

The database defaults to `$TERESIS_DB`, else `~/.local/share/teresis/memory.db`.

### Hermes Agent

```bash
PYTHONPATH=/path/to/teresis/src python3 -m teresis hermes install          # copies to $HERMES_HOME/plugins/teresis
PYTHONPATH=/path/to/teresis/src python3 -m teresis hermes install --link   # dev: symlink this checkout
hermes config set memory.provider teresis                                  # then start a new session
```

Alternatively, run `pip install` on teresis inside the Hermes venv. It registers the
`hermes_agent.memory_providers` entry point.

What the provider does on each Hermes hook:

| Hook | Behavior |
| --- | --- |
| `prefetch` | Hybrid recall over `hermes/<profile>` + `user` + `global`, injected before each turn. Trivial prompts ("ok", "thanks", slash commands) skip recall. |
| `sync_turn` | Saves the turn as an `episode` (30-day TTL, low importance, kept out of fact recall) and extracts stated preferences, rules and decisions. |
| `on_memory_write` | Mirrors Hermes' built-in `memory` tool. `add` → remember, `replace` → new version of the matching memory, `remove` → forget. |
| `on_pre_compress` | Extracts durable facts from messages about to be compressed, and lists them for the summary. |
| `on_delegation` | Records the subagent task and its result as an episode. |
| subagent / cron / flush | Read-only. Write tools return an error, and the hooks do not save anything. |

Config goes under `plugins.teresis` in `config.yaml`:

| Key | Default | Notes |
| --- | --- | --- |
| `db_path` | `""` | Empty means the shared `~/.local/share/teresis/memory.db`, the same file your MCP agents use. Set `$HERMES_HOME/teresis.db` to isolate a profile. |
| `scope` | `hermes/<profile>` | Write scope |
| `extra_scopes` | `user` | Also searched on recall (comma-separated) |
| `embed` / `embed_model` / `embed_url` | `""` | Embedder for this provider, e.g. `ollama` / `all-minilm`. Hermes does not forward `TERESIS_EMBED*` env vars, so set them here. |
| `capture_turns` | `true` | Save turns as episodes |
| `episode_ttl_days` | `30` | `0` keeps them forever |
| `auto_extract` | `true` | Rule-based; precision over recall |
| `prefetch_k` / `prefetch_budget_tokens` | `6` / `700` | Injection size |

### MCP (Claude Code, Codex, Cursor, OMP, …)

```bash
claude mcp add teresis -- env PYTHONPATH=/path/to/teresis/src python3 -m teresis serve --scope project/atlas --scope user
```

```json
{ "mcpServers": { "teresis": {
    "command": "python3", "args": ["-m", "teresis", "serve", "--scope", "global"],
    "env": { "PYTHONPATH": "/path/to/teresis/src" } } } }
```

Repeat `--scope` as needed: writes go to the first scope, and recall searches all of them plus their parents.

Tools: `memory_remember`, `memory_recall`, `memory_context`, `memory_update`, `memory_forget`,
`memory_history`, `memory_feedback`, `memory_conflicts`, `memory_stats`. The server sends usage
instructions in `initialize`.

### HTTP (anything else)

```bash
export TERESIS_HTTP_TOKEN="$(openssl rand -hex 16)"
python3 -m teresis http --port 7077 --scope global &
curl -s localhost:7077/tools/memory_recall -H "Authorization: Bearer $TERESIS_HTTP_TOKEN" -d '{"query":"deploy"}'
```

It uses the same tool names and arguments as MCP. It binds to 127.0.0.1 by default.

### Python

```python
from teresis import MemoryStore
m = MemoryStore()                                   # or MemoryStore("path.db", embedder=None)
m.remember("User prefers terse answers", scope="user", kind="preference", importance=0.8)
m.remember("Editor is Neovim", scope="user", key="user.editor")      # supersedes older value
hits = m.recall("how should I answer", scope=["project/atlas", "user"])
print(m.context(["project/atlas", "user"], query="writing a reply"))
```

Scope inheritance follows the path: `project/atlas/agent-x` → `project/atlas` → `project` → `global`.
`user` is a sibling scope. To search it together with a project, pass `scope=["project/atlas", "user"]`.

### Embeddings (optional)

```bash
export TERESIS_EMBED=ollama TERESIS_EMBED_MODEL=nomic-embed-text           # local Ollama
export TERESIS_EMBED=openai TERESIS_EMBED_MODEL=... TERESIS_EMBED_URL=http://localhost:8080/v1  # llama.cpp/vLLM/LM Studio
teresis embed                                                              # backfill existing memories
```

If the embedder is down, writes still succeed without a vector, and `teresis embed` backfills them later.

## Maintenance

`teresis maintain` hard-deletes expired memories and memories soft-deleted more than 30 days ago, then
optimizes the FTS indexes. `teresis export > backup.jsonl` and `teresis import < backup.jsonl` round-trip
the full history.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m teresis bench
```

## Limits

- Contradictions without a shared `key` are not detected. "Prefers vim" and then "prefers emacs" are
  stored as two memories, and recency ranks the newer one first. Use keys for facts that change.
- Brute-force vector search is fine up to roughly 100k memories with numpy, and a few thousand
  without it.
- No LLM is in the loop: there is no automatic summarization or extraction. The agent decides what is
  worth remembering, which keeps writes deterministic and fast.
