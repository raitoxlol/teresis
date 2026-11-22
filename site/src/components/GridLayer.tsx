import {useLayoutEffect, useState, type CSSProperties, type RefObject} from 'react';
import {TILE} from '../lotus';

/** Full-bleed construction grid, aligned to the lattice of the lotus it sits behind. */
export function GridLayer({anchor}: {anchor: RefObject<SVGSVGElement | null>}) {
  const [transform, setTransform] = useState<string>();
  const [origin, setOrigin] = useState<{cx: number; cy: number; r: number}>();

  useLayoutEffect(() => {
    const update = () => {
      const svg = anchor.current;
      const host = svg?.closest('.hero');
      if (!svg || !host) return;
      const vb = svg.viewBox.baseVal;
      const r = svg.getBoundingClientRect();
      const h = host.getBoundingClientRect();
      const s = Math.min(r.width / vb.width, r.height / vb.height);
      const left = r.left - h.left + (r.width - vb.width * s) / 2;
      const top = r.top - h.top + (r.height - vb.height * s) / 2;
      setTransform(`translate(${left + (TILE.ox - vb.x) * s} ${top + (TILE.oy - vb.y) * s}) scale(${s})`);
      // the grid draws outward from the lotus centre; the radius must reach the farthest corner
      const cx = r.left - h.left + r.width / 2;
      const cy = r.top - h.top + r.height / 2;
      const far = Math.max(Math.hypot(cx, cy), Math.hypot(h.width - cx, cy), Math.hypot(cx, h.height - cy), Math.hypot(h.width - cx, h.height - cy));
      setOrigin({cx, cy, r: Math.ceil(far)});
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(document.documentElement);
    if (anchor.current) ro.observe(anchor.current);
    return () => ro.disconnect();
  }, [anchor]);

  return (
    <svg
      className={`gridlayer${origin ? ' drawing' : ''}`}
      aria-hidden="true"
      style={origin ? ({'--cx': `${origin.cx}px`, '--cy': `${origin.cy}px`, '--rmax': `${origin.r}px`} as CSSProperties) : undefined}
    >
      <defs>
        <pattern id="hero-grid" patternUnits="userSpaceOnUse" width={TILE.w} height={TILE.h} patternTransform={transform}>
          <path d={TILE.d} />
        </pattern>
      </defs>
      {transform && <rect width="100%" height="100%" fill="url(#hero-grid)" />}
    </svg>
  );
}
