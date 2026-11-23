import {useEffect, useRef, useState} from 'react';
import {Bars} from './components/Bars';
import {GridLayer} from './components/GridLayer';
import {Lotus, Mark} from './components/Lotus';
import {Waitlist} from './components/Waitlist';
import {FAQ, HERO, LIVE_BY_KIND, LIVE_METHOD, LIVE_TOTAL, LOCOMO, LONGMEMEVAL, SNIPPETS, STEPS, type Step} from './content';

type Tab = keyof typeof SNIPPETS;
const TABS = Object.keys(SNIPPETS) as Tab[];

function Install({compact = false}: {compact?: boolean}) {
  const [tab, setTab] = useState<Tab>('Hermes');
  const [copied, setCopied] = useState(false);
  const code = compact ? SNIPPETS[tab].split('\n')[0] : SNIPPETS[tab];
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(SNIPPETS[tab]);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked: the code stays selectable */
    }
  };
  return (
    <div className={`install${compact ? ' compact' : ''}`}>
      <div className="tabs" role="tablist" aria-label="Install preview">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={t === tab} className={t === tab ? 'on' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="code">
        <pre>
          <code>
            {code.split('\n').map((line, i) => (
              <span className="ln" key={i}>
                {line}
              </span>
            ))}
          </code>
        </pre>
        {!compact && (
          <button className="copy" onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>
      {!compact && <p className="note">Apache 2.0 · no required dependencies.</p>}
    </div>
  );
}

function Demo({kind}: {kind: Step['demo']}) {
  switch (kind) {
    case 'remember':
      return (
        <div className="demo">
          <pre>
            <code>
              <span className="k">m</span>.remember(<span className="s">"Editor is Neovim"</span>, scope=<span className="s">"user"</span>,
              {'\n           '}key=<span className="s">"user.editor"</span>)
            </code>
          </pre>
          <p className="out">created · ~/.local/share/teresis/memory.db</p>
        </div>
      );
    case 'supersede':
      return (
        <ol className="demo timeline">
          <li className="old">
            <span>Editor is VS Code</span>
            <em>superseded</em>
          </li>
          <li className="cur">
            <span>Editor is Neovim</span>
            <em>current · key user.editor</em>
          </li>
          <li className="dup">
            <span>Editor is Neovim</span>
            <em>repeated · reinforced, no new row</em>
          </li>
        </ol>
      );
    case 'scopes':
      return (
        <ul className="demo scopes">
          <li className="yes">global</li>
          <li className="yes i1">project/atlas</li>
          <li className="from i2">project/atlas/agent-x · recalling</li>
          <li className="no i1">project/helios · sibling, never read</li>
        </ul>
      );
    case 'channels':
      return (
        <div className="demo">
          <p className="q">
            recall(<span className="s">"postgress"</span>)
          </p>
          <ul className="hits">
            <li>
              <b>trigram</b> Atlas migrated its database to PostgreSQL 16
            </li>
            <li>
              <b>BM25</b> stemmed keyword match, ranked by field weight
            </li>
            <li>
              <b>vectors</b> optional, for paraphrased questions
            </li>
          </ul>
        </div>
      );
    case 'local':
      return (
        <ul className="demo rows">
          <li>
            <span>recall p50 · no model (LoCoMo)</span>
            <b>{LOCOMO.find((row) => row.label === 'Teresis, no model')?.note}</b>
          </li>
          <li>
            <span>network calls by default</span>
            <b>0</b>
          </li>
          <li>
            <span>processes writing at once (test suite)</span>
            <b>4</b>
          </li>
        </ul>
      );
  }
}

function Story() {
  const [step, setStep] = useState(1);
  const [drawn, setDrawn] = useState(false);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const plateRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setStep(Number((e.target as HTMLElement).dataset.step));
        }
      },
      {rootMargin: '-45% 0px -45% 0px'},
    );
    refs.current.forEach((el) => el && io.observe(el));
    const enter = new IntersectionObserver(([e]) => e.isIntersecting && setDrawn(true), {threshold: 0.3});
    if (plateRef.current) enter.observe(plateRef.current);
    return () => {
      io.disconnect();
      enter.disconnect();
    };
  }, []);
  const caption = step >= 6 ? 'The lotus, complete: five things it keeps' : `${step} of 5 · ${STEPS[step - 1].title.replace(/\.$/, '')}`;
  return (
    <section className="story" id="how" aria-label="How Teresis keeps memory">
      <div className={`story-plate${drawn ? ' drawn' : ''}`} ref={plateRef}>
        <Lotus step={step} grid pad={0.3} />
        <p className="plate-cap" aria-live="polite">
          {caption}
        </p>
      </div>
      <ol className="story-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} data-step={i + 1} ref={(el) => void (refs.current[i] = el)} className={step === i + 1 ? 'active' : ''}>
            <span className="num" aria-hidden="true">
              {i + 1}
            </span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
            <Demo kind={s.demo} />
          </li>
        ))}
        <li className="story-end" data-step={6} ref={(el) => void (refs.current[STEPS.length] = el)} aria-hidden="true" />
      </ol>
    </section>
  );
}

export function App() {
  const lotusRef = useRef<SVGSVGElement>(null);
  const slipRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLElement>(null);
  const [showBar, setShowBar] = useState(false);

  useEffect(() => {
    const seen = {slip: true, close: false};
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.target === slipRef.current) seen.slip = e.isIntersecting;
        if (e.target === closeRef.current) seen.close = e.isIntersecting;
      }
      setShowBar(!seen.slip && !seen.close);
    });
    if (slipRef.current) io.observe(slipRef.current);
    if (closeRef.current) io.observe(closeRef.current);
    return () => io.disconnect();
  }, []);

  return (
    <>
      <header className="hero">
        <GridLayer anchor={lotusRef} />
        <nav className="nav" aria-label="Main">
          <a className="brand" href="#top" aria-label="Teresis home">
            <Mark />
            <span>Teresis</span>
          </a>
          <div className="links">
            <a href="#how">How it keeps</a>
            <a href="#proof">Benchmarks</a>
            <a href="#install">Install</a>
            <a href="https://github.com/raitoxlol/teresis" target="_blank" rel="noopener noreferrer">GitHub</a>
          </div>
          <a className="pill" href="#join">
            Get updates
          </a>
        </nav>
        <div className="hero-copy" id="top">
          <h1>
            {HERO.line1}
            <br />
            <span className="keeps">{HERO.line2}</span>
          </h1>
          <p className="sub">{HERO.sub}</p>
        </div>
        <Lotus svgRef={lotusRef} intro pad={0.08} className="hero-lotus" />
        <div className="slip" ref={slipRef}>
          <Waitlist id="email-hero" />
          <Install compact />
          <p className="proof-line">
            Live Hermes test: <b>{HERO.proof.teresis}</b> with Teresis, {HERO.proof.stock} with stock memory.
          </p>
        </div>
      </header>

      <main>
        <Story />

        <section className="proof" id="proof">
          <div className="wrap">
            <h2>100 out of 100 on a live Hermes test.</h2>
            <p className="lede">{LIVE_METHOD}</p>
            <Bars rows={LIVE_TOTAL} max={100} caption="Questions answered correctly, out of 100" />
            <table className="kinds">
              <caption>By kind of question</caption>
              <thead>
                <tr>
                  <th scope="col">Kind</th>
                  <th scope="col">Asked</th>
                  <th scope="col">Teresis</th>
                  <th scope="col">Stock Hermes</th>
                </tr>
              </thead>
              <tbody>
                {LIVE_BY_KIND.map((k) => (
                  <tr key={k.kind}>
                    <th scope="row">{k.kind}</th>
                    <td>{k.asked}</td>
                    <td className="t">{k.teresis}</td>
                    <td>{k.stock}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>And on public benchmarks.</h3>
            <div className="bench">
              <Bars rows={LONGMEMEVAL} max={1} caption="LongMemEval · ranking quality (NDCG@10) · median query time" />
              <Bars rows={LOCOMO} max={1} caption="LoCoMo · evidence in the top 5 (recall@5) · median query time" />
            </div>
            <p className="fine">Retrieval only, no LLM calls. Vector and hybrid systems share local Ollama all-minilm except total-agent-memory (built-in FastEmbed MiniLM, cross-encoder off). The optional Teresis reranker row adds a local MiniLM cross-encoder over the top 15 hits; all other rows are first-stage retrieval. mem0 OSS ran v3 hybrid (BM25 + spaCy + vectors, infer=False). Higher is better.</p>
          </div>
        </section>

        <section className="installs" id="install">
          <div className="wrap">
            <h2>Four interfaces, one file.</h2>
            <p className="lede">A Hermes memory provider, an MCP server, a local HTTP API, and a Python API. They share one SQLite file.</p>
            <Install />
          </div>
        </section>

        <section className="faq" aria-labelledby="faq-h">
          <div className="wrap">
            <h2 id="faq-h">Questions</h2>
            {FAQ.map((f) => (
              <details key={f.q}>
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="close" id="join" ref={closeRef}>
          <div className="wrap">
            <Mark className="close-mark" />
            <h2>The file stays on your machine.</h2>
            <p className="lede">Apache 2.0. Email is for release notes.</p>
            <Waitlist id="email-close" />
          </div>
        </section>
      </main>

      <footer className="foot">
        <Mark />
        <span>
          τήρησις <i>·</i> faithful keeping
        </span>
        <span className="c"><a href="https://github.com/raitoxlol/teresis" target="_blank" rel="noopener noreferrer">GitHub</a> · Apache 2.0</span>
      </footer>

      <div className={`bar${showBar ? ' show' : ''}`} aria-hidden={!showBar} inert={!showBar}>
        <span className="bar-t">
          <Mark /> Apache 2.0 · get release updates.
        </span>
        <Waitlist id="email-bar" compact />
      </div>
    </>
  );
}
