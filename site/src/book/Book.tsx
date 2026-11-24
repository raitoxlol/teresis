import {useEffect, useRef, useState, type ComponentType, type CSSProperties} from 'react';
import {PAGES} from './pages';
import {onIdle} from './idle';
import type {createScene, ViewState} from './scene';
import type {capturePages} from './snapshots';
import './book.css';

const LAST = PAGES.length / 2;
const PORTRAIT = '(max-aspect-ratio: 5/6)';
const REDUCED = '(prefers-reduced-motion: reduce)';
const PAGE_INDEX = new Map(PAGES.map(({id}, index): [string, number] => [id, index]));
const INTERACTIVE = 'a[href], button, summary, input, select, textarea, label[for], [role="tab"], [tabindex]:not([tabindex="-1"])';

export const NAV_ITEMS = [
  ['try', 'Try it', 2], ['how', 'Method', 3], ['works-with', 'Works with', 4],
  ['benchmarks', 'Benchmarks', 5], ['questions', 'Questions', 7],
] as const;

export type PageProps = {fact?: string; onTell?: (fact: string) => void; onForget?: () => void};
type Stop = ViewState;
type Engine = ReturnType<typeof createScene>;

// Build-time knob for inspecting the motion frame by frame; 1 in every normal build.
const SLOW = Number(import.meta.env.VITE_BOOK_SLOW ?? 1) || 1;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const easeInOut = (t: number) => (t < .5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

// Desktop rests on each spread. A portrait screen reads one page at a time:
// left page, right page, then the leaf turns.
function stopsFor(portrait: boolean): Stop[] {
  const stops: Stop[] = [{p: 0, focus: 0}];
  for (let p = 1; p <= LAST; p++) {
    if (portrait) stops.push({p, focus: -1}, {p, focus: 1});
    else stops.push({p, focus: 0});
  }
  return stops;
}

function stopForPage(index: number, stops: Stop[], portrait: boolean) {
  const p = 1 + Math.floor(index / 2);
  const focus = portrait ? (index % 2 ? 1 : -1) : 0;
  return Math.max(0, stops.findIndex((stop) => stop.p === p && stop.focus === focus));
}

function durationFor(from: Stop, to: Stop) {
  const leaves = Math.abs(to.p - from.p);
  if (!leaves) return to.focus === from.focus ? 0 : 560;
  const cover = Math.min(from.p, to.p) < 1;
  if (leaves <= 1) return cover ? 1500 : 1180;
  return 760 + 430 * leaves;
}

export function Book({fact, onTell, onForget, onStep}: PageProps & {onStep: (spread: number) => void}) {
  const [mode, setMode] = useState<'loading' | 'book' | 'paper'>('loading');
  const [opened, setOpened] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Start WebGL; without it the pages are shown as paper.
  useEffect(() => {
    let cancelled = false;
    const cancelIdle = onIdle(async () => {
      try {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('webgl2', {alpha: true, antialias: true});
        if (!context) throw new Error('webgl2');
        const {createScene} = await import('./scene');
        if (cancelled || !stage.current) return;
        const engine = createScene(canvas, context, PAGES, () => canvas.dispatchEvent(new Event('materialready')));
        await engine.printed;
        if (cancelled || !stage.current) {
          engine.dispose();
          return;
        }
        const {clientWidth: w, clientHeight: h} = stage.current;
        engine.resize(w, h);
        if (!engine.render({p: 0, focus: 0})) {
          engine.dispose();
          throw new Error('shader');
        }
        canvas.setAttribute('aria-hidden', 'true');
        stage.current.prepend(canvas);
        engineRef.current = engine;
        canvasRef.current = canvas;
        setMode('book');
      } catch {
        if (!cancelled) setMode('paper');
      }
    }, 120);
    return () => {
      cancelled = true;
      cancelIdle();
      engineRef.current?.dispose();
      engineRef.current = null;
      canvasRef.current?.remove();
    };
  }, []);

  useEffect(() => {
    if (mode !== 'book') return;
    const engine = engineRef.current!;
    const canvas = canvasRef.current!;
    const stageElement = stage.current!;
    const pageElements = Array.from(host.current!.querySelectorAll<HTMLElement>('.book-page'));
    const reducedQuery = matchMedia(REDUCED);
    const portraitQuery = matchMedia(PORTRAIT);
    let portrait = portraitQuery.matches;
    let stops = stopsFor(portrait);
    let index = 0;
    let view: Stop = {...stops[0]};
    let anim: {from: Stop; to: Stop; start: number; duration: number} | null = null;
    let frame = 0;
    let dirty = true;
    let settledAt = 0;
    let stopped = false;
    let snapshots: ReturnType<typeof capturePages> | undefined;
    document.documentElement.classList.add('book-locked');
    requestAnimationFrame(() => canvas.dataset.ready = '');

    function kick() {
      if (!frame && !stopped) frame = requestAnimationFrame(tick);
    }

    function tick(now: number) {
      frame = 0;
      if (anim) {
        const k = anim.duration ? clamp((now - anim.start) / anim.duration, 0, 1) : 1;
        const e = easeInOut(k);
        view = {p: anim.from.p + (anim.to.p - anim.from.p) * e, focus: anim.from.focus + (anim.to.focus - anim.from.focus) * e};
        if (k >= 1) {
          view = {...anim.to};
          anim = null;
          settledAt = now;
        }
        dirty = true;
      }
      if (dirty && !document.hidden) {
        dirty = false;
        engine.resize(stageElement.clientWidth, stageElement.clientHeight);
        if (!engine.render(view)) {
          setMode('paper');
          return;
        }
        snapshots?.prioritize(anim?.to.p ?? view.p);
      }
      if (anim) kick();
    }

    function refresh() {
      dirty = true;
      kick();
    }

    function go(next: number, instant = false) {
      next = clamp(next, 0, stops.length - 1);
      if (next === index && !anim) return;
      index = next;
      const to = stops[index];
      const duration = instant || reducedQuery.matches ? 0 : durationFor(view, to) * SLOW;
      anim = {from: {...view}, to, start: performance.now(), duration};
      onStep(to.p);
      setOpened(index > 0);
      const active = document.activeElement;
      if (active instanceof HTMLElement && host.current?.contains(active)) active.blur();
      kick();
    }

    // Scroll, swipe and keys turn the pages.
    let accumulated = 0;
    let lastWheel = 0;
    let lastMagnitude = 0;
    function onWheel(event: WheelEvent) {
      if (event.ctrlKey) return;
      event.preventDefault();
      const now = performance.now();
      const gap = now - lastWheel;
      lastWheel = now;
      const unit = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 800 : 1;
      const delta = (Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX) * unit;
      const magnitude = Math.abs(delta);
      // Momentum after a turn keeps arriving in a fast, fading stream.
      const momentum = gap < 90 && magnitude <= lastMagnitude * 1.15 + 1;
      lastMagnitude = magnitude;
      if (anim) {
        accumulated = 0;
        return;
      }
      if (momentum && now - settledAt < 1300) return;
      if (gap > 220) accumulated = 0;
      accumulated += delta;
      if (Math.abs(accumulated) >= 34) {
        go(index + Math.sign(accumulated));
        accumulated = 0;
      }
    }

    let touch: {x: number; y: number} | null = null;
    function onTouchStart(event: TouchEvent) {
      touch = event.touches.length === 1 ? {x: event.touches[0].clientX, y: event.touches[0].clientY} : null;
    }
    function onTouchMove(event: TouchEvent) {
      if (touch) event.preventDefault();
    }
    function onTouchEnd(event: TouchEvent) {
      if (!touch) return;
      const end = event.changedTouches[0];
      const dx = end.clientX - touch.x;
      const dy = end.clientY - touch.y;
      touch = null;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 40 || anim) return;
      const forward = Math.abs(dy) > Math.abs(dx) ? dy < 0 : dx < 0;
      go(index + (forward ? 1 : -1));
    }

    function onKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && (active.matches('input, textarea, select') || active.isContentEditable)) {
        if (event.key === 'Escape') active.blur();
        return;
      }
      const onControl = active && active !== document.body && active.matches('a, button, summary, [role="tab"]');
      let next: number | undefined;
      if (['ArrowRight', 'ArrowDown', 'PageDown'].includes(event.key) || (event.key === ' ' && !event.shiftKey && !onControl)) next = index + 1;
      else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key) || (event.key === ' ' && event.shiftKey && !onControl)) next = index - 1;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = stops.length - 1;
      if (next === undefined || (onControl && active.getAttribute('role') === 'tab' && event.key.startsWith('Arrow'))) return;
      event.preventDefault();
      go(next);
    }

    // A tap on a page reaches the element at that spot of the DOM page.
    function elementAt(page: number, x: number, y: number) {
      const pageElement = pageElements[page];
      if (!pageElement) return null;
      const box = pageElement.getBoundingClientRect();
      let best: HTMLElement | null = null;
      let bestArea = Infinity;
      for (const element of pageElement.querySelectorAll<HTMLElement>(INTERACTIVE)) {
        const rect = element.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;
        const left = rect.left - box.left - 4;
        const top = rect.top - box.top - 4;
        if (x < left || y < top || x > left + rect.width + 8 || y > top + rect.height + 8) continue;
        const area = rect.width * rect.height;
        if (area < bestArea) {
          best = element;
          bestArea = area;
        }
      }
      return best;
    }

    function hitAt(event: PointerEvent) {
      const rect = canvas.getBoundingClientRect();
      const hit = engine.pick(event.clientX - rect.left, event.clientY - rect.top);
      if (!hit) return null;
      return {...hit, element: elementAt(hit.page, hit.u * 560, hit.v * 800)};
    }

    let down: {x: number; y: number} | null = null;
    function onPointerDown(event: PointerEvent) {
      down = {x: event.clientX, y: event.clientY};
    }
    function onPointerUp(event: PointerEvent) {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 8 || anim) {
        down = null;
        return;
      }
      down = null;
      if (index === 0) {
        go(1);
        return;
      }
      const hit = hitAt(event);
      const active = document.activeElement;
      if (!hit) {
        if (active instanceof HTMLElement && host.current?.contains(active)) active.blur();
        return;
      }
      if (hit.element) {
        const control = hit.element.matches('label[for]')
          ? document.getElementById(hit.element.getAttribute('for')!) : hit.element;
        if (control?.matches('input, textarea, select')) (control as HTMLInputElement).focus({preventScroll: true});
        else hit.element.click();
        return;
      }
      if (active instanceof HTMLElement && host.current?.contains(active)) active.blur();
      const left = hit.page % 2 === 0;
      if (left && hit.u < .24) go(index - 1);
      else if (!left && hit.u > .76) go(index + 1);
    }

    let hoverFrame = 0;
    let hoverEvent: PointerEvent | null = null;
    function onPointerMove(event: PointerEvent) {
      hoverEvent = event;
      if (hoverFrame) return;
      hoverFrame = requestAnimationFrame(() => {
        hoverFrame = 0;
        if (!hoverEvent || anim) return;
        if (index === 0) {
          canvas.style.cursor = 'pointer';
          return;
        }
        const hit = hitAt(hoverEvent);
        const edge = hit && !hit.element && (hit.page % 2 === 0 ? hit.u < .24 : hit.u > .76);
        canvas.style.cursor = hit?.element || edge ? 'pointer' : '';
      });
    }

    function onDocumentClick(event: MouseEvent) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element).closest?.<HTMLAnchorElement>('a[href^="#"]');
      if (!link) return;
      const id = link.getAttribute('href')!.slice(1);
      const page = PAGE_INDEX.get(id);
      if (page === undefined && id !== 'top') return;
      event.preventDefault();
      if (location.hash !== `#${id}`) history.pushState(null, '', `#${id}`);
      go(page === undefined ? 0 : stopForPage(page, stops, portrait));
    }

    function fromHash(instant: boolean) {
      const id = location.hash.slice(1);
      const page = PAGE_INDEX.get(id);
      if (page !== undefined) go(stopForPage(page, stops, portrait), instant);
      else if (!id || id === 'top') go(0, instant);
    }

    function onFocusIn(event: FocusEvent) {
      const page = (event.target as Element).closest<HTMLElement>('[data-page-index]');
      if (!page) return;
      const pageIndex = Number(page.dataset.pageIndex);
      const spread = 1 + Math.floor(pageIndex / 2);
      if (stops[index].p !== spread || (portrait && stops[index].focus !== (pageIndex % 2 ? 1 : -1))) {
        go(stopForPage(pageIndex, stops, portrait));
      }
    }

    function onResize() {
      const nextPortrait = portraitQuery.matches;
      if (nextPortrait !== portrait) {
        const current = stops[index];
        portrait = nextPortrait;
        stops = stopsFor(portrait);
        const focus = portrait && current.p > 0 ? -1 : 0;
        index = Math.max(0, stops.findIndex((stop) => stop.p === current.p && stop.focus === focus));
        anim = null;
        view = {...stops[index]};
      }
      refresh();
    }

    canvas.addEventListener('materialready', refresh);
    fromHash(true);
    refresh();
    const resize = new ResizeObserver(onResize);
    resize.observe(stageElement);
    window.addEventListener('wheel', onWheel, {passive: false});
    window.addEventListener('keydown', onKey);
    const onHash = () => fromHash(false);
    window.addEventListener('hashchange', onHash);
    document.addEventListener('click', onDocumentClick);
    document.addEventListener('visibilitychange', refresh);
    stageElement.addEventListener('touchstart', onTouchStart, {passive: true});
    stageElement.addEventListener('touchmove', onTouchMove, {passive: false});
    stageElement.addEventListener('touchend', onTouchEnd);
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointermove', onPointerMove);
    host.current!.addEventListener('focusin', onFocusIn);
    const hostElement = host.current!;

    void import('./snapshots').then(({capturePages}) => {
      if (stopped) return;
      snapshots = capturePages(pageElements, (page, snapshot) => {
        if (stopped) return;
        engine.setSnapshot(page, snapshot);
        refresh();
      }, (index) => {
        if (!PAGES[index].print) return false;
        const candidates = pageElements[index].querySelectorAll<HTMLElement>('[data-book-print]');
        const visible = Array.from(candidates).find(node => !node.closest('[hidden]'));
        return !!visible?.dataset.bookPrint && engine.showPrint(index, visible.dataset.bookPrint);
      });
      snapshots.prioritize(stops[index].p);
    }).catch(() => { /* Pages keep their titled paper. */ });

    return () => {
      stopped = true;
      canvas.removeEventListener('materialready', refresh);
      snapshots?.dispose();
      cancelAnimationFrame(frame);
      cancelAnimationFrame(hoverFrame);
      resize.disconnect();
      document.documentElement.classList.remove('book-locked');
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('hashchange', onHash);
      document.removeEventListener('click', onDocumentClick);
      document.removeEventListener('visibilitychange', refresh);
      stageElement.removeEventListener('touchstart', onTouchStart);
      stageElement.removeEventListener('touchmove', onTouchMove);
      stageElement.removeEventListener('touchend', onTouchEnd);
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointermove', onPointerMove);
      hostElement.removeEventListener('focusin', onFocusIn);
    };
  }, [mode, onStep]);

  function sheet(index: number) {
    const {id, title, Content, ...page} = PAGES[index];
    const Page = Content as ComponentType<PageProps>;
    return (
      <div className="book-sheet" key={id} data-side={index % 2 === 0 ? 'left' : 'right'}>
        <article id={id} className="book-page" aria-label={title} data-page-index={index} data-endpaper={'endpaper' in page ? '' : undefined}>
          {'endpaper' in page
            ? <div className="endpaper-pattern" aria-hidden="true" />
            : <img className="painted-margin" src={`${import.meta.env.BASE_URL}book/illumination.svg`} alt="" />}
          <Page fact={fact} onTell={onTell} onForget={onForget} />
          {!('endpaper' in page) && <span className="folio" aria-label={`Page ${index}`}>{index}</span>}
        </article>
      </div>
    );
  }

  const style = {
    '--book-endpaper': `url("${import.meta.env.BASE_URL}book/endpaper.svg")`,
    '--book-paper': `url("${import.meta.env.BASE_URL}book/paper.webp")`,
    '--book-cloth': `url("${import.meta.env.BASE_URL}book/cloth.webp")`,
  } as CSSProperties;

  if (mode === 'paper') {
    return (
      <main id="main" className="book-track" data-mode="paper" style={style}>
        <section className="paper-intro" id="top">
          <div className="wrap">
            <h1>Tell your agents once</h1>
            <p>Teresis is local long-term memory for AI agents. Your facts, preferences and decisions live in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.</p>
          </div>
        </section>
        <div ref={host}>
          {Array.from({length: LAST}, (_, spread) => (
            <section className="paper-spread" key={spread} aria-label={PAGES[spread * 2].title}>
              <div className="wrap">{sheet(spread * 2)}{sheet(spread * 2 + 1)}</div>
            </section>
          ))}
        </div>
      </main>
    );
  }

  return (
    <main id="main" className="book-track book-main" data-mode="book" style={style}>
      <h1 className="sr-only" id="top">Tell your agents once</h1>
      <p className="sr-only">Teresis is local long-term memory for AI agents. Your facts, preferences and decisions live in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.</p>
      <div className="book-stage3d" ref={stage}>
        <p className="book-hint" data-hidden={opened || mode !== 'book'} aria-hidden="true">{matchMedia('(pointer: coarse)').matches ? 'Swipe to open' : 'Scroll to open'}</p>
      </div>
      <div className="book-offscreen" ref={host}>{PAGES.map((_, index) => sheet(index))}</div>
    </main>
  );
}
