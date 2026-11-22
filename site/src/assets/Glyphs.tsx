import type {ReactNode} from 'react';

const stroke = {
  fill: 'none',
  stroke: 'var(--color-accent)',
  strokeWidth: 2.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function Glyph({children, label}: {children: ReactNode; label: string}) {
  return (
    <svg viewBox="0 0 64 64" width="56" height="56" role="img" aria-label={label} style={{display: 'block'}}>
      <g {...stroke}>{children}</g>
    </svg>
  );
}

const feathers = (
  <>
    <path d="M22 40 C14 38 9 33 6 26" />
    <path d="M22 45 C15 44 11 41 9 36" />
    <path d="M42 40 C50 38 55 33 58 26" />
    <path d="M42 45 C49 44 53 41 55 36" />
  </>
);

/** Rows converge into one slot: duplicates reinforce, changed values supersede. */
export function WritesGlyph() {
  return (
    <Glyph label="Writes reconcile">
      <path d="M10 14 H26 C34 14 36 32 44 32" />
      <path d="M10 32 H44" />
      <path d="M10 50 H26 C34 50 36 32 44 32" />
      <circle cx="50" cy="32" r="5" fill="var(--color-accent)" />
    </Glyph>
  );
}

/** Nested path scopes. */
export function ScopesGlyph() {
  return (
    <Glyph label="Scopes are paths">
      <circle cx="32" cy="32" r="25" />
      <circle cx="32" cy="32" r="16" />
      <circle cx="32" cy="32" r="7" />
      <circle cx="32" cy="32" r="2" fill="var(--color-accent)" />
    </Glyph>
  );
}

/** Three channels converge on one result. */
export function RetrievalGlyph() {
  return (
    <Glyph label="Three retrieval channels">
      <path d="M8 12 L44 32" />
      <path d="M8 32 H44" strokeDasharray="1 6" />
      <path d="M8 52 L44 32" strokeOpacity="0.6" />
      <circle cx="50" cy="32" r="6" fill="var(--color-accent)" />
      <circle cx="50" cy="32" r="10" strokeOpacity="0.5" />
    </Glyph>
  );
}

/** One file, with feathers: local and deterministic. */
export function LocalGlyph() {
  return (
    <Glyph label="One local file">
      <ellipse cx="32" cy="16" rx="12" ry="5" />
      <path d="M20 16 V44 C20 47 25 50 32 50 C39 50 44 47 44 44 V16" />
      <path d="M20 30 C20 33 25 36 32 36 C39 36 44 33 44 30" />
      {feathers}
    </Glyph>
  );
}

/** Wing / orb / wing divider. */
export function Ornament() {
  const side = (s: 1 | -1) =>
    [0, 1, 2].map((i) => (
      <line key={`${s}${i}`} x1={110 + s * 14} y1={12 + (i - 1) * 5} x2={110 + s * (96 - i * 20)} y2={12 + (i - 1) * 5 - 3 + i} strokeWidth="1.6" strokeLinecap="round" />
    ));
  return (
    <svg viewBox="0 0 220 24" width="220" height="24" aria-hidden="true" style={{display: 'block'}}>
      <g stroke="var(--color-accent)" opacity="0.8">
        {side(-1)}
        {side(1)}
      </g>
      <path d="M110 5 L116 12 L110 19 L104 12 Z" fill="var(--color-accent)" />
    </svg>
  );
}
