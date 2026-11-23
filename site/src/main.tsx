import {flushSync} from 'react-dom';
import {createRoot} from 'react-dom/client';
import './styles.css';
import {App} from './App';
import cormorant from './fonts/cormorant-garamond.woff2?url';
import allo from './fonts/allo.woff2?url';
import {TILE} from './lotus';

for (const href of [cormorant, allo]) {
  const preload = document.createElement('link');
  preload.rel = 'preload';
  preload.as = 'font';
  preload.type = 'font/woff2';
  preload.crossOrigin = 'anonymous';
  preload.href = href;
  document.head.append(preload);
}

const scale = 3.2;
const lattice = `<svg xmlns="http://www.w3.org/2000/svg" width="${TILE.w * scale}" height="${TILE.h * scale}" viewBox="0 0 ${TILE.w} ${TILE.h}"><path d="${TILE.d}" fill="none" stroke="#d9af5b" stroke-opacity=".06" stroke-width=".2"/></svg>`;
document.documentElement.style.setProperty('--lattice', `url("data:image/svg+xml,${encodeURIComponent(lattice)}")`);
document.documentElement.style.setProperty('--lattice-x', `${-((TILE.ox % TILE.w) * scale)}px`);
document.documentElement.style.setProperty('--lattice-y', `${-((TILE.oy % TILE.h) * scale)}px`);

const root = createRoot(document.getElementById('root')!);
flushSync(() => root.render(<App />));
