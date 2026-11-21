# mnemo

Local long-term memory for AI agents. It stores everything in one SQLite file and has no dependencies.
It ships a Hermes memory provider, an MCP server, a local HTTP API, a CLI and a Python API, and all of
them share the same store.

Development runs on nucbox (`/home/nuc/Projects/mnemo`).

## Why it is built this way

Agent memory differs from document RAG. Agents write constantly, repeat themselves, and change
their minds. Several of them may also share one store at the same time. mnemo is designed around
the write path as much as the read path:

| Problem | What mnemo does |
| --- | --- |
| Agents save the same fact repeatedly | Exact duplicates (after normalization) and near duplicates (Jaccard ≥ 0.9) reinforce the existing memory instead of adding rows. |
| Facts change ("we moved to Postgres") | A `key` makes a memory an updatable slot. The new value supersedes the old one, and `history`/`as_of` keep the full timeline. A new memory that strictly refines an old one supersedes it automatically. |
| Projects leak into each other | Scopes are paths (`global`, `user`, `project/atlas`, `project/atlas/agent-x`). Recall sees the scope plus its parents, never its siblings. |
| Agents misspell and inflect words | BM25 over a Porter-stemmed FTS5 index, plus a trigram index for fuzzy matching (`postgress` → PostgreSQL). |
| Paraphrased questions | Optional embeddings (Ollama or any OpenAI-compatible server) add a semantic channel. Without them mnemo stays fully functional and lexical. |
| Stale and temporary facts | Recency, importance, reinforcement and pinning act as gentle tie-breakers. `ttl_days` makes memories expire. |
| Context windows are finite | `budget_tokens` packs the best memories that fit. `context()` returns a ready-to-inject block. |
| Many agents, one store | WAL mode, `BEGIN IMMEDIATE` writes, busy timeouts. The test suite runs 4 processes writing concurrently. |

### Retrieval

Each query runs up to three channels against the active, in-scope set:

1. FTS5 BM25 (Porter stemming; columns weighted content 1.0 / tags 0.6 / key 1.5)
2. Trigram fuzzy match (kept only when ≥ 50% of the query's trigrams appear)
3. Cosine similarity over unit vectors (when an embedder is configured)

Scores are normalized per channel and combined as a weighted mean. Then priors are applied:
`relevance × recency(30-day half-life, ≤15%) × importance(±10%) × reinforcement × pinned`.

Reciprocal-rank fusion was tried first and measured worse. It flattens BM25 margins (rank 1 vs rank 6
becomes 1.00 vs 0.92), so priors overrode real relevance. Exact-match hit@1 was 0.57 with RRF and
1.00 with score fusion.

## What it borrows from other memory providers

I read the 8 providers bundled with Hermes (mem0, supermemory, holographic, honcho, hindsight,
retaindb, byterover, openviking) and the designs of Zep/Graphiti and Letta. mnemo keeps the ideas that
work locally without an LLM:

| Idea | From | In mnemo |
| --- | --- | --- |
| Reconcile writes against existing memories instead of appending | mem0 | Dedup, refinement and keyed supersession on every write |
| Facts have validity intervals; old values stay queryable | Zep/Graphiti | `superseded_at`, `history`, `recall(as_of=...)` |
| Always-in-context core memory vs searchable archive | Letta | `pinned` + `context()` vs `recall()` |
| Agents rate memories; trust rises and falls | holographic | `memory_feedback` |
| Surface contradictions for cleanup | holographic | `memory_conflicts` |
| Capture conversation turns automatically | supermemory, mem0 | Episodes with a TTL, kept out of fact recall |
| Non-primary agent contexts must not write | supermemory | Read-only in subagent, cron and flush |

Deliberately not borrowed: LLM-based extraction on every turn (mem0, honcho). It costs a model call per
turn, is non-deterministic, and needs a network or a large local model. mnemo stays deterministic. The
agent saves what matters through tools, and rules catch explicit preferences and decisions.

## Benchmark

`mnemo bench` runs 35 queries over 34 target memories hidden among 2,000 distractors. The queries
cover supersession, scope isolation, inheritance, typos, morphology, recency, expiry and paraphrase.
It also measures latency at scale. Results on nucbox (8-core, Python 3.14, SQLite 3.54):

| System | hit@1 | hit@5 | MRR | leak@5 |
| --- | --- | --- | --- | --- |
| **mnemo, lexical only** | **0.86** | 0.91 | 0.89 | 0.00 |
| **mnemo + nomic-embed-text (Ollama)** | **0.94** | 0.94 | 0.94 | 0.00 |
| naive LIKE baseline (newest first) | 0.51 | 0.74 | 0.60 | 0.06 |

Ablations (lexical): removing trigram drops typo hit@1 from 1.00 to 0.80, and removing the
recency/importance priors drops recency hit@1 from 1.00 to 0.50. Embeddings raise paraphrase hit@1
from 0.33 to 0.83.

Latency, lexical, 10k memories: recall p50 14 ms / p95 21 ms, about 200 writes/s, 6 MB on disk.
With CPU embeddings and no numpy: recall p50 about 180 ms, about 20 writes/s, dominated by the
embedding call and pure-Python cosine. Install `numpy` (`pip install mnemo[fast]`) for vectorized
similarity.

Caveat: the fixture was written by the author and the defaults were tuned on it. Treat the numbers
as regression guards and relative comparisons, not as a public leaderboard score.

## Use

```bash
# from a checkout (no install needed)
PYTHONPATH=src python3 -m mnemo remember "Atlas uses PostgreSQL 16" -s project/atlas --key atlas.database
PYTHONPATH=src python3 -m mnemo recall "atlas db" -s project/atlas --explain
PYTHONPATH=src python3 -m mnemo context -s project/atlas -q "fix the migration" --budget 800
PYTHONPATH=src python3 -m mnemo history -s project/atlas --key atlas.database

# or install: pip install -e .   then just `mnemo ...`
```

The database defaults to `$MNEMO_DB`, else `~/.local/share/mnemo/memory.db`.

### Hermes Agent

```bash
PYTHONPATH=/path/to/mnemo/src python3 -m mnemo hermes install          # copies to $HERMES_HOME/plugins/mnemo
PYTHONPATH=/path/to/mnemo/src python3 -m mnemo hermes install --link   # dev: symlink this checkout
hermes config set memory.provider mnemo                                 # then start a new session
```

Alternatively, run `pip install` on mnemo inside the Hermes venv. It registers the
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

Config goes under `plugins.mnemo` in `config.yaml`:

| Key | Default | Notes |
| --- | --- | --- |
| `db_path` | `""` | Empty means the shared `~/.local/share/mnemo/memory.db`, the same file your MCP agents use. Set `$HERMES_HOME/mnemo.db` to isolate a profile. |
| `scope` | `hermes/<profile>` | Write scope |
| `extra_scopes` | `user` | Also searched on recall (comma-separated) |
| `capture_turns` | `true` | Save turns as episodes |
| `episode_ttl_days` | `30` | `0` keeps them forever |
| `auto_extract` | `true` | Rule-based; precision over recall |
| `prefetch_k` / `prefetch_budget_tokens` | `6` / `700` | Injection size |

### MCP (Claude Code, Codex, Cursor, OMP, …)

```bash
claude mcp add mnemo -- env PYTHONPATH=/path/to/mnemo/src python3 -m mnemo serve --scope project/atlas --scope user
```

```json
{ "mcpServers": { "mnemo": {
    "command": "python3", "args": ["-m", "mnemo", "serve", "--scope", "global"],
    "env": { "PYTHONPATH": "/path/to/mnemo/src" } } } }
```

Repeat `--scope` as needed: writes go to the first scope, and recall searches all of them plus their parents.

Tools: `memory_remember`, `memory_recall`, `memory_context`, `memory_update`, `memory_forget`,
`memory_history`, `memory_feedback`, `memory_conflicts`, `memory_stats`. The server sends usage
instructions in `initialize`.

### HTTP (anything else)

```bash
MNEMO_HTTP_TOKEN=change-me python3 -m mnemo http --port 7077 --scope global
curl -s localhost:7077/tools/memory_recall -H 'Authorization: Bearer change-me' -d '{"query":"deploy"}'
```

It uses the same tool names and arguments as MCP. It binds to 127.0.0.1 by default.

### Python

```python
from mnemo import MemoryStore
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
export MNEMO_EMBED=ollama MNEMO_EMBED_MODEL=nomic-embed-text           # local Ollama
export MNEMO_EMBED=openai MNEMO_EMBED_MODEL=... MNEMO_EMBED_URL=http://localhost:8080/v1  # llama.cpp/vLLM/LM Studio
mnemo embed                                                             # backfill existing memories
```

If the embedder is down, writes still succeed without a vector, and `mnemo embed` backfills them later.

## Maintenance

`mnemo maintain` hard-deletes expired memories and memories soft-deleted more than 30 days ago, then
optimizes the FTS indexes. `mnemo export > backup.jsonl` and `mnemo import < backup.jsonl` round-trip
the full history.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m mnemo bench
```

## Limits

- Contradictions without a shared `key` are not detected. "Prefers vim" and then "prefers emacs" are
  stored as two memories, and recency ranks the newer one first. Use keys for facts that change.
- Brute-force vector search is fine up to roughly 100k memories with numpy, and a few thousand
  without it.
- No LLM is in the loop: there is no automatic summarization or extraction. The agent decides what is
  worth remembering, which keeps writes deterministic and fast.
