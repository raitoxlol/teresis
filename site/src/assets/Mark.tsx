import {useId} from 'react';
import {helixPath, wingPaths, MARK_WING} from './geometry';

const GOLD_FROM = 'var(--color-accent)';
const GOLD_TO = 'var(--color-text-accent)';

/** The winged-staff mark: an orb for the memory kept, wings for the messenger, a double helix for history. */
export function MarkBody({gradient}: {gradient: string}) {
  const stroke = `url(#${gradient})`;
  const left = wingPaths(-1, 60, MARK_WING);
  const right = wingPaths(1, 60, MARK_WING);
  return (
    <g fill="none" stroke={stroke} strokeLinecap="round" strokeLinejoin="round">
      <line x1="60" y1="34" x2="60" y2="154" strokeWidth="3" />
      {left.map((d, i) => <path key={`l${i}`} d={d} strokeWidth={3 - i * 0.28} />)}
      {right.map((d, i) => <path key={`r${i}`} d={d} strokeWidth={3 - i * 0.28} />)}
      <path d={helixPath(60, 66, 148, 14, 2, 0)} strokeWidth="3" />
      <path d={helixPath(60, 66, 148, 14, 2, Math.PI)} strokeWidth="3" opacity="0.62" />
      <circle cx="60" cy="24" r="9" fill={stroke} stroke="none" />
      <circle cx="60" cy="24" r="14" strokeWidth="1.6" opacity="0.55" />
      <path d="M60 154 L66 163 L60 172 L54 163 Z" fill={stroke} stroke="none" />
    </g>
  );
}

export function GoldGradient({id}: {id: string}) {
  return (
    <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="176">
      <stop offset="0" style={{stopColor: GOLD_TO}} />
      <stop offset="1" style={{stopColor: GOLD_FROM}} />
    </linearGradient>
  );
}

export function Mark({height = 44, title}: {height?: number; title?: string}) {
  const id = useId();
  return (
    <svg
      viewBox="0 0 120 176"
      height={height}
      width={(height * 120) / 176}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      style={{display: 'block', flexShrink: 0}}>
      <defs><GoldGradient id={id} /></defs>
      <MarkBody gradient={id} />
    </svg>
  );
}
