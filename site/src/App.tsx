import type {CSSProperties} from 'react';
import {FAQ, LIVE_BY_KIND, LIVE_METHOD, LIVE_TOTAL, LOCOMO, LONGMEMEVAL, SNIPPETS} from './content';
import {Mark, Lotus} from './components/Lotus';

const GITHUB = 'https://github.com/raitoxlol/teresis';
const LICENCE = 'https://github.com/raitoxlol/teresis/blob/main/LICENSE';
const RESULTS = 'https://github.com/raitoxlol/teresis/tree/main/bench/results';

const DOTS = <span className="ui-dots" aria-hidden="true"><i></i><i></i><i></i></span>;

const MEM_ROWS: [string, string, string, string][] = [
  ['user', 'Editor is Neovim · user.editor', 'current', ''],
  ['user', 'Editor is VS Code · user.editor', 'superseded', ''],
  ['user', 'User prefers terse answers · preference', 'current', ''],
  ['project/atlas', 'Atlas uses PostgreSQL 16 · atlas.database', 'current', ''],
  ['project/atlas', 'Deploys go out on Tuesdays', 'current', ''],
  ['project/atlas/agent-x', 'Migration 0042 is applied', 'current', ''],
  ['project/helios', 'Helios runs on MySQL 8 · helios.database', 'current', ''],
  ['project/helios', 'Helios deploys from the main branch', 'current', ''],
  ['global', 'Commit messages use the imperative mood', 'current', ''],
  ['user', 'Timezone is Europe/Berlin · user.timezone', 'current', ''],
];

const CLI_OUT: {cmd?: boolean; t: string; mark?: string}[] = [
  {cmd: true, t: '$ teresis remember "Editor is VS Code" -s user --key user.editor'},
  {t: 'created 36a9d8ab412246e3'},
  {cmd: true, t: '$ teresis remember "Editor is Neovim" -s user --key user.editor'},
  {t: 'superseded 0c4fed00cb4b4db2 (replaced 36a9d8ab412246e3)', mark: 'Replaced the earlier value for the same key; it stays in history.'},
  {cmd: true, t: '$ teresis remember "Editor is Neovim" -s user --key user.editor'},
  {t: 'duplicate 0c4fed00cb4b4db2'},
  {cmd: true, t: '$ teresis recall "which editor" -s user'},
  {t: '0c4fed00cb4b4db2  [fact · user · key=user.editor · 1.014]'},
  {t: '    Editor is Neovim'},
];

// Real output of the same store, captured from the CLI: more writes, then history and recall.
const CLI_HISTORY: {cmd?: boolean; t: string; mark?: string}[] = [
  {cmd: true, t: '$ teresis remember "Atlas uses PostgreSQL 16" -s project/atlas --key atlas.database'},
  {t: 'created e49ec32acb4f4da0'},
  {cmd: true, t: '$ teresis history -s user --key user.editor'},
  {t: '36a9d8ab412246e3  [fact · user · key=user.editor · SUPERSEDED]', mark: 'The old value stays in history. Recall returns the current one.'},
  {t: '    Editor is VS Code'},
  {t: '0c4fed00cb4b4db2  [fact · user · key=user.editor]'},
  {t: '    Editor is Neovim'},
  {cmd: true, t: '$ teresis recall "postgress" -s project/atlas --explain'},
  {t: 'e49ec32acb4f4da0  [fact · project/atlas · key=atlas.database · 1.000]'},
  {t: '    Atlas uses PostgreSQL 16'},
  {t: "    why: {'channels': {'trigram': 1.0}, 'relevance': 1.0, 'recency': 1.0}"},
  {cmd: true, t: '$ teresis remember "Deploys go out on Tuesdays" -s project/atlas'},
  {t: 'created a5da4b19a78b46a0'},
  {cmd: true, t: '$ teresis remember "Helios runs on MySQL 8" -s project/helios --key helios.database'},
  {t: 'created 38e9831b14bd4b33'},
  {cmd: true, t: '$ teresis recall "which editor" -s user'},
  {t: '0c4fed00cb4b4db2  [fact · user · key=user.editor · 1.014]'},
  {t: '    Editor is Neovim'},
];

// The CLI prints its metadata in square brackets. The opening bracket is its own text node so the
// kit's leftover-placeholder guard, which reads one text node at a time, does not outline real output.
const cli = (t: string) => {
  const i = t.indexOf('[');
  return i < 0 ? t : <>{t.slice(0, i)}<span>[</span>{t.slice(i + 1)}</>;
};

const TABS: {id: number; label: string; text: string}[] = [
  {id: 1, label: 'Add to Hermes', text: 'Copies the provider plugin into the Hermes home, then sets Teresis as the memory provider. Start a new session.'},
  {id: 2, label: 'Add to MCP', text: 'Runs the MCP server on stdio. Writes go to the first scope; recall searches every scope given and their parents.'},
  {id: 3, label: 'Call over HTTP', text: 'The same tool names and arguments as MCP, over a local HTTP API. It binds to 127.0.0.1 by default.'},
  {id: 4, label: 'Import in Python', text: 'MemoryStore opens the same file the other three interfaces use. A keyed write supersedes the older value.'},
];

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>

      <header className="nav nav--centre">
        <div className="wrap nav__bar">
          <a className="nav__logo" href="#top" aria-label="Teresis home">
            <Mark className="nav__mark" />
            <span>Teresis</span>
          </a>
          <nav className="nav__links" aria-label="Sections">
            <div className="nav__item"><a className="nav__link" href="#memory">Memory</a></div>
            <div className="nav__item"><a className="nav__link" href="#how">Method</a></div>
            <div className="nav__item"><a className="nav__link" href="#benchmarks">Benchmarks</a></div>
            <div className="nav__item"><a className="nav__link" href="#questions">Questions</a></div>
            <div className="nav__item"><a className="nav__link" href={GITHUB} target="_blank" rel="noopener noreferrer">GitHub</a></div>
          </nav>
          <div className="nav__actions">
            <a className="btn btn--primary" href="#install">Install Teresis</a>
          </div>
          <button className="nav__toggle" type="button" aria-expanded="false" aria-label="Menu"><svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M2 5h14M2 13h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg></button>
        </div>
      </header>

      <main id="main">
        {/* 1 — hero: collage */}
        <section className="hero hero--collage" data-enter aria-labelledby="hero-h" id="top">
          <div className="wrap">
            <div className="hero-text grid hero__grid">
              <div className="hero__text span-5">
                <h1 id="hero-h">Local long{'\u2011'}term memory for AI agents</h1>
                <p className="hero__lead">Teresis keeps facts, preferences and decisions in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.</p>
                <div className="btn-row">
                  <a className="btn btn--primary" href="#install">Install Teresis</a>
                  <a className="btn btn--secondary" href="#benchmarks">See the benchmarks</a>
                </div>
                <p className="hero__proof">Live Hermes test: <b>{LIVE_TOTAL[0].display}</b> with Teresis, <b>{LIVE_TOTAL[1].display}</b> with stock memory.</p>
              </div>
              <div className="hero__art span-6 start-7" role="img" aria-label="Teresis terminal on the lattice ground: three writes and a recall, with the user.editor fact card beside it">
                <div className="ly-piece ly-piece--main t-term" aria-hidden="true">
                  <div className="t-term__bar">{DOTS}<span className="t-term__title">teresis — zsh</span></div>
                  <pre className="t-term__body">{CLI_OUT.map((l, i) => (
                    <span key={i} className={l.cmd ? 't-term__ln is-cmd' : 't-term__ln'}>{cli(l.t)}{'\n'}</span>
                  ))}</pre>
                </div>
                <div className="ly-piece ly-piece--note t-card" aria-hidden="true" data-ly-steps="700">
                  <h5>user.editor</h5>
                  <div className="t-card__row" data-step><span>Editor is VS Code</span><span>superseded</span></div>
                  <div className="t-card__row" data-step><span>Editor is Neovim</span><span>current</span></div>
                  <div className="t-card__row" data-step><span>Repeated write</span><span>duplicate, no new row</span></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* 2 — #memory: app-frame */}
        <section className="section" id="memory" aria-labelledby="memory-h">
          <div className="wrap">
            <div className="grid">
              <div className="section-head span-5">
                <h2 id="memory-h">Facts with their scope and history</h2>
              </div>
              <p className="span-6 start-7 section-copy">A keyed fact replaces the old value and keeps the previous one. A repeated fact reinforces the same row. Recall reads a scope and its parents. <a className="link" href={GITHUB} target="_blank" rel="noopener noreferrer">Read the source on GitHub</a></p>
            </div>
            <div className="ui app fill" role="img" aria-label="Teresis memory list beside a terminal session showing history and recall" data-ui-pause-host>
                <div className="app__pane app__pane--list">
                <div className="ui ui-panel ui-win" data-ui="window" data-open="All" data-work="Writing" data-done="Written">
                  <div className="ui-win__bar">
                    {DOTS}
                    <span className="ui-win__crumb">memory.db <i>/</i> <b>All facts</b></span>
                    <span className="ui-spacer"></span>
                    <span className="ui-win__search" aria-hidden="true"><svg className="ui-icon" viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></svg><span className="ui-win__ph">Search</span></span>
                  </div>
                  <div className="ui-win__body">
                    <nav className="ui-win__side" aria-hidden="true">
                      <span className="ui-win__nav is-on">All<em>10</em></span>
                      <span className="ui-win__nav">user<em>4</em></span>
                      <span className="ui-win__nav">project<em>5</em></span>
                      <span className="ui-win__nav">global<em>1</em></span>
                    </nav>
                    <div className="ui-win__main">
                      <div className="ui-win__cols" aria-hidden="true"><span>Scope</span><span>Fact</span><span>State</span><span>Key</span></div>
                      <ul className="ui-win__rows">
                        {MEM_ROWS.map(([scope, fact, st, key], i) => (
                          <li key={i} className="ui-win__row" data-row>
                            <span className="ui-avatar" data-tone={(i % 5) + 1}>{scope === 'global' ? 'gl' : scope === 'user' ? 'us' : 'pr'}</span>
                            <span className="ui-win__who">{scope}</span>
                            <span className="ui-win__sub">{fact}</span>
                            <span className={`ui-win__st${st === 'superseded' ? ' is-old' : ''}`} data-st>{st}</span>
                            <span className="ui-win__age">{key || '—'}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
                </div>
                <div className="app__pane app__pane--open" data-ui-loop>
                  <div className="ui ui-panel ui-code" data-ui="code">
                    <div className="ui-code__tabs">
                      <span className="ui-code__tab is-on"><i className="ui-code__lang">sh</i>teresis</span>
                      <span className="ui-spacer"></span>
                      <span className="ui-chip ui-chip--plain ui-code__chip" data-code-chip>history</span>
                    </div>
                    <pre className="ui-code__pre"><code>{CLI_HISTORY.map((l, i) => (
                      <span key={i} className={`ui-code__ln${l.mark ? ' is-mark' : ''}`} {...(l.mark ? {'data-note': l.mark} : {})} data-n={i + 1}>{cli(l.t)}{'\n'}</span>
                    ))}</code></pre>
                    <div className="ui-code__hint" data-code-hint><span className="ui-dot"></span><span data-code-text>The old value stays in history. Recall returns the current one.</span></div>
                  </div>
                </div>
              </div>
            </div>
        </section>

        {/* 3 — #how: bento */}
        <section className="section" id="how" aria-labelledby="how-h">
          <div className="wrap">
            <div className="section-head"><h2 id="how-h">How Teresis keeps facts straight</h2></div>
            <div className="grid bento">
              <article className="card card--row span-8">
                <h3>Shares one file between agents</h3>
                <p>Hermes, Claude Code, Codex and Cursor read and write ~/.local/share/teresis/memory.db. SQLite WAL lets several processes write at once.</p>
                <div className="panel dg-panel" style={{'--p-h': '240px'} as CSSProperties}>
                  <div className="dg" data-diagram={JSON.stringify({
                    layout: 'hub',
                    alt: 'Hermes Agent, Claude Code, Codex and Cursor all connect to the memory.db file.',
                    center: {label: 'memory.db', icon: 'ui:database'},
                    spokes: [{label: 'Hermes Agent'}, {label: 'Claude Code'}, {label: 'Codex'}, {label: 'Cursor'}],
                  })}></div>
                </div>
              </article>
              <article className="card card--row span-4">
                <h3>Replaces a changed fact</h3>
                <p>The newest value wins. The old one stays in history.</p>
                <div className="panel viz" style={{'--p-h': '130px'} as CSSProperties}>
                  <div className="viz__row is-off"><span><s>Editor is VS Code</s></span><b>superseded</b></div>
                  <div className="viz__row"><span>Editor is Neovim</span><b>current · key user.editor</b></div>
                </div>
              </article>
              <article className="card card--row span-4">
                <h3>Reads parents, never siblings</h3>
                <p>Scopes are paths. Recall reads a scope and its parents.</p>
                <div className="panel viz" style={{'--p-h': '130px'} as CSSProperties}>
                  <div className="viz__row"><span>global</span><b>read</b></div>
                  <div className="viz__row"><span>project/atlas</span><b>read</b></div>
                  <div className="viz__row is-hi"><span>project/atlas/agent-x</span><b>recalling</b></div>
                  <div className="viz__row is-mute"><span>project/helios</span><b>never read</b></div>
                </div>
              </article>
              <article className="card card--row span-4">
                <h3>Finds stems and typos</h3>
                <p>BM25 on a Porter-stemmed index, trigrams for typos, optional vectors for paraphrases.</p>
                <div className="panel viz" style={{'--p-h': '130px'} as CSSProperties}>
                  <div className="viz__row"><span>recall("postgress")</span><b>trigram · 1.000</b></div>
                  <div className="viz__row is-hi"><span>Atlas uses PostgreSQL 16</span><b>hit</b></div>
                </div>
              </article>
              <article className="card card--row span-4">
                <h3>Writes without a model</h3>
                <p>Zero LLM calls on write, so each write is exact and repeatable.</p>
                <div className="panel viz" style={{'--p-h': '130px'} as CSSProperties}>
                  <div className="viz__row"><span>recall p50 · no model (LoCoMo)</span><b>17 ms</b></div>
                  <div className="viz__row"><span>network calls by default</span><b>0</b></div>
                  <div className="viz__row"><span>processes writing at once (test suite)</span><b>4</b></div>
                </div>
              </article>
            </div>
          </div>
        </section>

        {/* 4 — #keeps: statement + liquid-type */}
        <section className="section section--keeps" id="keeps" aria-labelledby="keeps-h" data-statement>
          <div className="wrap">
            <div className="keeps__text" data-m-loop>
              <h2 id="keeps-h" className="keeps-h mo-lt__type" data-moment="liquid-type">Your agents forget. <span className="keeps">Teresis keeps.</span></h2>
              <p className="keeps-sub">τήρησις is Greek for faithful keeping. Secrets are redacted on write, and nothing leaves the machine unless you add an embedder.</p>
            </div>
            <Lotus className="keeps-mark" grid />
          </div>
        </section>

        {/* 5 — #benchmarks: inverse band + counter-rolls */}
        <section className="section ground-inverse" id="benchmarks" aria-labelledby="bench-h">
          <div className="wrap">
            <div className="grid">
              <div className="section-head span-7"><h2 id="bench-h">100 of 100 on a live Hermes test</h2><p className="lead">{LIVE_METHOD}</p></div>
              <div className="grid stats span-12" data-moment="counter-rolls">
                {LIVE_TOTAL.map((r) => (
                  <div className="stat span-3" key={r.label}><p className="t-stat">{r.display}</p><p className="stat-label">{r.label}</p></div>
                ))}
              </div>
              <div className="span-12">
                <table className="kinds">
                  <caption>By kind of question</caption>
                  <thead><tr><th scope="col">Kind</th><th scope="col">Asked</th><th scope="col">Teresis</th><th scope="col">Stock Hermes</th></tr></thead>
                  <tbody>
                    {LIVE_BY_KIND.map((r) => (
                      <tr key={r.kind}><th scope="row">{r.kind}</th><td>{r.asked}</td><td className="t">{r.teresis}</td><td>{r.stock}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>

        {/* 6 — #public: bar charts */}
        <section className="section section--public" id="public" aria-labelledby="public-h">
          <div className="wrap">
            <div className="section-head"><h2 id="public-h">LongMemEval and LoCoMo results</h2></div>
            <div className="grid bench">
              <figure className="span-6">
                <figcaption>LongMemEval · ranking quality (NDCG@10) · median query time</figcaption>
                <div className="panel chart-panel"><ul className="bars">
                  {LONGMEMEVAL.map((r) => (
                    <li key={r.label} className={r.highlight ? 'hi' : ''}>
                      <span className="bl">{r.label}</span>
                      <span className="track"><i className="fill" style={{width: `${r.value * 100}%`}}></i></span>
                      <span className="bv">{r.display}</span>
                      <span className="bn">{r.note}</span>
                    </li>
                  ))}
                </ul></div>
              </figure>
              <figure className="span-6">
                <figcaption>LoCoMo · evidence in the top 5 (recall@5) · median query time</figcaption>
                <div className="panel chart-panel"><ul className="bars">
                  {LOCOMO.map((r) => (
                    <li key={r.label} className={r.highlight ? 'hi' : ''}>
                      <span className="bl">{r.label}</span>
                      <span className="track"><i className="fill" style={{width: `${r.value * 100}%`}}></i></span>
                      <span className="bv">{r.display}</span>
                      <span className="bn">{r.note}</span>
                    </li>
                  ))}
                </ul></div>
              </figure>
            </div>
            <p className="fine">Retrieval only, no LLM calls. Vector and hybrid systems share local Ollama all-minilm except total-agent-memory (built-in FastEmbed MiniLM, cross-encoder off). The optional Teresis reranker row adds a local MiniLM cross-encoder over the top 15 hits; all other rows are first-stage retrieval. mem0 OSS ran v3 hybrid (BM25 + spaCy + vectors, infer=False). Higher is better.</p>
          </div>
        </section>

        {/* 7 — #install: tabs-tour */}
        <section className="section" id="install" aria-labelledby="install-h">
          <div className="wrap">
            <div className="grid">
              <div className="span-5">
                <div className="section-head"><h2 id="install-h">Four interfaces to one Teresis file</h2><p className="lead">A Hermes memory provider, an MCP server, a local HTTP API and a Python API share one SQLite file.</p></div>
                <div className="tabs" role="tablist" aria-label="Interfaces">
                  {TABS.map((t, i) => (
                    <button key={t.id} className="tab" role="tab" id={`tabbtn-${t.id}`} aria-controls={`tab-${t.id} screen-${t.id}`} aria-selected={i === 0 ? 'true' : 'false'}>{t.label}</button>
                  ))}
                </div>
                {TABS.map((t, i) => (
                  <div key={t.id} className="tabpanel" role="tabpanel" id={`tab-${t.id}`} aria-labelledby={`tabbtn-${t.id}`} hidden={i !== 0}>
                    <p>{t.text}</p>
                  </div>
                ))}
              </div>
              <div className="frame frame--split span-6 start-7">
                <div className="stage stage--fade-br">
                  {(['Hermes', 'MCP', 'HTTP', 'Python'] as const).map((k, i) => (
                    <div key={k} className="screen t-code" id={`screen-${i + 1}`} hidden={i !== 0}>
                      <div className="ui ui-panel ui-code" data-ui="code">
                        <div className="ui-code__tabs">
                          <span className="ui-code__tab is-on"><i className="ui-code__lang">sh</i>{k}</span>
                          <span className="ui-spacer"></span>
                        </div>
                        <pre className="ui-code__pre"><code>{SNIPPETS[k].trim().split('\n').map((ln, j) => (
                          <span key={j} className="ui-code__ln" data-n={j + 1}>{ln}{'\n'}</span>
                        ))}</code></pre>
                        <button className="copy" type="button" aria-label="Copy the commands" data-copy={k}>Copy</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <p className="note">Apache 2.0. No required dependencies.</p>
          </div>
        </section>

        {/* 8 — #questions: faq */}
        <section className="section" id="questions" aria-labelledby="faq-h">
          <div className="wrap">
            <div className="grid">
              <div className="span-5">
                <div className="section-head"><h2 id="faq-h">Questions</h2></div>
                <Lotus className="faq-mark" grid />
              </div>
              <div className="faq span-6 start-7">
                {FAQ.map((f) => (
                  <div className="faq__item" key={f.q}><h3>{f.q}</h3><p>{f.a}</p></div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* 9 — footer close-word */}
        <footer className="footer closing" id="contact" aria-labelledby="close-h">
          <div className="wrap">
            <div className="closing__cta close--word">
              <div className="section-head--split">
                <div>
                  <h2 id="close-h">The file stays on your machine</h2>
                  <p className="t-lead">Apache 2.0, installed with pip from GitHub.</p>
                </div>
                <a className="btn btn--primary" href="#install">Install Teresis</a>
              </div>
              <p className="close__word" aria-hidden="true"><Mark className="close__mark" />Teresis</p>
            </div>
            <div className="closing__links">
              <div className="grid">
                <div className="span-4 stack-4">
                  <a className="nav__logo" href="#top"><Mark className="nav__mark" /><span>Teresis</span></a>
                  <p className="footer__lede">Local long-term memory for AI agents.</p>
                  <form className="form" data-endpoint={`${import.meta.env.BASE_URL}api/waitlist`} data-sent="You are subscribed to release notes." noValidate>
                    <div className="field field--full">
                      <label htmlFor="rn-email">Email</label>
                      <input id="rn-email" name="email" type="email" required autoComplete="email" inputMode="email" aria-describedby="rn-email-err" />
                      <p className="field__error" id="rn-email-err" hidden>Write an email address with an @.</p>
                    </div>
                    <div className="btn-row"><button className="btn btn--secondary" type="submit">Subscribe to release notes</button></div>
                    <p className="form__status" role="status" data-form-status></p>
                    <p className="t-small muted">Release notes only.</p>
                  </form>
                </div>
                <div className="span-4 footer__col">
                  <h3>Product</h3>
                  <ul>
                    <li><a href="#memory">Memory</a></li>
                    <li><a href="#how">Method</a></li>
                    <li><a href="#benchmarks">Benchmarks</a></li>
                    <li><a href="#questions">Questions</a></li>
                  </ul>
                </div>
                <div className="span-4 footer__col">
                  <h3>Source</h3>
                  <ul>
                    <li><a href={GITHUB} target="_blank" rel="noopener noreferrer">GitHub</a></li>
                    <li><a href={LICENCE} target="_blank" rel="noopener noreferrer">Licence</a></li>
                    <li><a href={RESULTS} target="_blank" rel="noopener noreferrer">Benchmark results</a></li>
                  </ul>
                </div>
              </div>
              <div className="footer__legal"><span>Teresis · 2026 · Apache 2.0 · τήρησις, faithful keeping · Product names and logos are trademarks of their owners</span></div>
            </div>
          </div>
        </footer>
    </>
  );
}
