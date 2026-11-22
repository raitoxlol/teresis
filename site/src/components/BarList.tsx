import {VStack} from '@astryxdesign/core/VStack';
import {HStack} from '@astryxdesign/core/HStack';
import {Text} from '@astryxdesign/core/Text';
import {Tooltip} from '@astryxdesign/core/Tooltip';
import type {BarRow} from '../content';

const BAR_H = 12;

/** Horizontal bars on one baseline. Emphasis form: highlighted rows carry the accent, the rest stay neutral. */
export function BarList({rows, max, metric}: {rows: BarRow[]; max: number; metric: string}) {
  return (
    <VStack gap={4}>
      {rows.map((r) => {
        const pct = Math.max(0, Math.min(100, (r.value / max) * 100));
        const tip = `${r.label}: ${metric} ${r.display}${r.note ? ` · ${r.note}` : ''}`;
        return (
          <Tooltip key={r.label} content={tip} placement="above" alignment="start">
            <VStack gap={1.5}>
              <HStack hAlign="between" gap={3}>
                <Text type="label" color={r.highlight ? 'primary' : 'secondary'} weight={r.highlight ? 'semibold' : 'normal'}>
                  {r.label}
                </Text>
                <Text type="label" weight="semibold" hasTabularNumbers>
                  {r.display}
                </Text>
              </HStack>
              <svg width="100%" height={BAR_H} role="img" aria-label={tip} style={{display: 'block'}}>
                <rect x="0" y="0" width="100%" height={BAR_H} rx="4" fill="var(--color-background-muted)" />
                {pct > 0 && (
                  <>
                    <rect x="0" y="0" width={`${pct}%`} height={BAR_H} rx="4" fill={r.highlight ? 'var(--color-accent)' : 'var(--color-border-emphasized)'} />
                    <rect x="0" y="0" width="6" height={BAR_H} fill={r.highlight ? 'var(--color-accent)' : 'var(--color-border-emphasized)'} />
                  </>
                )}
              </svg>
            </VStack>
          </Tooltip>
        );
      })}
    </VStack>
  );
}
