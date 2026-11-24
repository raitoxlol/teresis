import {getFontEmbedCSS, toCanvas} from 'html-to-image';
import {onIdle} from './idle';

export function capturePages(pages: HTMLElement[], receive: (index: number, canvas: HTMLCanvasElement) => void, usePrint: (index: number) => boolean) {
  const dirty = new Set(Array.from(pages.keys()).filter(index => !usePrint(index)));
  const pageIndices = new Map(pages.map((page, index) => [page, index]));
  let cancelIdle: (() => void) | undefined;
  let busy = false;
  let stopped = false;
  let spread = 0;

  function nextPage() {
    let nearest: number | undefined;
    let distance = Infinity;
    for (const page of dirty) {
      const proximity = Math.abs(Math.floor(page / 2) - spread);
      if (proximity < distance) {
        nearest = page;
        distance = proximity;
      }
    }
    return nearest;
  }

  function schedule() {
    if (stopped || busy || cancelIdle || document.hidden || dirty.size === 0) return;
    const next = nextPage()!;
    const nearby = Math.abs(Math.floor(next / 2) - spread) <= 1;
    cancelIdle = onIdle(capture, nearby ? 16 : 500);
  }

  async function capture() {
    cancelIdle = undefined;
    if (stopped || document.hidden) return;
    const index = nextPage();
    if (index === undefined) return;
    dirty.delete(index);
    busy = true;
    try {
      const canvas = await toCanvas(pages[index], {
        width: 560,
        height: 800,
        pixelRatio: 1.75,
        filter: (node) => !(node instanceof HTMLElement && node.hidden),
        backgroundColor: getComputedStyle(pages[index]).backgroundColor,
        fontEmbedCSS: await fonts,
        style: {transform: 'none', position: 'relative', opacity: '1', visibility: 'visible'},
      });
      if (!stopped && !dirty.has(index) && !usePrint(index)) receive(index, canvas);
    } catch {
      // Keep the previous texture if this revision cannot be rasterized.
    } finally {
      busy = false;
      schedule();
    }
  }

  function markDirty(target: Node) {
    const element = target instanceof Element ? target : target.parentElement;
    const page = element?.closest<HTMLElement>('[data-page-index]');
    const index = page && pageIndices.get(page);
    if (typeof index !== 'number') return;
    if (usePrint(index)) dirty.delete(index);
    else dirty.add(index);
  }

  function onInput(event: Event) {
    if (event.target instanceof Node) markDirty(event.target);
    schedule();
  }

  const observer = new MutationObserver((records) => {
    const seen = new Map<Element, Set<string>>();
    for (const {target, attributeName, oldValue} of records) {
      if (target instanceof Element && attributeName) {
        let attributes = seen.get(target);
        if (!attributes) {
          attributes = new Set();
          seen.set(target, attributes);
        }
        // React can rewrite form attributes to their original value in one commit.
        if (attributes.has(attributeName)) continue;
        attributes.add(attributeName);
        if (target.getAttribute(attributeName) === oldValue) continue;
      }
      markDirty(target);
    }
    schedule();
  });
  // Font embedding is shared by all snapshots. Begin before the first idle turn.
  const fonts = getFontEmbedCSS(pages[0], {preferredFontFormat: 'woff2'}).catch(() => '');
  for (const page of pages) {
    observer.observe(page, {attributeOldValue: true, subtree: true, childList: true, characterData: true});
    page.addEventListener('input', onInput);
    page.addEventListener('change', onInput);
  }
  document.addEventListener('visibilitychange', schedule);
  schedule();

  return {
    prioritize(progress: number) {
      const settled = Math.floor(progress);
      // During a turn, both spreads supply visible faces.
      const nearest = Math.max(0, settled - 1 + (progress === settled ? 0 : .5));
      if (spread === nearest) return;
      spread = nearest;
      cancelIdle?.();
      cancelIdle = undefined;
      schedule();
    },
    dispose() {
      stopped = true;
      cancelIdle?.();
      observer.disconnect();
      for (const page of pages) {
        page.removeEventListener('input', onInput);
        page.removeEventListener('change', onInput);
      }
      document.removeEventListener('visibilitychange', schedule);
    },
  };
}
