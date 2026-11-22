import type {BarRow} from '../content';

/** One measure per chart, one axis, direct labels on every row; Teresis rows carry the ochre. */
export function Bars({rows, max, caption}: {rows: BarRow[]; max: number; caption: string}) {
  return (
    <figure className="bars">
      <figcaption>{caption}</figcaption>
      <ul>
        {rows.map((r) => (
          <li key={r.label} className={r.highlight ? 'hi' : ''}>
            <span className="bl">{r.label}</span>
            <span className="track" aria-hidden="true">
              <span className="fill" style={{width: `${(r.value / max) * 100}%`}} />
            </span>
            <span className="bv">{r.display}</span>
            {r.note && <span className="bn">{r.note}</span>}
          </li>
        ))}
      </ul>
    </figure>
  );
}
