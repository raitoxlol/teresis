// Every number here comes from README.md and bench/results/*.json in this repo.

export const REPO = 'https://git.cafe/w/teresis';

export type BarRow = {label: string; value: number; display: string; note?: string; highlight?: boolean};

export const LIVE_TOTAL: BarRow[] = [
  {label: 'Hermes + Teresis', value: 100, display: '100/100', highlight: true},
  {label: 'Stock Hermes (built-in memory)', value: 60, display: '60/100'},
];

export const LIVE_BY_KIND = [
  {kind: 'Direct facts', asked: 40, teresis: 40, stock: 21},
  {kind: 'Paraphrased questions', asked: 20, teresis: 20, stock: 13},
  {kind: 'Preferences', asked: 10, teresis: 10, stock: 3},
  {kind: 'Changed values (newest wins)', asked: 20, teresis: 20, stock: 13},
  {kind: 'Never told (must say so)', asked: 10, teresis: 10, stock: 10},
];

export const LOCOMO: BarRow[] = [
  {label: 'Teresis + all-minilm', value: 0.654, display: '0.654', note: 'query p50 22 ms', highlight: true},
  {label: 'Teresis, no model', value: 0.637, display: '0.637', note: 'query p50 8.4 ms', highlight: true},
  {label: 'holographic (Hermes plugin)', value: 0.563, display: '0.563', note: 'query p50 10 ms'},
  {label: 'mem0 OSS', value: 0.449, display: '0.449', note: 'query p50 126 ms'},
  {label: 'Naive LIKE, newest first', value: 0.025, display: '0.025', note: 'query p50 0.8 ms'},
];

export const LONGMEMEVAL: BarRow[] = [
  {label: 'Teresis + all-minilm', value: 0.936, display: '0.936', note: 'query p50 26 ms', highlight: true},
  {label: 'mem0 OSS', value: 0.903, display: '0.903', note: 'query p50 366 ms'},
  {label: 'Teresis, no model', value: 0.882, display: '0.882', note: 'query p50 25 ms', highlight: true},
  {label: 'holographic (Hermes plugin)', value: 0.859, display: '0.859', note: 'query p50 23 ms'},
  {label: 'Naive LIKE, newest first', value: 0.195, display: '0.195', note: 'query p50 6 ms'},
];

export const PILLARS = [
  {
    key: 'writes',
    title: 'Writes reconcile',
    body: 'Exact and near duplicates reinforce the existing memory instead of adding rows. A key makes a memory an updatable slot: the new value supersedes the old one, and history keeps the full timeline.',
  },
  {
    key: 'scopes',
    title: 'Scopes are paths',
    body: 'global, user, project/atlas, project/atlas/agent-x. Recall sees the scope plus its parents, never its siblings, so projects do not leak into each other.',
  },
  {
    key: 'retrieval',
    title: 'Three retrieval channels',
    body: 'BM25 over a Porter-stemmed FTS5 index, trigram fuzzy match, and optional embeddings from Ollama or any OpenAI-compatible server. Without a model it stays fully functional and lexical.',
  },
  {
    key: 'local',
    title: 'Local and deterministic',
    body: 'One SQLite file, no dependencies, no model call per turn. WAL mode and BEGIN IMMEDIATE writes let several agents share one store; the test suite runs 4 processes writing at once.',
  },
] as const;

export const SNIPPETS = {
  hermes: `PYTHONPATH=/path/to/teresis/src python3 -m teresis hermes install
hermes config set memory.provider teresis`,
  mcp: `claude mcp add teresis -- env PYTHONPATH=/path/to/teresis/src \\
  python3 -m teresis serve --scope project/atlas --scope user`,
  http: `export TERESIS_HTTP_TOKEN="$(openssl rand -hex 16)"
python3 -m teresis http --port 7077 --scope global &
curl -s localhost:7077/tools/memory_recall \\
  -H "Authorization: Bearer $TERESIS_HTTP_TOKEN" -d '{"query":"deploy"}'`,
  python: `from teresis import MemoryStore
m = MemoryStore()
m.remember("Editor is Neovim", scope="user", key="user.editor")  # supersedes older value
hits = m.recall("how should I answer", scope=["project/atlas", "user"])`,
};
