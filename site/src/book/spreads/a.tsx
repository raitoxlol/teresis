import {useState, useSyncExternalStore, type ReactNode} from 'react';
import {cli, CopyButton, useTabKeys} from '../../App';
import './a.css';
import {SNIPPETS, STEPS} from '../../content';
import {DEMO_STEPS, demoRows, GITHUB, HERMES_HOOKS, INSTALL, SCOPES, scopeChain} from '../../data';

const BASE = import.meta.env.BASE_URL;
const MARK = `${BASE}logos/teresis-mark.svg`;

export function Bookplate({fact, onTell, onForget}: {fact?: string; onTell?: (fact: string) => void; onForget?: () => void}) {
  const [draft, setDraft] = useState('');
  const [focused, setFocused] = useState(false);
  if (fact) {
    return (
      <div className="sa-bookplate">
        <h2>Kept for you</h2>
        <p className="sa-kept" aria-live="polite">{fact}</p>
        <p className="sa-plate-note">Saved in this browser.</p>
        <button className="sa-forget" type="button" onClick={onForget}>Forget it</button>
      </div>
    );
  }
  return (
    <form className="sa-bookplate" onSubmit={(event) => {
      event.preventDefault();
      const next = draft.trim();
      if (!next) return;
      onTell?.(next);
      setDraft('');
      (document.activeElement as HTMLElement | null)?.blur();
    }}>
      <h2>Kept for you</h2>
      <label className="sa-plate-note" htmlFor="bookplate-fact">Try the bookplate. Write a preference to keep in this browser.</label>
      <span className="sa-write" data-empty={!draft || undefined}>
        <input id="bookplate-fact" value={draft} maxLength={48} autoComplete="off" spellCheck={false}
          placeholder="My editor is Neovim"
          onChange={(event) => setDraft(event.target.value)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
        <span className="sa-ink" aria-hidden="true">{draft || 'My editor is Neovim'}{focused && <span className="sa-caret" />}</span>
      </span>
      <button className="sa-keep" type="submit">Keep it</button>
    </form>
  );
}

export function TitlePage() {
  return (
    <div className="sa-title">
      <img className="sa-mark" src={MARK} alt="" />
      <h2>Teresis</h2>
      <p className="sa-etymology"><span lang="el">τήρησις</span> · faithful keeping</p>
      <p className="sa-statement">Memory for your agents</p>
      <p className="sa-introduction">Tell one agent which editor you use. Another can recall it from the same SQLite file in a fresh session.</p>
      <a href={GITHUB} target="_blank" rel="noopener noreferrer">Read Teresis on GitHub</a>
    </div>
  );
}

const recallIndex = DEMO_STEPS.findIndex((step) => step.id === 'recall');
const demoListeners = new Set<() => void>();
let demo = {selected: recallIndex, rowsAt: recallIndex, typed: DEMO_STEPS[recallIndex].cmd, pending: false};
let typingFrame = 0;

function subscribeDemo(listener: () => void) {
  demoListeners.add(listener);
  return () => { demoListeners.delete(listener); };
}

function readDemo() {
  return demo;
}

function updateDemo(next: typeof demo) {
  demo = next;
  demoListeners.forEach((listener) => listener());
}

function runStep(index: number) {
  cancelAnimationFrame(typingFrame);
  const command = DEMO_STEPS[index].cmd;
  const complete = () => updateDemo({selected: index, rowsAt: index, typed: command, pending: false});

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    complete();
    return;
  }

  updateDemo({...demo, selected: index, typed: '', pending: true});
  const start = performance.now();
  const type = (now: number) => {
    const progress = (now - start) / 420;
    if (progress >= 1) {
      complete();
      return;
    }
    updateDemo({...demo, typed: command.slice(0, Math.ceil(command.length * progress))});
    typingFrame = requestAnimationFrame(type);
  };
  typingFrame = requestAnimationFrame(type);
}

export function TryTablePage() {
  const rowsAt = useSyncExternalStore(subscribeDemo, () => demo.rowsAt);
  const rows = demoRows(rowsAt);

  return (
    <div className="sa-try">
      <h2>Change a fact</h2>
      <p className="sa-try-lead">{DEMO_STEPS[rowsAt].point}</p>
      <table className="sa-memory">
        <caption>memory.db</caption>
        <thead><tr><th scope="col">scope</th><th scope="col">key</th><th scope="col">fact</th><th scope="col">state</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-touched={DEMO_STEPS[rowsAt].touched.includes(row.id) || undefined}>
              <td>{row.scope}</td>
              <td>{row.key ?? '—'}</td>
              <td>{row.state === 'superseded' ? <s>{row.fact}</s> : cli(row.fact)}</td>
              <td>{row.state}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TryTerminalPage() {
  const {selected, typed, pending} = useSyncExternalStore(subscribeDemo, readDemo);
  const step = DEMO_STEPS[selected];
  const last = selected === DEMO_STEPS.length - 1;

  return (
    <div className="sa-guided">
      <ol className="sa-step-list" aria-label="Guided terminal steps">
        {DEMO_STEPS.map((item, index) => (
          <li key={item.id}>
            <button
              className="sa-step"
              type="button"
              aria-current={selected === index ? 'step' : undefined}
              onClick={() => runStep(index)}
            >{item.label}</button>
          </li>
        ))}
      </ol>
      <div className="sa-terminal">
        <code className="sa-command">{typed}</code>
        <div className="sa-transcript" aria-live="polite" aria-atomic="true">
          {!pending && (
            <div className="sa-output">
              {step.out.map((line) => (
                <div key={line} className={line.startsWith('    ') && !line.startsWith('    why:') ? 'sa-recall' : undefined}>{cli(line)}</div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="sa-terminal-actions">
        <button className="book-button book-button--gold" type="button" onClick={() => runStep(selected)}>Run</button>
        <button className="book-button" type="button" onClick={() => runStep(last ? 0 : selected + 1)}>{last ? 'Start over' : 'Next'}</button>
      </div>
    </div>
  );
}

const diagramScopes = SCOPES.filter((scope) => scope.split('/').length < 3);
const scopeLinks = [
  {from: 'user', className: 'sa-user-link'},
  {from: 'project', className: 'sa-project-link'},
  {from: 'project/atlas', className: 'sa-atlas-link'},
  {from: 'project/helios', className: 'sa-helios-link'},
] as const;

export function ScopePage() {
  const [selected, setSelected] = useState(diagramScopes.indexOf('project/atlas'));
  const read = scopeChain(diagramScopes[selected]);

  return (
    <div className="sa-scope-page">
      <h2>Who can recall it?</h2>
      <p className="sa-scope-intro">Choose a scope below. Follow the ink to see which memories an agent in that scope can read.</p>
      <div className="sa-scopes" role="radiogroup" aria-label="Choose where recall starts">
        {scopeLinks.map(({from, className}) => (
          <span className={`sa-edge ${className}`} key={from} data-read={read.includes(from) || undefined} aria-hidden="true"><i /></span>
        ))}
        {diagramScopes.map((scope, index) => (
          <button
            className={`sa-scope sa-scope-${scope.replaceAll('/', '-')}`}
            id={`sa-scope-${index}`}
            type="button"
            role="radio"
            key={scope}
            data-read={read.includes(scope) || undefined}
            aria-checked={selected === index}
            tabIndex={selected === index ? 0 : -1}
            onClick={() => setSelected(index)}
            onKeyDown={(event) => useTabKeys(event, index, diagramScopes.length, setSelected)}
          >{scope}</button>
        ))}
      </div>
      <span className="sa-visually-hidden" role="status">Recall reads {read.join(', ')}.</span>
    </div>
  );
}

export function MethodPage() {
  const [beforePath, databasePath, afterPath] = STEPS[0].body.split(/(~\/[^ ]+\.db)/);

  return (
    <div className="sa-method">
      {[STEPS[0], STEPS[1], STEPS[3], STEPS[4]].map((step) => (
        <section key={step.demo}>
          <h3>{step.title}</h3>
          <p>{step === STEPS[0] ? <>{beforePath}<code>{databasePath}</code>{afterPath}</> : step.body}</p>
        </section>
      ))}
    </div>
  );
}

export function HermesPage() {
  return (
    <div className="sa-hermes">
      <h2>Inside Hermes</h2>
      <div className="sa-hermes-brand">
        <img src={`${BASE}logos/hermes-agent.svg`} alt="" />
        <div><h3>Hermes Agent</h3><p>Native memory provider</p></div>
      </div>
      <dl className="sa-hooks">
        {HERMES_HOOKS.map(({hook, does}) => (
          <div key={hook}>
            <dt><code>{hook}</code></dt>
            <dd>{does}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const mcpClients = [
  {id: 'claude-code', name: 'Claude Code'},
  {id: 'codex', name: 'Codex'},
  {id: 'cursor', name: 'Cursor'},
];

function InterfaceEntry({name, command, children}: {name: string; command: string; children: ReactNode}) {
  return (
    <section className="sa-interface">
      <div className="sa-interface-heading">
        <h2>{name}</h2>
        <CopyButton text={command} label={`Copy ${name} commands`} />
      </div>
      {children}
      <details className="sa-commands" name="sa-client-commands">
        <summary aria-label={`${name} commands`}>Commands</summary>
        <pre className="sa-snippet"><code>{cli(command)}</code></pre>
      </details>
    </section>
  );
}

export function ClientsPage() {
  const setup = INSTALL.tabs.find(({id}) => id === 'all')!;
  const http = INSTALL.tabs.find(({id}) => id === 'http')!;
  const python = INSTALL.tabs.find(({id}) => id === 'python')!;

  return (
    <div className="sa-clients">
      <InterfaceEntry name="MCP" command={setup.code}>
        <ul className="sa-client-list">
          {mcpClients.map(({id, name}) => (
            <li key={id}><img src={`${BASE}assets/icons/${id}.svg`} alt="" />{name}</li>
          ))}
        </ul>
      </InterfaceEntry>
      <InterfaceEntry name="HTTP" command={SNIPPETS.HTTP}><p>{http.text}</p></InterfaceEntry>
      <InterfaceEntry name="Python" command={SNIPPETS.Python}><p>{python.text}</p></InterfaceEntry>
    </div>
  );
}
