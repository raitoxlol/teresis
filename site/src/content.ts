// Every number here comes from README.md and bench/results/*.json in this repo.
// Teresis is private for now: no repository link and no "open source" claim on the page.

export type BarRow = {label: string; value: number; display: string; note?: string; highlight?: boolean};

export const HERO = {
  line1: 'Your agents forget.',
  line2: 'Teresis keeps.',
  sub: 'Local long-term memory for AI agents. One SQLite file, no dependencies, and nothing leaves your machine by default.',
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
  {label: 'Teresis + all-minilm', value: 0.654, display: '0.654', note: '22 ms', highlight: true},
  {label: 'Teresis, no model', value: 0.637, display: '0.637', note: '8.4 ms', highlight: true},
  {label: 'holographic (Hermes plugin)', value: 0.563, display: '0.563', note: '10 ms'},
  {label: 'mem0 OSS', value: 0.449, display: '0.449', note: '126 ms'},
  {label: 'Naive LIKE, newest first', value: 0.025, display: '0.025', note: '0.8 ms'},
];

export const LONGMEMEVAL: BarRow[] = [
  {label: 'Teresis + all-minilm', value: 0.936, display: '0.936', note: '26 ms', highlight: true},
  {label: 'mem0 OSS', value: 0.903, display: '0.903', note: '366 ms'},
  {label: 'Teresis, no model', value: 0.882, display: '0.882', note: '25 ms', highlight: true},
  {label: 'holographic (Hermes plugin)', value: 0.859, display: '0.859', note: '23 ms'},
  {label: 'Naive LIKE, newest first', value: 0.195, display: '0.195', note: '6 ms'},
];

export type Step = {title: string; body: string; demo: 'remember' | 'supersede' | 'scopes' | 'channels' | 'local'};

// The five petals, in assembly order: centre, middle pair, outer pair.
export const STEPS: Step[] = [
  {
    title: 'One file keeps it all.',
    body: 'Every fact, preference and decision your agents learn lands in one SQLite file on your machine. No server, no account, no dependencies.',
    demo: 'remember',
  },
  {
    title: 'New facts replace old ones.',
    body: 'Agents repeat themselves and change their minds. A repeated fact reinforces the memory it repeats. A keyed fact replaces its old value, and the history stays for anyone who asks what was true before.',
    demo: 'supersede',
  },
  {
    title: 'Projects never leak.',
    body: 'Scopes are paths. Recall sees a scope and its parents, never its siblings, so project/atlas never reads what project/helios learned.',
    demo: 'scopes',
  },
  {
    title: 'It finds what you meant.',
    body: 'BM25 over stemmed text, trigram matching for typos, and optional embeddings from Ollama or any OpenAI-compatible server for paraphrases.',
    demo: 'channels',
  },
  {
    title: 'Local and deterministic.',
    body: 'No model call per turn, so writes are exact and repeatable. WAL mode lets several agents share one store; the test suite runs four processes writing at once.',
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
    a: 'Hermes Agent natively, anything that speaks MCP or HTTP, such as Claude Code, Codex and Cursor, and a Python API. All of them share the same store.',
  },
  {
    q: 'Can several agents share one memory?',
    a: 'Yes. Scopes keep them apart where they should be apart, and SQLite WAL mode lets several processes write at once.',
  },
  {
    q: 'When can I use it?',
    a: 'Teresis is in private early access. Join the waitlist to get access as it opens.',
  },
];
