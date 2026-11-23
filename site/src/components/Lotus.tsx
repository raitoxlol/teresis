import {useId, type Ref} from 'react';
import {MARK, PETALS, TILE} from '../lotus';

type Props = {
  /** 0 = grid only, 1-5 = petals assembled so far (the newest bright, earlier ones ghosted), 6 = complete. */
  step?: number;
  intro?: boolean;
  grid?: boolean;
  pad?: number;
  className?: string;
  svgRef?: Ref<SVGSVGElement>;
};

function petalState(index: number, step: number) {
  const n = index + 1;
  if (step >= 6) return 'on';
  if (n < step) return 'ghost';
  if (n === step) return 'new';
  return 'off';
}

export function Lotus({step = 6, intro = false, grid = false, pad = 0.12, className = '', svgRef}: Props) {
  const side = Math.max(MARK.w, MARK.h) * (1 + pad);
  const vx = (MARK.w - side) / 2;
  const vy = (MARK.h - side) / 2;
  const pid = `lg${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  return (
    <svg ref={svgRef} className={`lotus${intro ? ' is-intro' : ''} ${className}`} viewBox={`${vx} ${vy} ${side} ${side}`} aria-hidden="true">
      {grid && (
        <>
          <defs>
            <pattern id={pid} patternUnits="userSpaceOnUse" x={TILE.ox} y={TILE.oy} width={TILE.w} height={TILE.h}>
              <path d={TILE.d} className="tile" />
            </pattern>
          </defs>
          <rect className="lotus-grid" x={vx} y={vy} width={side} height={side} fill={`url(#${pid})`} />
        </>
      )}
      {PETALS.map((d, i) => (
        <path key={i} d={d} className={`petal p${i} ${petalState(i, step)}`} />
      ))}
    </svg>
  );
}

/** Small solid mark for the nav and footer. */
export function Mark({className = ''}: {className?: string}) {
  return (
    <svg className={`lotus-mark ${className}`} viewBox={`0 0 ${MARK.w} ${MARK.h}`} aria-hidden="true">
      <path d={PETALS.join('')} />
    </svg>
  );
}
