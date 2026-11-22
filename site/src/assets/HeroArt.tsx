import {useId} from 'react';
import {GoldGradient, MarkBody} from './Mark';
import {meanderPath, wingPaths} from './geometry';

const W = 1200;
const H = 440;
const CX = 600;
const BASE = 400;

function polar(r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(a), BASE - r * Math.sin(a)];
}

const RAYS = Array.from({length: 49}, (_, i) => {
  const deg = 8 + (i * 164) / 48;
  const long = i % 4 === 0;
  const [x1, y1] = polar(250, deg);
  const [x2, y2] = polar(long ? 470 : i % 2 ? 360 : 410, deg);
  return {x1, y1, x2, y2, o: long ? 0.34 : 0.18};
});

const NODE_ANGLES = [24, 48, 72, 108, 132, 156];

/** Wide hero illustration: sunburst of rays, dotted orbits, memory nodes, long wings, the staff, a meander band. */
export function HeroArt() {
  const id = useId();
  const grad = `${id}g`;
  const fade = `${id}f`;
  const wing = {count: 9, reach: 560, startY: 214, startStep: 7, tipY: 70, tipStep: 24};
  const nodes = NODE_ANGLES.map((d) => polar(300, d));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="A winged staff with rays, orbits and linked memory nodes" style={{display: 'block'}}>
      <defs>
        <GoldGradient id={grad} />
        <linearGradient id={fade} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#000" />
          <stop offset="0.12" stopColor="#fff" />
          <stop offset="0.88" stopColor="#fff" />
          <stop offset="1" stopColor="#000" />
        </linearGradient>
        <mask id={`${id}m`} maskUnits="userSpaceOnUse" x="0" y="0" width={W} height={H}>
          <rect width={W} height={H} fill={`url(#${fade})`} />
        </mask>
      </defs>
      <g mask={`url(#${id}m)`}>
        <g stroke="var(--color-accent)" strokeLinecap="round" fill="none">
          {RAYS.map((r, i) => <line key={i} x1={r.x1} y1={r.y1} x2={r.x2} y2={r.y2} strokeWidth="1" opacity={r.o} />)}
          {[190, 310, 430].map((r) => (
            <path key={r} d={`M${CX - r} ${BASE} A${r} ${r} 0 0 1 ${CX + r} ${BASE}`} strokeWidth="1" opacity="0.32" />
          ))}
          {[250, 370].map((r) => (
            <path key={r} d={`M${CX - r} ${BASE} A${r} ${r} 0 0 1 ${CX + r} ${BASE}`} strokeWidth="2.5" strokeDasharray="0.1 10" opacity="0.7" />
          ))}
          <polyline points={nodes.map((p) => p.join(',')).join(' ')} strokeWidth="1" opacity="0.4" />
        </g>
        <g fill="none" strokeLinecap="round" stroke={`url(#${grad})`}>
          {[-1, 1].flatMap((side) =>
            wingPaths(side as 1 | -1, CX, wing).map((d, i) => (
              <path key={`${side}${i}`} d={d} strokeWidth={2.2 - i * 0.12} opacity={0.62 - i * 0.045} />
            )),
          )}
        </g>
        <g fill="var(--color-accent)" stroke="var(--color-background-body)" strokeWidth="2">
          {nodes.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="5" />)}
        </g>
        <g transform={`translate(${CX - 60 * 2.05} ${BASE - 172 * 2.05}) scale(2.05)`}>
          <MarkBody gradient={grad} />
        </g>
        <path d={meanderPath(0, W, 436)} fill="none" stroke="var(--color-accent)" strokeWidth="2" opacity="0.6" strokeLinejoin="miter" />
      </g>
    </svg>
  );
}
