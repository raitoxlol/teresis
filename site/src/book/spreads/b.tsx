import {useState, useSyncExternalStore} from 'react';
import {CopyButton, useTabKeys, cli} from '../../App';
import {NAV_ITEMS} from '../Book';
import {FAQ, LIVE_BY_KIND} from '../../content';
import {
  E2E, GITHUB, INSTALL, LIVE, LOCOMO_METRICS, LOCOMO_NOTE, LOCOMO_ROWS,
  LONGMEMEVAL_METRICS, LONGMEMEVAL_NOTE, LONGMEMEVAL_ROWS, RESULTS_URL,
  type BenchRow, type Metric,
} from '../../data';
import './b.css';

const BASE = import.meta.env.BASE_URL;
const MARK = `${BASE}logos/teresis-mark.svg`;

function Tabs({items, active, select, prefix, label, vertical = false}: {
  items: {id: string; label: string}[];
  active: number;
  select: (index: number) => void;
  prefix: string;
  label: string;
  vertical?: boolean;
}) {
  return (
    <div className="sb-tabs" role="tablist" aria-label={label} aria-orientation={vertical ? 'vertical' : 'horizontal'}>
      {items.map((item, index) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          id={`sb-${prefix}-tab-${index}`}
          aria-controls={`sb-${prefix}-panel-${index}`}
          aria-selected={active === index}
          tabIndex={active === index ? 0 : -1}
          onClick={() => select(index)}
          onKeyDown={(event) => useTabKeys(event, index, items.length, select)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function Bar({fraction}: {fraction: number}) {
  return <span className="sb-bar" aria-hidden="true"><span style={{width: `${fraction * 100}%`}} /></span>;
}

export function LiveBenchPage() {
  return (
    <div className="sb-page sb-live" data-book-print="benchmarks.webp">
      <h2 className="sb-title">Benchmarks</h2>
      <div className="sb-totals">
        {[LIVE.teresis, LIVE.stock].map(({label, right, asked}) => (
          <div key={label}>
            <p>{label}</p>
            <strong>{right}/{asked}</strong>
            <Bar fraction={right / asked} />
          </div>
        ))}
      </div>
      <table className="sb-ledger">
        <thead><tr><th scope="col">Question kind</th><th scope="col">Asked</th><th scope="col">Teresis</th><th scope="col">Stock</th></tr></thead>
        <tbody>
          {LIVE_BY_KIND.map(({kind, asked, teresis, stock}) => (
            <tr key={kind}>
              <th scope="row">{kind.replace(' (', '\n(')}</th>
              <td>{asked}</td><td>{teresis}</td><td>{stock}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sb-bench-note">Hermes learned 200 facts across sessions, then answered 100 questions in fresh sessions. Answers were graded by string match. With 30 facts, both systems scored 29/30.</p>
    </div>
  );
}

const BENCH_TABS = [
  {id: 'e2e', label: '200-fact run'},
  {id: 'longmemeval', label: 'LongMemEval'},
  {id: 'locomo', label: 'LoCoMo'},
];

function EndToEndLedger() {
  return (
    <>
      <table className="sb-ledger sb-e2e-ledger" data-book-print="evaluation.webp">
        <thead><tr><th scope="col">System</th><th scope="col">Right</th><th scope="col">LLM calls<br />on write</th></tr></thead>
        <tbody>
          {E2E.rows.map(({label, right, answered, writeLlmCalls}) => (
            <tr key={label}>
              <th scope="row">{label}<Bar fraction={right / E2E.rows[0].answered} /></th>
              <td aria-label={`${right} right out of ${answered} answered`}>{right}</td><td>{writeLlmCalls}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sb-bench-note">{E2E.note}</p>
    </>
  );
}

function RetrievalLedger({rows, metrics, note, label}: {
  rows: BenchRow[];
  metrics: Metric[];
  note: string;
  label: string;
}) {
  const [metric, setMetric] = useState(metrics[0].id);
  const [sort, setSort] = useState('score');
  const ordered = [...rows].sort((a, b) => sort === 'score' ? b.scores[metric] - a.scores[metric] : a.p50ms - b.p50ms);
  const metricLabel = metrics.find((item) => item.id === metric)?.label;

  return (
    <>
      <div className="sb-metric-controls" data-book-print={metric === metrics[0].id && sort === 'score' ? `${label.toLowerCase()}.webp` : undefined}>
        <label>Metric <select value={metric} onChange={(event) => setMetric(event.target.value)}>
          {metrics.map(({id, label, hint}) => <option key={id} value={id} title={hint}>{label}</option>)}
        </select></label>
        <label>Sort by <select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="score">Score</option><option value="time">Query time</option>
        </select></label>
      </div>
      <table className="sb-ledger sb-retrieval-ledger" aria-label={`${label} results`}>
        <thead><tr><th scope="col">System</th><th scope="col" aria-label={metricLabel}>Score</th><th scope="col">Median time</th></tr></thead>
        <tbody>
          {ordered.map(({label, scores, p50, teresis}) => (
            <tr key={label} data-teresis={teresis}>
              <th scope="row">{label}<Bar fraction={scores[metric]} /></th>
              <td>{scores[metric].toFixed(3)}</td><td>{p50}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sb-bench-note">{note}</p>
    </>
  );
}

export function EvaluationPage() {
  const [active, setActive] = useState(0);
  const ledgers = [
    <EndToEndLedger />,
    <RetrievalLedger rows={LONGMEMEVAL_ROWS} metrics={LONGMEMEVAL_METRICS} note={LONGMEMEVAL_NOTE} label="LongMemEval" />,
    <RetrievalLedger rows={LOCOMO_ROWS} metrics={LOCOMO_METRICS} note={LOCOMO_NOTE} label="LoCoMo" />,
  ];

  return (
    <div className="sb-page sb-evaluation">
      <Tabs items={BENCH_TABS} active={active} select={setActive} prefix="bench" label="Benchmark results" />
      {BENCH_TABS.map(({id}, index) => (
        <div role="tabpanel" id={`sb-bench-panel-${index}`} aria-labelledby={`sb-bench-tab-${index}`} hidden={active !== index} tabIndex={0} key={id}>
          {ledgers[index]}
        </div>
      ))}
      <a className="sb-results" href={RESULTS_URL} target="_blank" rel="noopener noreferrer">Raw benchmark results</a>
    </div>
  );
}

// The selectors and commands are rendered on separate book sheets.
let installIndex = 0;
const installListeners = new Set<() => void>();

function subscribeInstall(listener: () => void) {
  installListeners.add(listener);
  return () => { installListeners.delete(listener); };
}

function getInstallIndex() {
  return installIndex;
}

function selectInstall(index: number) {
  if (index === installIndex) return;
  installIndex = index;
  installListeners.forEach((listener) => listener());
}

function CommandPlate({commands, label}: {commands: string[]; label: string}) {
  return (
    <div className="sb-command-plate">
      {commands.map((command, index) => (
        <div className="sb-command-row" key={command}>
          <pre><code>{cli(command)}</code></pre>
          <CopyButton text={command} label={commands.length === 1 ? label : `${label} ${index + 1}`} />
        </div>
      ))}
    </div>
  );
}

export function InstallPage() {
  const active = useSyncExternalStore(subscribeInstall, getInstallIndex);
  return (
    <div className="sb-page sb-install">
      <h2 className="sb-title sb-install-title">Install</h2>
      <p className="manuscript-note">Choose the agent or interface that will read your memory file.</p>
      <Tabs items={INSTALL.tabs} active={active} select={selectInstall} prefix="install" label="Install methods" vertical />
    </div>
  );
}

export function InstallCommandPage() {
  const active = useSyncExternalStore(subscribeInstall, getInstallIndex);
  return (
    <div className="sb-page sb-install-commands">
      {INSTALL.tabs.map((tab, index) => {
        // Keep Python and multiline shell snippets intact when copying.
        const commands = tab.id === 'http' || tab.id === 'python' ? [tab.code] : tab.code.split('\n');
        return (
          <div role="tabpanel" id={`sb-install-panel-${index}`} aria-labelledby={`sb-install-tab-${index}`} hidden={active !== index} tabIndex={0} key={tab.id}>
            <h2 className="sb-title sb-install-title">{tab.label}</h2>
            <p>{tab.text}</p>
            <CommandPlate commands={commands} label={`Copy ${tab.label} command`} />
          </div>
        );
      })}
    </div>
  );
}

export function QuestionsPage() {
  return (
    <div className="sb-page sb-questions">
      <h2 className="sb-title">Questions</h2>
      <div className="sb-faq">
        {FAQ.map(({q, a}, index) => (
          <details name="sb-faq" open={index === 0} key={q}>
            <summary>{q}</summary>
            <p>{a}</p>
          </details>
        ))}
      </div>
    </div>
  );
}

export function ClosingPage() {
  return (
    <div className="sb-page sb-close">
      <img className="sb-mark" src={MARK} alt="" />
      <h2 className="sb-title">Keep the file on your machine</h2>
      <CommandPlate commands={[INSTALL.brew]} label="Copy the Homebrew install command" />
      <div className="sb-news">
        <h3>Release notes</h3>
        <form className="form" data-endpoint={`${import.meta.env.BASE_URL}api/waitlist`} data-sent="You are subscribed to release notes." noValidate>
          <div className="field field--full">
            <label htmlFor="rn-email">Email</label>
            <input id="rn-email" name="email" type="email" required autoComplete="email" inputMode="email" aria-describedby="rn-email-err" />
            <p className="field__error" id="rn-email-err" hidden>Write an email address with an @.</p>
          </div>
          <div className="btn-row"><button className="book-button book-button--gold" type="submit" aria-label="Subscribe to release notes">Subscribe</button></div>
          <p className="form__status" role="status" data-form-status />
          <p className="t-small muted">Release notes only.</p>
        </form>
      </div>
    </div>
  );
}

const SOURCE_LINKS = [
  ['GitHub', GITHUB],
  ['Docs', `${GITHUB}#readme`],
  ['Apache 2.0', `${GITHUB}/blob/main/LICENSE`],
  ['Releases', `${GITHUB}/releases`],
  ['Benchmark results', RESULTS_URL],
];

export function ColophonPage() {
  return (
    <footer className="sb-page sb-colophon">
      <h2 className="sb-title">Colophon</h2>
      <p className="sb-colophon-name">Source &amp; further reading</p>
      <nav className="sb-source-links" aria-label="Teresis source and documentation">
        {SOURCE_LINKS.map(([label, href]) => (
          <a key={href} href={href} target="_blank" rel="noopener noreferrer">{label}</a>
        ))}
      </nav>
      <nav className="sb-page-links" aria-label="Book sections">
        {NAV_ITEMS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
      </nav>
      <a className="book-button book-button--gold sb-colophon-install" href="#install">Install Teresis</a>
      <p className="sb-legal">Apache 2.0 · τήρησις, faithful keeping · Product names and logos are trademarks of their owners.</p>
    </footer>
  );
}

export function BackCoverPage() {
  return (
    <div className="sb-page sb-back">
      <div className="sb-backplate"><img className="sb-mark" src={MARK} alt="" />
        <h2>Where to find your ledger</h2>
        <p>Teresis keeps its database here by default.</p>
        <code>~/.local/share/teresis/memory.db</code>
      </div>
    </div>
  );
}
