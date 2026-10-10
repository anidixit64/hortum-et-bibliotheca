import type { TimelineEvent } from '../api/types'
import { formatTime, yearOf } from '../lib/format'

const ROW = 22

/** Dated events for the topic and its related topics, oldest first, on a year axis. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  const dated = events
    .map((e) => ({ ...e, year: yearOf(e.time) }))
    .filter((e): e is TimelineEvent & { year: number } => e.year !== null)
    .slice(0, 24)
  if (!dated.length) return <p className="muted">No dates for this topic.</p>
  const years = dated.map((e) => e.year)
  const [lo, hi] = [Math.min(...years), Math.max(...years)]
  const span = Math.max(hi - lo, 1)
  const x = (year: number) => 70 + ((year - lo) / span) * 380
  return (
    <svg className="timeline" width="100%" viewBox={`0 0 760 ${dated.length * ROW + 10}`} role="img"
         aria-label="Timeline">
      <line className="axis" x1={70} x2={450} y1={4} y2={4} />
      {dated.map((e, i) => (
        <g key={`${e.id}-${e.event}-${i}`} transform={`translate(0, ${i * ROW + 16})`}>
          <text x={62} y={4} textAnchor="end" className="small">{formatTime(e.time, e.precision)}</text>
          <circle cx={x(e.year)} cy={0} r={e.is_topic ? 6 : 4}
                  fill={e.is_topic ? 'var(--accent-2)' : 'var(--accent)'} />
          <text x={470} y={4} fontWeight={e.is_topic ? 700 : 400}>
            {e.label}: {e.event}
          </text>
        </g>
      ))}
    </svg>
  )
}
