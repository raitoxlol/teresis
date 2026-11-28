// Interactive-page data. Every number is copied from README.md (tables "Head-to-head: LongMemEval",
// "Head-to-head: LoCoMo", "200-fact E2E", "Live in Hermes") and matches bench/results/*.json.
// Every terminal line is real CLI output captured from one session against an empty store.
// Do not edit a value here without changing the README and the results file it comes from.

export type BenchRow = {
  label: string;
  teresis?: boolean;
  /** metric id -> score, 0..1 */
  scores: Record<string, number>;
  /** median query time as printed, and in ms for sorting */
  p50: string;
  p50ms: number;
};

export type Metric = {id: string; label: string; hint: string};

export const LONGMEMEVAL_METRICS: Metric[] = [
  {id: 'ndcg10', label: 'NDCG@10', hint: 'Ranking quality of the top 10'},
  {id: 'all10', label: 'recall_all@10', hint: 'Every evidence session in the top 10'},
  {id: 'any5', label: 'recall_any@5', hint: 'Any evidence session in the top 5'},
];

export const LONGMEMEVAL_ROWS: BenchRow[] = [
  {label: 'Teresis + all-minilm + reranker', teresis: true, scores: {any5: 0.99, all10: 0.96, ndcg10: 0.949}, p50: '2.8 s', p50ms: 2800},
  {label: 'Teresis + all-minilm', teresis: true, scores: {any5: 0.99, all10: 0.95, ndcg10: 0.944}, p50: '51 ms', p50ms: 51},
  {label: 'mem0 OSS hybrid (infer=False)', scores: {any5: 0.97, all10: 0.93, ndcg10: 0.932}, p50: '714 ms', p50ms: 714},
  {label: 'LanceDB hybrid', scores: {any5: 0.97, all10: 0.93, ndcg10: 0.93}, p50: '23 ms', p50ms: 23},
  {label: 'engram-search (no reranker)', scores: {any5: 0.97, all10: 0.91, ndcg10: 0.905}, p50: '120 ms', p50ms: 120},
  {label: 'ChromaDB', scores: {any5: 0.98, all10: 0.96, ndcg10: 0.904}, p50: '27 ms', p50ms: 27},
  {label: 'mem0 OSS (vector only)', scores: {any5: 0.98, all10: 0.96, ndcg10: 0.903}, p50: '366 ms', p50ms: 366},
  {label: 'total-agent-memory (no reranker)', scores: {any5: 0.97, all10: 0.92, ndcg10: 0.9}, p50: '108 ms', p50ms: 108},
  {label: 'Teresis, no model', teresis: true, scores: {any5: 0.98, all10: 0.89, ndcg10: 0.888}, p50: '19 ms', p50ms: 19},
  {label: 'SQLite FTS5 (BM25)', scores: {any5: 0.96, all10: 0.87, ndcg10: 0.881}, p50: '0.5 ms', p50ms: 0.5},
  {label: 'holographic (Hermes plugin)', scores: {any5: 0.94, all10: 0.85, ndcg10: 0.859}, p50: '23 ms', p50ms: 23},
  {label: 'bm25s (pure BM25)', scores: {any5: 0.95, all10: 0.86, ndcg10: 0.852}, p50: '0.6 ms', p50ms: 0.6},
  {label: 'Naive LIKE, newest first', scores: {any5: 0.35, all10: 0.18, ndcg10: 0.195}, p50: '6 ms', p50ms: 6},
];

export const LONGMEMEVAL_NOTE =
  'LongMemEval_s (Wu et al., ICLR 2025), 100-question test split, scored per session. Retrieval only, no LLM calls. 8-core CPU, no GPU.';

export const LOCOMO_METRICS: Metric[] = [
  {id: 'any5', label: 'recall_any@5', hint: 'Any evidence turn in the top 5'},
  {id: 'any10', label: 'recall_any@10', hint: 'Any evidence turn in the top 10'},
  {id: 'all10', label: 'recall_all@10', hint: 'Every evidence turn in the top 10'},
  {id: 'ndcg10', label: 'NDCG@10', hint: 'Ranking quality of the top 10'},
];

export const LOCOMO_ROWS: BenchRow[] = [
  {label: 'Teresis + all-minilm + reranker', teresis: true, scores: {any5: 0.718, any10: 0.758, all10: 0.624, ndcg10: 0.589}, p50: '738 ms', p50ms: 738},
  {label: 'Teresis + all-minilm', teresis: true, scores: {any5: 0.664, any10: 0.732, all10: 0.594, ndcg10: 0.52}, p50: '37 ms', p50ms: 37},
  {label: 'Teresis, no model', teresis: true, scores: {any5: 0.641, any10: 0.716, all10: 0.587, ndcg10: 0.516}, p50: '17 ms', p50ms: 17},
  {label: 'total-agent-memory (no reranker)', scores: {any5: 0.612, any10: 0.696, all10: 0.572, ndcg10: 0.488}, p50: '45 ms', p50ms: 45},
  {label: 'SQLite FTS5 (BM25)', scores: {any5: 0.606, any10: 0.689, all10: 0.566, ndcg10: 0.485}, p50: '0.5 ms', p50ms: 0.5},
  {label: 'LanceDB hybrid', scores: {any5: 0.589, any10: 0.686, all10: 0.555, ndcg10: 0.457}, p50: '19 ms', p50ms: 19},
  {label: 'mem0 OSS hybrid (infer=False)', scores: {any5: 0.564, any10: 0.682, all10: 0.553, ndcg10: 0.433}, p50: '221 ms', p50ms: 221},
  {label: 'holographic (Hermes plugin)', scores: {any5: 0.562, any10: 0.638, all10: 0.53, ndcg10: 0.449}, p50: '10 ms', p50ms: 10},
  {label: 'bm25s (pure BM25)', scores: {any5: 0.513, any10: 0.587, all10: 0.486, ndcg10: 0.401}, p50: '0.4 ms', p50ms: 0.4},
  {label: 'engram-search (no reranker)', scores: {any5: 0.484, any10: 0.606, all10: 0.486, ndcg10: 0.344}, p50: '71 ms', p50ms: 71},
  {label: 'mem0 OSS (vector only)', scores: {any5: 0.449, any10: 0.566, all10: 0.44, ndcg10: 0.342}, p50: '126 ms', p50ms: 126},
  {label: 'ChromaDB', scores: {any5: 0.448, any10: 0.563, all10: 0.439, ndcg10: 0.341}, p50: '11 ms', p50ms: 11},
  {label: 'Naive LIKE, newest first', scores: {any5: 0.025, any10: 0.049, all10: 0.038, ndcg10: 0.021}, p50: '0.8 ms', p50ms: 0.8},
];

export const LOCOMO_NOTE =
  'LoCoMo (Maharana et al., ACL 2024), 10 conversations, 1,536 questions, scored on the exact evidence turns. Same weights as LongMemEval, nothing re-tuned. Retrieval only.';

// Live in Hermes: a real Hermes agent, 200 facts told in earlier sessions, 100 questions in fresh sessions.
export const LIVE = {
  teresis: {label: 'Hermes + Teresis', right: 100, asked: 100},
  stock: {label: 'Stock Hermes (built-in memory)', right: 60, asked: 100},
  byKind: [
    {kind: 'Direct facts', asked: 40, teresis: 40, stock: 21},
    {kind: 'Paraphrased questions', asked: 20, teresis: 20, stock: 13},
    {kind: 'Preferences', asked: 10, teresis: 10, stock: 3},
    {kind: 'Changed values (newest wins)', asked: 20, teresis: 20, stock: 13},
    {kind: 'Never told (must say so)', asked: 10, teresis: 10, stock: 10},
  ],
  method:
    'A real Hermes agent was told 200 facts across earlier sessions, then asked 100 questions in fresh sessions with nothing restated. Graded by string match, no AI judge.',
  // README caveats, kept on the page so the claim stays honest.
  caveats: [
    'One run per arm, seed 42.',
    'A 30-fact version of the same run was a tie, 29 of 30 each: the gap appears once memory outgrows the built-in 3,200-character file.',
  ],
  lookup: 'Lookup in the Teresis store took a median of 6.6 ms (p95 8.5 ms).',
};

// 200-fact end-to-end run: same 220 turns in, same 100 questions, same answer model, string-match grading.
export const E2E = {
  method:
    'The same 200 facts and 20 updates go into each system, then 100 questions with the same answer model at temperature 0. Graded by exact string match.',
  rows: [
    {label: 'Teresis + all-minilm', teresis: true, right: 100, answered: 100, updates: 20, paraphrase: 20, writeLlmCalls: 0, ingest: '56 s', ingestS: 56},
    {label: 'Teresis, no model', teresis: true, right: 99, answered: 99, updates: 20, paraphrase: 20, writeLlmCalls: 0, ingest: '23 s', ingestS: 23},
    {label: 'mem0 OSS (infer=True, LLM on write)', right: 93, answered: 93, updates: 20, paraphrase: 19, writeLlmCalls: 88, ingest: '321 s', ingestS: 321},
    {label: 'holographic (Hermes plugin)', right: 64, answered: 98, updates: 0, paraphrase: 5, writeLlmCalls: 0, ingest: '7 s', ingestS: 7},
  ],
  note: 'Answered excludes questions lost to transient HTTP 429 errors from the answer model (1 for Teresis no model, 7 for mem0, 2 for holographic).',
};

export const RESULTS_URL = 'https://github.com/raitoxlol/teresis/tree/main/bench/results';
export const README_BENCH_URL = 'https://github.com/raitoxlol/teresis#head-to-head-longmemeval';

// ---------------------------------------------------------------------------------------------
// Guided terminal. One real session, run in order against an empty store. `rows` is the state of
// memory.db after the step, derived from the same output (ids are the real ones the CLI printed).

export type DemoRow = {id: string; scope: string; fact: string; key?: string; state: 'current' | 'superseded'};
export type DemoStep = {
  id: string;
  /** short label for the step button */
  label: string;
  /** one sentence: what this step proves */
  point: string;
  cmd: string;
  out: string[];
  /** ids touched by this step, to highlight in the table */
  touched: string[];
};

export const DEMO_STEPS: DemoStep[] = [
  {
    id: 'create',
    label: 'Remember a fact',
    point: 'A keyed fact becomes one row.',
    cmd: 'teresis remember "Editor is VS Code" -s user --key user.editor',
    out: ['created 992df7e44c554cc9'],
    touched: ['992df7e44c554cc9'],
  },
  {
    id: 'supersede',
    label: 'Change it',
    point: 'The same key takes a new value. The old one moves to history.',
    cmd: 'teresis remember "Editor is Neovim" -s user --key user.editor',
    out: ['superseded 1e02937788b74b12 (replaced 992df7e44c554cc9)'],
    touched: ['1e02937788b74b12', '992df7e44c554cc9'],
  },
  {
    id: 'duplicate',
    label: 'Say it again',
    point: 'A repeated fact reinforces the same row. No new row.',
    cmd: 'teresis remember "Editor is Neovim" -s user --key user.editor',
    out: ['duplicate 1e02937788b74b12'],
    touched: ['1e02937788b74b12'],
  },
  {
    id: 'recall',
    label: 'Recall it',
    point: 'Recall returns the current value only.',
    cmd: 'teresis recall "which editor" -s user',
    out: ['1e02937788b74b12  [fact · user · key=user.editor · 1.014]', '    Editor is Neovim'],
    touched: ['1e02937788b74b12'],
  },
  {
    id: 'history',
    label: 'Read its history',
    point: 'The old value is still there, marked superseded.',
    cmd: 'teresis history -s user --key user.editor',
    out: [
      '992df7e44c554cc9  [fact · user · key=user.editor · SUPERSEDED]',
      '    Editor is VS Code',
      '1e02937788b74b12  [fact · user · key=user.editor]',
      '    Editor is Neovim',
    ],
    touched: ['992df7e44c554cc9', '1e02937788b74b12'],
  },
  {
    id: 'project',
    label: 'Add a project fact',
    point: 'Scopes are paths. This one belongs to project/atlas.',
    cmd: 'teresis remember "Atlas uses PostgreSQL 16" -s project/atlas --key atlas.database',
    out: ['created 41204422ca6a4eda'],
    touched: ['41204422ca6a4eda'],
  },
  {
    id: 'typo',
    label: 'Misspell the query',
    point: 'The trigram index catches the typo.',
    cmd: 'teresis recall "postgress" -s project/atlas --explain',
    out: [
      '41204422ca6a4eda  [fact · project/atlas · key=atlas.database · 1.000]',
      '    Atlas uses PostgreSQL 16',
      "    why: {'channels': {'trigram': 1.0}, 'relevance': 1.0, 'recency': 1.0}",
    ],
    touched: ['41204422ca6a4eda'],
  },
  {
    id: 'sibling',
    label: 'Add a sibling project',
    point: 'Helios is a sibling of Atlas.',
    cmd: 'teresis remember "Helios runs on MySQL 8" -s project/helios --key helios.database',
    out: ['created a665c5b0ce5d428d'],
    touched: ['a665c5b0ce5d428d'],
  },
  {
    id: 'isolate',
    label: 'Ask from Atlas',
    point: 'Atlas never reads Helios. Only its own database comes back.',
    cmd: 'teresis recall "which database" -s project/atlas',
    out: ['41204422ca6a4eda  [fact · project/atlas · key=atlas.database · 1.014]', '    Atlas uses PostgreSQL 16'],
    touched: ['41204422ca6a4eda'],
  },
  {
    id: 'redact',
    label: 'Paste a secret',
    point: 'The key is redacted before it is stored.',
    cmd: 'teresis remember "Deploy key is sk-proj-abc123def456ghi789jkl012mno345pqr678" -s project/atlas',
    out: ['memory content contained openai_key; stored redacted', 'created 09370dc64487445d'],
    touched: ['09370dc64487445d'],
  },
];

/** memory.db after step index i (0-based). Derived from the outputs above. */
export function demoRows(stepIndex: number): DemoRow[] {
  const rows: DemoRow[] = [];
  if (stepIndex >= 0) rows.push({id: '992df7e44c554cc9', scope: 'user', fact: 'Editor is VS Code', key: 'user.editor', state: stepIndex >= 1 ? 'superseded' : 'current'});
  if (stepIndex >= 1) rows.push({id: '1e02937788b74b12', scope: 'user', fact: 'Editor is Neovim', key: 'user.editor', state: 'current'});
  if (stepIndex >= 5) rows.push({id: '41204422ca6a4eda', scope: 'project/atlas', fact: 'Atlas uses PostgreSQL 16', key: 'atlas.database', state: 'current'});
  if (stepIndex >= 7) rows.push({id: 'a665c5b0ce5d428d', scope: 'project/helios', fact: 'Helios runs on MySQL 8', key: 'helios.database', state: 'current'});
  if (stepIndex >= 9) rows.push({id: '09370dc64487445d', scope: 'project/atlas', fact: 'Deploy key is [REDACTED:openai_key]', state: 'current'});
  return rows;
}

// ---------------------------------------------------------------------------------------------
// Scope explorer. The rule is store.py scope_chain(): a scope, each of its parents, then global.

export const SCOPES = ['global', 'user', 'project', 'project/atlas', 'project/atlas/agent-x', 'project/helios'] as const;

export function scopeChain(scope: string): string[] {
  const parts = scope.split('/').filter(Boolean);
  const chain = parts.map((_, i) => parts.slice(0, parts.length - i).join('/'));
  if (!chain.includes('global')) chain.push('global');
  return chain;
}

// ---------------------------------------------------------------------------------------------
// Works with. Hermes is the native integration; the others connect over MCP.

export const HERMES_HOOKS = [
  {hook: 'prefetch', does: 'Recalls over hermes/<profile>, user and global before each turn.'},
  {hook: 'sync_turn', does: 'Saves the turn as an episode and extracts stated preferences, rules and decisions.'},
  {hook: 'on_memory_write', does: "Mirrors Hermes' built-in memory tool: add, replace, remove."},
  {hook: 'on_pre_compress', does: 'Extracts durable facts from messages about to be compressed.'},
  {hook: 'on_delegation', does: 'Records the subagent task and its result.'},
  {hook: 'subagent · cron · flush', does: 'Read-only. Nothing is written.'},
];

export const INSTALL = {
  brew: 'brew install raitoxlol/tap/teresis',
  tabs: [
    {
      id: 'hermes',
      label: 'Hermes Agent',
      text: 'Copies the provider plugin into the Hermes home, then sets Teresis as the memory provider. Start a new session.',
      code: 'brew install raitoxlol/tap/teresis\nteresis hermes install && hermes config set memory.provider teresis',
    },
    {
      id: 'all',
      label: 'Every agent',
      // setup and doctor landed after the v0.1.0 tag the Homebrew formula builds, so this tab installs from main.
      text: 'Wires Claude Code, Cursor, Codex and Hermes to one memory.db, then proves the round trip. Setup only touches its own entry.',
      code: 'pip install git+https://github.com/raitoxlol/teresis.git\nteresis setup\nteresis doctor',
    },
    {
      id: 'mcp',
      label: 'MCP',
      text: 'Runs the MCP server on stdio. Writes go to the first scope; recall searches every scope given and their parents.',
      code: 'brew install raitoxlol/tap/teresis\nclaude mcp add teresis -- teresis serve --scope project/atlas --scope user',
    },
    {
      id: 'http',
      label: 'HTTP',
      text: 'The same tool names and arguments as MCP, over a local HTTP API. It binds to 127.0.0.1 by default.',
      code: 'teresis http --port 7077 --scope global &\ncurl -s localhost:7077/tools/memory_recall \\\n  -H "Authorization: Bearer $TERESIS_HTTP_TOKEN" -d \'{"query":"deploy"}\'',
    },
    {
      id: 'python',
      label: 'Python',
      text: 'MemoryStore opens the same file the other interfaces use. A keyed write supersedes the older value.',
      code: 'from teresis import MemoryStore\nm = MemoryStore()\nm.remember("Editor is Neovim", scope="user", key="user.editor")\nm.recall("which editor?", scope=["project/atlas", "user"])',
    },
  ],
};
