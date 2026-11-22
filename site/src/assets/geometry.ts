const TAU = Math.PI * 2;

/** One strand of the staff's double helix, as an SVG path. */
export function helixPath(cx: number, y0: number, y1: number, amp: number, turns: number, phase: number, steps = 56) {
  const pts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const x = cx + amp * Math.sin(TAU * turns * t + phase);
    const y = y0 + (y1 - y0) * t;
    pts.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return pts.join(' ');
}

/** Feathers of one wing. Upper feathers reach furthest; each tip fans upward and outward. */
export function wingPaths(side: 1 | -1, cx: number, o: {count: number; reach: number; startY: number; startStep: number; tipY: number; tipStep: number}) {
  return Array.from({length: o.count}, (_, i) => {
    const k = o.count === 1 ? 0 : i / (o.count - 1);
    const sx = cx + side * 6;
    const sy = o.startY + i * o.startStep;
    const tx = cx + side * o.reach * (1 - 0.72 * k);
    const ty = o.tipY + i * o.tipStep;
    const c1x = cx + side * o.reach * 0.35;
    const c1y = sy - 10;
    const c2x = tx - side * o.reach * 0.28 * (1 - 0.3 * k);
    const c2y = ty + 14;
    return `M${sx} ${sy} C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${tx.toFixed(1)} ${ty.toFixed(1)}`;
  });
}

/** A Greek-key (meander) band: baseline plus one key per unit. */
export function meanderPath(x0: number, x1: number, y: number, unit = 24, h = 18) {
  const parts = [`M${x0} ${y} H${x1}`];
  for (let x = x0; x < x1; x += unit) {
    parts.push(`M${x} ${y} V${y - h} H${x + 16} V${y - h + 12} H${x + 8} V${y - h + 6}`);
  }
  return parts.join(' ');
}

export const MARK_WING = {count: 5, reach: 50, startY: 46, startStep: 6, tipY: 24, tipStep: 11};
