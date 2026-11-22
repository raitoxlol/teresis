// Every number here comes from README.md and bench/results/*.json in this repo.
// Teresis is private for now: no repository link and no "open source" claim on the page.

export type BarRow = {label: string; value: number; display: string; note?: string; highlight?: boolean};

export const HERO = {
  line1: 'Your agents forget.',
  line2: 'Teresis keeps.',
  sub: 'Local memory for autonomous agents, native to Hermes and shared with Claude Code, Codex and every MCP client. Fully local by default.',
  proof: {teresis: '100/100', stock: '60/100'},
};

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

export const LIVE_METHOD =
  'A real Hermes agent was told 200 facts across earlier sessions, then asked 100 questions in fresh sessions with nothing restated. Graded by string match, no AI judge.';

export const LOCOMO: BarRow[] = [
  {label: 'Teresis + all-minilm + reranker', value: 0.718, display: '0.718', note: '738 ms', highlight: true},
  {label: 'Teresis + all-minilm', value: 0.664, display: '0.664', note: '37 ms', highlight: true},
  {label: 'Teresis, no model', value: 0.641, display: '0.641', note: '17 ms', highlight: true},
  {label: 'total-agent-memory (no reranker)', value: 0.612, display: '0.612', note: '45 ms'},
  {label: 'SQLite FTS5 (BM25)', value: 0.606, display: '0.606', note: '0.5 ms'},
  {label: 'LanceDB hybrid', value: 0.589, display: '0.589', note: '19 ms'},
  {label: 'mem0 OSS hybrid (infer=False)', value: 0.564, display: '0.564', note: '221 ms'},
  {label: 'holographic (Hermes plugin)', value: 0.562, display: '0.562', note: '10 ms'},
  {label: 'ChromaDB', value: 0.448, display: '0.448', note: '11 ms'},
  {label: 'Naive LIKE, newest first', value: 0.025, display: '0.025', note: '0.8 ms'},
];

export const LONGMEMEVAL: BarRow[] = [
  {label: 'Teresis + all-minilm + reranker', value: 0.949, display: '0.949', note: '2.8 s', highlight: true},
  {label: 'Teresis + all-minilm', value: 0.944, display: '0.944', note: '51 ms', highlight: true},
  {label: 'mem0 OSS hybrid (infer=False)', value: 0.932, display: '0.932', note: '714 ms'},
  {label: 'LanceDB hybrid', value: 0.930, display: '0.930', note: '23 ms'},
  {label: 'ChromaDB', value: 0.904, display: '0.904', note: '27 ms'},
  {label: 'total-agent-memory (no reranker)', value: 0.900, display: '0.900', note: '108 ms'},
  {label: 'Teresis, no model', value: 0.888, display: '0.888', note: '19 ms', highlight: true},
  {label: 'SQLite FTS5 (BM25)', value: 0.881, display: '0.881', note: '0.5 ms'},
  {label: 'holographic (Hermes plugin)', value: 0.859, display: '0.859', note: '23 ms'},
  {label: 'Naive LIKE, newest first', value: 0.195, display: '0.195', note: '6 ms'},
];

export type Step = {title: string; body: string; demo: 'remember' | 'supersede' | 'scopes' | 'channels' | 'local'};

// The five petals, in assembly order: centre, middle pair, outer pair.
export const STEPS: Step[] = [
  {
    title: 'One file keeps it all.',
    body: 'Every fact, preference and decision your agents learn lands in one SQLite file, one store shared by every agent you run. No server, no account, no dependencies.',
    demo: 'remember',
  },
  {
    title: 'New facts replace old ones.',
    body: 'Agents repeat themselves and change their minds. A repeated fact reinforces; a keyed fact supersedes its old value, and history keeps what was true before. Secrets are redacted on write.',
    demo: 'supersede',
  },
  {
    title: 'Projects never leak.',
    body: 'Scopes are paths: global, project/atlas, hermes/main. Recall sees a scope and its parents, never its siblings; subagents and crons run read-only.',
    demo: 'scopes',
  },
  {
    title: 'It finds what you meant.',
    body: 'BM25 over stemmed text, trigram matching for typos, and optional embeddings from Ollama or any OpenAI-compatible server for paraphrases.',
    demo: 'channels',
  },
  {
    title: 'Local and deterministic.',
    body: 'Zero LLM calls per turn, so writes are exact and repeatable. WAL mode lets several agents share one store; the test suite runs four processes writing at once.',
    demo: 'local',
  },
];

export const SNIPPETS = {
  Hermes: `python3 -m teresis hermes install
hermes config set memory.provider teresis`,
  MCP: `claude mcp add teresis -- python3 -m teresis serve \\
  --scope project/atlas --scope user`,
  HTTP: `python3 -m teresis http --port 7077 --scope global &
curl -s localhost:7077/tools/memory_recall \\
  -H "Authorization: Bearer $TERESIS_HTTP_TOKEN" -d '{"query":"deploy"}'`,
  Python: `from teresis import MemoryStore
m = MemoryStore()
m.remember("Editor is Neovim", scope="user", key="user.editor")
m.recall("which editor?", scope=["project/atlas", "user"])`,
} as const;

export const FAQ = [
  {
    q: 'Does anything leave my machine?',
    a: 'No. Teresis stores everything in one local SQLite file. Embeddings are optional; if you turn them on, they come from an Ollama or OpenAI-compatible server you choose.',
  },
  {
    q: 'Do I need a GPU or a model?',
    a: 'No. Without embeddings it runs on keyword and fuzzy search alone, in milliseconds on a laptop CPU. Embeddings add paraphrase matching.',
  },
  {
    q: 'Which agents does it work with?',
    a: 'A native memory provider for Hermes Agent, an MCP server for Claude Code, Codex, Cursor and every other MCP client, plus HTTP and Python APIs. All share one store.',
  },
  {
    q: 'Can several agents share one memory?',
    a: 'Yes. Scopes keep them apart where they should be apart, and SQLite WAL mode lets several processes write at once. Subagents and crons can run read-only, so background work never poisons memory.',
  },
  {
    q: 'When can I use it?',
    a: 'Teresis is in private early access. Join the waitlist to get access as it opens.',
  },
];
