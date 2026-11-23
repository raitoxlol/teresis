import {useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode} from 'react';
import {FAQ, STEPS} from './content';
import {
  DEMO_STEPS,
  E2E,
  HERMES_HOOKS,
  INSTALL,
  LIVE,
  type BenchRow,
  type Metric,
  LOCOMO_METRICS,
  LOCOMO_NOTE,
  LOCOMO_ROWS,
  LONGMEMEVAL_METRICS,
  LONGMEMEVAL_NOTE,
  LONGMEMEVAL_ROWS,
  RESULTS_URL,
  SCOPES,
  demoRows,
  scopeChain,
} from './data';
import {Lotus} from './components/Lotus';

const GITHUB = 'https://github.com/raitoxlol/teresis';
const LICENSE = `${GITHUB}/blob/main/LICENSE`;
const LOGO = 'logos/teresis-lockup-white.svg';
const REDUCED = '(prefers-reduced-motion: reduce)';

function cli(line: string) {
  const bracket = line.indexOf('[');
  if (bracket < 0) return line;
  return <>{line.slice(0, bracket)}<span>[</span>{line.slice(bracket + 1)}</>;
}

function CopyButton({text, label = 'Copy commands'}: {text: string; label?: string}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.append(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <button className="btn btn--secondary copy-button" type="button" onClick={copy} aria-label={label}>
      {copied ? 'Copied' : 'Copy'}
      <span className="sr-only" aria-live="polite">{copied ? 'Copied to clipboard.' : ''}</span>
    </button>
  );
}

function LogoLink({footer = false}: {footer?: boolean}) {
  return (
    <a className={footer ? 'brand-lockup brand-lockup--footer' : 'brand-lockup'} href="#top" aria-label="Teresis home">
      <img src={LOGO} alt="Teresis" />
    </a>
  );
}

function useTabKeys(event: KeyboardEvent<HTMLButtonElement>, index: number, count: number, select: (i: number) => void) {
  const next = event.key === 'ArrowRight' || event.key === 'ArrowDown';
  const previous = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
  if (!next && !previous && event.key !== 'Home' && event.key !== 'End') return;
  event.preventDefault();
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (index + (next ? 1 : -1) + count) % count;
  select(target);
  document.getElementById(`${event.currentTarget.id.split('-').slice(0, -1).join('-')}-${target}`)?.focus();
}

function HeroTranscript() {
  return (
    <div className="hero-terminal ui ui-term">
      <div className="terminal-bar">
        <span>teresis · zsh</span>
        <span className="terminal-db">memory.db</span>
      </div>
      <div className="hero-transcript" aria-label="First four guided terminal commands">
        {DEMO_STEPS.slice(0, 4).map((step) => (
          <div className="transcript-command" key={step.id}>
            <div className="command-line"><span aria-hidden="true">$ </span>{step.cmd}</div>
            {step.out.map((line, index) => <div className="output-line" key={`${step.id}-${index}`}>{cli(line)}</div>)}
          </div>
        ))}
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="hero hero--centred ground-surface" data-enter aria-labelledby="hero-title" id="top" style={{'--h': 1} as CSSProperties}>
      <div className="wrap">
        <div className="hero-text">
          <div className="hero-copy">
            <h1 id="hero-title">Local long-term memory for AI agents</h1>
            <p className="hero-lead">Teresis keeps facts, preferences and decisions in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.</p>
            <div className="btn-row hero-actions">
              <a className="btn btn--primary" href="#install">Install Teresis</a>
              <a className="btn btn--secondary" href="#benchmarks">See the benchmarks</a>
            </div>
            <p className="hero-proof">Live Hermes test: <strong>{LIVE.teresis.right}/{LIVE.teresis.asked}</strong> with Teresis, <strong>{LIVE.stock.right}/{LIVE.stock.asked}</strong> with stock memory.</p>
          </div>
          <div className="hero-visual">
            <HeroTranscript />
            <div className="hero-lotus-mark" aria-hidden="true"><Lotus intro grid /></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function GuidedTerminal() {
  const [selected, setSelected] = useState(2);
  const [visibleRowsAt, setVisibleRowsAt] = useState(2);
  const [pending, setPending] = useState(false);
  const [typed, setTyped] = useState('');
  const [touchVersion, setTouchVersion] = useState(0);
  const frame = useRef<number | undefined>(undefined);
  const [lastTouched, setLastTouched] = useState<string[]>([]);

  useEffect(() => () => window.cancelAnimationFrame(frame.current ?? 0), []);

  function runStep(index: number) {
    window.cancelAnimationFrame(frame.current ?? 0);
    setSelected(index);
    setLastTouched(DEMO_STEPS[index].touched);
    setTouchVersion((version) => version + 1);
    const command = DEMO_STEPS[index].cmd;
    setTyped('');

    if (window.matchMedia(REDUCED).matches) {
      setTyped(command);
      setPending(false);
      setVisibleRowsAt(index);
      return;
    }

    setPending(true);
    const started = performance.now();
    const duration = 420;
    const type = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      setTyped(command.slice(0, Math.ceil(command.length * progress)));
      if (progress < 1) frame.current = window.requestAnimationFrame(type);
      else {
        setPending(false);
        setVisibleRowsAt(index);
      }
    };
    frame.current = window.requestAnimationFrame(type);
  }

  function restart() {
    window.cancelAnimationFrame(frame.current ?? 0);
    setSelected(2);
    setVisibleRowsAt(2);
    setPending(false);
    setTyped('');
    setLastTouched([]);
    setTouchVersion((version) => version + 1);
  }

  const shownSteps = DEMO_STEPS.slice(0, selected + 1);
  const rows = demoRows(visibleRowsAt);
  const activeStep = DEMO_STEPS[selected];

  return (
    <section className="section try-section" id="try" aria-labelledby="try-title" style={{'--h': 1, '--hm': 2} as CSSProperties}>
      <div className="wrap">
        <div className="section-heading">
          <h2 id="try-title">Run Teresis in a guided terminal</h2>
          <p>Run a real sequence. The table follows the file after each command.</p>
        </div>
        <div className="try-app ui ui-panel app fill frame" aria-label="Guided terminal and memory database" data-ui-pause-host data-visual>
          <div className="try-app-header">
            <span className="try-app-title">Guided run</span>
            <div className="try-actions">
              <button className="btn btn--primary" type="button" onClick={() => runStep(Math.min(selected + 1, DEMO_STEPS.length - 1))} disabled={selected === DEMO_STEPS.length - 1}>
                Run next command
              </button>
              <button className="btn btn--secondary" type="button" onClick={restart}>Start over</button>
            </div>
          </div>
          <div className="terminal-pane">
            <div className="terminal-bar">
              <span className="terminal-dots" aria-hidden="true"><i /><i /><i /></span>
              <span>teresis · zsh</span>
            </div>
            <div className="terminal-output">
              {shownSteps.map((step, index) => (
                <div className="terminal-entry" key={step.id}>
                  <div className="command-line"><span aria-hidden="true">$ </span>{pending && index === selected ? typed : step.cmd}</div>
                  {(!pending || index !== selected) && (
          <div className="output-copy" aria-live="polite" aria-atomic="true">
                      {step.out.map((line, lineIndex) => <div className="output-line" key={`${step.id}-${lineIndex}`}>{cli(line)}</div>)}
                    </div>
                  )}
                </div>
              ))}
              <span className="terminal-cursor" aria-hidden="true" />
            </div>
          </div>
          <div className="memory-pane">
            <div className="memory-head"><span>memory.db · {rows.length} rows</span></div>
            <div className="memory-table" role="table" aria-label="Memory database rows">
              <div className="memory-table-head" role="row">
                <span role="columnheader">Scope</span><span role="columnheader">Fact</span><span role="columnheader">Key</span><span role="columnheader">State</span>
              </div>
              {rows.map((row) => (
                <div
                  className={`memory-row${row.state === 'superseded' ? ' is-superseded' : ''}${lastTouched.includes(row.id) ? ' is-touched' : ''}`}
                  role="row"
                  key={`${row.id}-${lastTouched.includes(row.id) ? touchVersion : 0}`}
                >
                  <span role="cell">{row.scope}</span>
                  <span role="cell" className="memory-fact">{row.fact}</span>
                  <span role="cell" className="memory-key">{row.key ?? '—'}</span>
                  <span role="cell" className="memory-state">{row.state}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="try-controls">
          <div className="step-list" aria-label="Guided terminal steps">
            {DEMO_STEPS.map((step, index) => (
              (() => {
                const status = index < selected ? 'done' : index === selected ? 'current' : 'upcoming';
                return (
              <button
                className={`step-button is-${status}${selected === index ? ' is-selected' : ''}`}
                type="button"
                key={step.id}
                aria-pressed={selected === index}
                aria-current={selected === index ? 'step' : undefined}
                aria-label={`${index + 1}. ${step.label}. ${status}. ${step.point}`}
                onClick={() => runStep(index)}
              >
                <span className="step-number">{index + 1}</span>
                <span className="step-label">{step.label}</span>
                <span className="step-point">{step.point}</span>
                <span className="step-state">{status}</span>
              </button>
                );
              })()
            ))}
          </div>
          <span className="sr-only" aria-live="polite">{pending ? `Running ${activeStep.label}.` : ''}</span>
        </div>
      </div>
    </section>
  );
}

function ScopeExplorer() {
  const [selectedScope, setSelectedScope] = useState('project/atlas/agent-x');
  const chain = useMemo(() => scopeChain(selectedScope), [selectedScope]);
  const children: Record<string, string[]> = {
    root: ['global', 'user', 'project'],
    project: ['project/atlas', 'project/helios'],
    'project/atlas': ['project/atlas/agent-x'],
  };

  function pick(event: KeyboardEvent<HTMLButtonElement>, scope: string) {
    const keys = ['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const current = SCOPES.indexOf(scope as typeof SCOPES[number]);
    const direction = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
    const next = (current + direction + SCOPES.length) % SCOPES.length;
    const target = SCOPES[next];
    setSelectedScope(target);
    document.getElementById(`scope-${target.replaceAll('/', '-')}`)?.focus();
  }

  function scopeButton(scope: string) {
    const read = chain.includes(scope);
    return (
      <div className="scope-node" key={scope}>
        <button
          className="scope-radio"
          type="button"
          role="radio"
          id={`scope-${scope.replaceAll('/', '-')}`}
          aria-checked={selectedScope === scope}
          tabIndex={selectedScope === scope ? 0 : -1}
          onClick={() => setSelectedScope(scope)}
          onKeyDown={(event) => pick(event, scope)}
        >
          <span className="scope-path">{scope}</span>
          <span className={read ? 'scope-read' : 'scope-never'}>{read ? 'Read' : 'Never read'}</span>
        </button>
        {children[scope] && <div className="scope-children" role="group">{children[scope].map(scopeButton)}</div>}
      </div>
    );
  }

  return (
    <div className="scope-card card ui ui-scope">
      <div className="scope-card-head">
        <h3>Recall scope</h3>
        <p>Choose where recall starts.</p>
      </div>
      <div className="scope-tree" role="radiogroup" aria-label="Choose a memory scope">
        {children.root.map(scopeButton)}
      </div>
      <p className="scope-rule">Recall reads a scope and its parents, never a sibling. User is a sibling of projects.</p>
    </div>
  );
}

function HowSection() {
  const cards: {title: string; body: string; variant: string; rows: {label: string; value: ReactNode}[]}[] = [
    {title: STEPS[0].title, body: 'One SQLite file holds facts and preferences for every agent.', variant: 'file', rows: [{label: 'File', value: <code>~/.local/share/teresis/memory.db</code>} ]},
    {title: STEPS[1].title, body: 'Keyed updates keep replaced facts in history.', variant: 'history', rows: [{label: 'Superseded', value: <code>Editor is VS Code</code>}, {label: 'Current', value: <code>Editor is Neovim</code>}]},
    {title: STEPS[3].title, body: 'BM25 and trigrams find stems and typos. Embeddings are optional.', variant: 'search', rows: [{label: 'Match', value: cli(DEMO_STEPS[6].out[0])}]},
    {title: STEPS[4].title, body: 'Writes use zero LLM calls. WAL mode allows shared writes.', variant: 'writes', rows: [{label: 'LLM calls / write', value: <code>0</code>}]},
  ];

  return (
    <section className="section how-section g2m" id="how" aria-labelledby="how-title" style={{'--h': 1, '--hm': 2} as CSSProperties}>
      <div className="wrap how-wrap">
        <div className="group how-scope-group">
          <div className="section-heading">
            <h2 id="how-title">How Teresis keeps facts straight</h2>
            <p>Each fact has a scope, key and history. Recall reads only its path.</p>
          </div>
          <ScopeExplorer />
        </div>
        <div className="group how-cards-group">
          <div className="method-cards">
            {cards.map((card) => (
              <article className={`method-card card method-card--${card.variant}`} key={card.title}>
                <h3>{card.title}</h3>
                <p>{card.body}</p>
                <div className="method-fragment ui ui-panel" data-visual>
                  {card.rows.map((row) => <div className="fragment-row" key={row.label}><span>{row.label}</span><strong>{row.value}</strong></div>)}
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

const diagramSpec = {
  layout: 'hub',
  center: {label: 'memory.db', icon: 'ui:database'},
  spokes: [
    {label: 'Hermes Agent', icon: 'hermes-agent'},
    {label: 'Claude Code', icon: 'claude-code'},
    {label: 'Codex', icon: 'codex'},
    {label: 'Cursor', icon: 'cursor'},
  ],
  motion: {pulse: 'dot', cycle: 3.2},
  ground: 'none',
  alt: 'Hermes Agent, Claude Code, Codex and Cursor share memory.db',
};

function WorksWith() {
  return (
    <section className="section works-section" id="works-with" aria-labelledby="works-title" style={{'--h': 1, '--hm': 2} as CSSProperties}>
      <div className="wrap">
        <div className="section-heading">
          <h2 id="works-title">Works with agents and APIs</h2>
          <p>Hermes uses a native memory provider. The other agents connect through MCP.</p>
        </div>
        <div className="works-layout">
          <div className="works-pair" aria-label="Teresis native memory provider for Hermes Agent">
            <p className="works-pair-label">Native memory provider</p>
            <div className="works-brands">
              <div className="works-logo works-logo--teresis"><span className="works-icon-tile"><img src="logos/teresis-mark.svg" alt="" /></span></div>
              <span className="pair-divider" aria-hidden="true">+</span>
              <div className="works-logo"><span className="works-icon-tile"><img src="logos/hermes-agent.svg" alt="" /></span></div>
            </div>
            <ul className="hooks-list">
              {HERMES_HOOKS.map((entry) => <li key={entry.hook}><code>{entry.hook}</code><span>{entry.does}</span></li>)}
            </ul>
          </div>
          <div className="hub-panel panel" aria-label="Connected clients share one memory database" data-visual>
            <div className="dg" data-diagram={JSON.stringify(diagramSpec)} />
            <span className="hub-center-label" aria-hidden="true">memory.db</span>
          </div>
        </div>
        <div className="mcp-tools" aria-label="MCP clients and APIs">
          {[
            ['claude-code', 'Claude Code', 'MCP'],
            ['codex', 'Codex', 'MCP'],
            ['cursor', 'Cursor', 'MCP'],
          ].map(([id, name, kind]) => (
            <div className="tool-card" key={id}><span className="tool-icon-tile"><img src={`assets/icons/${id}.svg`} alt="" /></span><strong>{name}</strong><span>{kind}</span></div>
          ))}
          <div className="tool-card"><span className="tool-icon-tile tool-glyph">HTTP</span><strong>HTTP</strong><span>Local HTTP API</span></div>
          <div className="tool-card"><span className="tool-icon-tile tool-glyph">Py</span><strong>Python</strong><span>Python API</span></div>
        </div>
      </div>
    </section>
  );
}

function Statement() {
  return (
    <section className="section section--keeps statement-section ground-surface" id="keeps" aria-labelledby="keeps-title" data-statement style={{'--h': 1, '--hm': 1} as CSSProperties}>
      <div className="wrap statement-wrap">
        <div className="statement-copy" data-m-loop>
          <h2 id="keeps-title" className="keeps-h mo-lt__type" data-moment="liquid-type">Your agents forget. <span className="keeps">Teresis keeps.</span></h2>
          <p className="keeps-sub">τήρησις is Greek for faithful keeping.</p>
        </div>
        <Lotus className="keeps-mark statement-lotus" step={6} grid />
      </div>
    </section>
  );
}

function TabButtons({items, active, select, prefix}: {items: {id: string; label: string}[]; active: number; select: (i: number) => void; prefix: string}) {
  return (
    <div className="tabs" role="tablist" aria-label={prefix === 'bench' ? 'Benchmark results' : 'Install methods'}>
      {items.map((item, index) => (
        <button
          className="tab"
          type="button"
          role="tab"
          id={`${prefix}-tab-${index}`}
          aria-controls={prefix === 'install' ? `install-panel-${index} install-screen-${index}` : `bench-panel-${index}`}
          aria-selected={active === index}
          tabIndex={active === index ? 0 : -1}
          key={item.id}
          onClick={() => select(index)}
          onKeyDown={(event) => useTabKeys(event, index, items.length, select)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function PairBars() {
  return (
    <div className="kind-results">
      {LIVE.byKind.map((row) => (
        <div className="kind-row" key={row.kind}>
          <span className="kind-label">{row.kind}</span>
          <div className="kind-bar-pair">
            <div className="kind-bar"><span>Teresis</span><i><b style={{width: `${row.teresis / row.asked * 100}%`}} /></i><strong>{row.teresis}/{row.asked}</strong></div>
            <div className="kind-bar"><span>Stock</span><i><b style={{width: `${row.stock / row.asked * 100}%`}} /></i><strong>{row.stock}/{row.asked}</strong></div>
          </div>
        </div>
      ))}
    </div>
  );
}

function E2ETable() {
  return (
    <div className="e2e-table-wrap">
      <table className="e2e-table">
        <thead><tr><th>System</th><th>Right / answered</th><th>Updates /20</th><th>Paraphrase /20</th><th>Write LLM calls</th><th>Ingest time</th></tr></thead>
        <tbody>{E2E.rows.map((row) => (
          <tr key={row.label} className={row.teresis ? 'is-teresis' : ''}>
            <th scope="row">{row.label}</th><td>{row.right}/{row.answered}</td><td>{row.updates}/20</td><td>{row.paraphrase}/20</td><td>{row.writeLlmCalls}</td><td>{row.ingest}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="bench-note">{E2E.method}</p><p className="bench-note">{E2E.note}</p>
    </div>
  );
}

function MetricRows({rows, metrics, note, label}: {rows: BenchRow[]; metrics: Metric[]; note: string; label: string}) {
  const [metric, setMetric] = useState(metrics[0].id);
  const [sort, setSort] = useState<'score' | 'time'>('score');
  const [revision, setRevision] = useState(0);
  const ordered = [...rows].sort((a, b) => sort === 'score' ? (b.scores[metric] ?? 0) - (a.scores[metric] ?? 0) : a.p50ms - b.p50ms);

  function changeMetric(id: string) {
    setMetric(id);
    setRevision((value) => value + 1);
  }

  function changeSort(next: 'score' | 'time') {
    setSort(next);
    setRevision((value) => value + 1);
  }

  return (
    <div className="metric-results">
      <div className="metric-controls">
        <div className="switch-group" role="group" aria-label={`${label} metric`}>
          <span>Metric</span>
          {metrics.map((item) => <button type="button" key={item.id} aria-pressed={metric === item.id} title={item.hint} onClick={() => changeMetric(item.id)}>{item.label}</button>)}
        </div>
        <div className="switch-group" role="group" aria-label="Sort by">
          <span>Sort by</span>
          <button type="button" aria-pressed={sort === 'score'} onClick={() => changeSort('score')}>Score</button>
          <button type="button" aria-pressed={sort === 'time'} onClick={() => changeSort('time')}>Query time</button>
        </div>
      </div>
      <ol className="metric-list" aria-label={`${label} results`}>
        {ordered.map((row) => {
          const value = row.scores[metric] ?? 0;
          return (
            <li className={row.teresis ? 'metric-row is-teresis' : 'metric-row'} key={`${row.label}-${revision}`}>
              <span className="metric-name">{row.label}</span>
              <span className="metric-track"><i style={{width: `${value * 100}%`}} /></span>
              <strong className="metric-value">{value.toFixed(3)}</strong>
              <span className="metric-time">{row.p50}</span>
            </li>
          );
        })}
      </ol>
      <p className="bench-note">{note}</p>
    </div>
  );
}

function BenchmarkExplorer() {
  const [active, setActive] = useState(0);
  const tabs = [
    {id: 'live', label: 'Live in Hermes'},
    {id: 'e2e', label: '200-fact run'},
    {id: 'longmemeval', label: 'LongMemEval'},
    {id: 'locomo', label: 'LoCoMo'},
  ];

  return (
    <section className="section benchmark-section ground-surface" id="benchmarks" aria-labelledby="bench-title" style={{'--h': 1, '--hm': 2} as CSSProperties}>
      <div className="wrap">
        <div className="section-heading">
          <h2 id="bench-title">Teresis benchmark results</h2>
          <p>Compare the live Hermes test with retrieval results and a 200-fact run.</p>
        </div>
        <div className="bench-interface ui ui-panel" data-visual>
        <TabButtons items={tabs} active={active} select={setActive} prefix="bench" />
        <div className="bench-panel" role="tabpanel" id="bench-panel-0" aria-labelledby="bench-tab-0" hidden={active !== 0}>
        <div className="live-totals">
            <div><strong>{LIVE.teresis.right}/{LIVE.teresis.asked}</strong><span>{LIVE.teresis.label}</span></div>
            <div><strong>{LIVE.stock.right}/{LIVE.stock.asked}</strong><span>{LIVE.stock.label}</span></div>
          </div>
          <h3>By kind of question</h3>
          <PairBars />
          <p className="bench-note">{LIVE.method}</p>
          <div className="caveats">{LIVE.caveats.map((caveat) => <p className="bench-note" key={caveat}>{caveat}</p>)}</div>
          <p className="bench-note">{LIVE.lookup}</p>
        </div>
        <div className="bench-panel" role="tabpanel" id="bench-panel-1" aria-labelledby="bench-tab-1" hidden={active !== 1}><E2ETable /></div>
        <div className="bench-panel" role="tabpanel" id="bench-panel-2" aria-labelledby="bench-tab-2" hidden={active !== 2}>
          <MetricRows rows={LONGMEMEVAL_ROWS} metrics={LONGMEMEVAL_METRICS} note={LONGMEMEVAL_NOTE} label="LongMemEval" />
        </div>
        <div className="bench-panel" role="tabpanel" id="bench-panel-3" aria-labelledby="bench-tab-3" hidden={active !== 3}>
          <MetricRows rows={LOCOMO_ROWS} metrics={LOCOMO_METRICS} note={LOCOMO_NOTE} label="LoCoMo" />
        </div>
        <a className="link results-link" href={RESULTS_URL} target="_blank" rel="noopener noreferrer">Read the result files on GitHub</a>
        </div>
      </div>
    </section>
  );
}

function InstallSection() {
  const [active, setActive] = useState(0);
  const current = INSTALL.tabs[active];

  return (
    <section className="section install-section ground-surface" id="install" aria-labelledby="install-title" style={{'--h': 1, '--hm': 1} as CSSProperties}>
      <div className="wrap">
        <div className="section-heading">
          <h2 id="install-title">Install Teresis</h2>
          <p>A native Hermes provider, MCP server, local HTTP API and Python API share one SQLite file.</p>
        </div>
        <div className="install-body">
          <div className="install-left">
            {INSTALL.tabs.map((tab, index) => (
              <div className="install-description" role="tabpanel" id={`install-panel-${index}`} aria-labelledby={`install-tab-${index}`} hidden={active !== index} key={tab.id}>
                <p>{tab.text}</p>
              </div>
            ))}
            <TabButtons items={INSTALL.tabs} active={active} select={setActive} prefix="install" />
            <dl className="install-specs">
              <div><dt>File</dt><dd>~/.local/share/teresis/memory.db</dd></div>
              <div><dt>Dependencies</dt><dd>none</dd></div>
              <div><dt>Licence</dt><dd>Apache 2.0</dd></div>
            </dl>
          </div>
          <div className="install-right">
            {INSTALL.tabs.map((tab, index) => (
              <div className="code-window ui ui-panel ui-code frame" data-ui="code" id={`install-screen-${index}`} role="tabpanel" aria-labelledby={`install-tab-${index}`} hidden={active !== index} key={`${tab.id}-code`}>
                <div className="code-window-bar"><span>{tab.label}</span><CopyButton text={tab.code} label={`Copy ${tab.label} commands`} /></div>
                <pre><code>{tab.code}</code></pre>
              </div>
            ))}
          </div>
        </div>
        <span className="sr-only" aria-live="polite">Selected: {current.label}</span>
      </div>
    </section>
  );
}

function Questions() {
  return (
    <section className="section questions-section g2m" id="questions" aria-labelledby="questions-title" style={{'--h': 1, '--hm': 2} as CSSProperties}>
      <div className="wrap questions-wrap">
        <div className="questions-left">
          <h2 id="questions-title">Questions about Teresis</h2>
          <div className="questions-visual frame" data-visual><Lotus step={6} grid /></div>
        </div>
        <div className="faq">
          {FAQ.map((item) => <details className="faq__item" open key={item.q}><summary>{item.q}</summary><p>{item.a}</p></details>)}
        </div>
      </div>
    </section>
  );
}

function Closing() {
  return (
    <footer className="footer closing footer-dark" id="contact" aria-labelledby="close-title">
      <div className="wrap closing-wrap">
        <div className="closing-cta">
          <div className="closing-copy">
            <h2 id="close-title">Keep the file on your machine</h2>
            <p className="greek-line">Apache 2.0 · One SQLite file.</p>
            <div className="close-command"><code>{INSTALL.brew}</code><CopyButton text={INSTALL.brew} label="Copy the Homebrew install command" /></div>
            <a className="link" href={GITHUB} target="_blank" rel="noopener noreferrer">Read the source on GitHub</a>
          </div>
          <div className="closing-lotus" aria-hidden="true"><Lotus step={6} grid /></div>
        </div>
        <div className="closing-links">
          <div className="footer-columns">
            <div className="footer-news">
              <LogoLink footer />
              <p>Release notes for Teresis.</p>
              <form className="form" data-endpoint={`${import.meta.env.BASE_URL}api/waitlist`} data-sent="You are subscribed to release notes." noValidate>
                <div className="field field--full">
                  <label htmlFor="rn-email">Email</label>
                  <input id="rn-email" name="email" type="email" required autoComplete="email" inputMode="email" aria-describedby="rn-email-err" />
                  <p className="field__error" id="rn-email-err" hidden>Write an email address with an @.</p>
                </div>
                <div className="btn-row"><button className="btn btn--secondary" type="submit">Subscribe to release notes</button></div>
                <p className="form__status" role="status" data-form-status />
                <p className="t-small muted">Release notes only.</p>
              </form>
            </div>
            <div className="footer-col"><h3>Page</h3><a href="#try">Try it</a><a href="#how">Method</a><a href="#works-with">Works with</a><a href="#benchmarks">Benchmarks</a><a href="#questions">Questions</a></div>
            <div className="footer-col"><h3>Source</h3><a href={GITHUB} target="_blank" rel="noopener noreferrer">GitHub</a><a href={LICENSE} target="_blank" rel="noopener noreferrer">Apache 2.0</a><a href={RESULTS_URL} target="_blank" rel="noopener noreferrer">Benchmark results</a></div>
          </div>
          <div className="footer-legal"><span>Apache 2.0 · τήρησις, faithful keeping · Product names and logos are trademarks of their owners.</span></div>
        </div>
      </div>
    </footer>
  );
}

export function App() {
  const [activeNav, setActiveNav] = useState('');

  useEffect(() => {
    const sections = [...document.querySelectorAll<HTMLElement>('main > section[id]')];
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActiveNav(visible.target.id);
    }, {rootMargin: '-25% 0px -60% 0px', threshold: [0, 0.15, 0.4, 0.7]});
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const navItems = [
    ['try', 'Try it'],
    ['how', 'Method'],
    ['works-with', 'Works with'],
    ['benchmarks', 'Benchmarks'],
    ['questions', 'Questions'],
  ];

  return (
    <>
      <a className="skip-link" href="#top">Skip to content</a>
      <header className="nav nav--centre">
        <div className="wrap nav__bar">
          <LogoLink />
          <nav className="nav__links" aria-label="Sections">
            {navItems.map(([id, label]) => <div className="nav__item" key={id}><a className="nav__link" href={`#${id}`} aria-current={activeNav === id ? 'page' : undefined}>{label}</a></div>)}
            <div className="nav__item"><a className="nav__link" href={GITHUB} target="_blank" rel="noopener noreferrer">GitHub</a></div>
          </nav>
          <div className="nav__actions"><a className="btn btn--primary" href="#install">Install Teresis</a></div>
          <button className="nav__toggle btn btn--secondary" type="button" aria-expanded="false" aria-label="Open menu"><span aria-hidden="true">Menu</span></button>
        </div>
      </header>
      <main id="main">
        <Hero />
        <GuidedTerminal />
        <HowSection />
        <WorksWith />
        <Statement />
        <BenchmarkExplorer />
        <InstallSection />
        <Questions />
      </main>
      <Closing />
    </>
  );
}
