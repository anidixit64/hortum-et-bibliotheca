import type { TimelineEvent } from '../api/types'
import { formatTime, yearOf } from '../lib/format'

/** Dated events for the topic and its related topics, oldest first, on a year axis. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  const dated = events
    .map((e) => ({ ...e, year: yearOf(e.time) }))
    .filter((e): e is TimelineEvent & { year: number } => e.year !== null)
    .slice(0, 24)
  if (!dated.length) return <p className="muted">No dates for this topic.</p>
  return (
    <ol className="exhibit-timeline">
      {dated.map((e) => (
        <li key={`${e.id}-${e.event}`}>
          <span className="exhibit-year">{formatTime(e.time, e.precision)}</span>
          <span>
            {e.label}: {e.event}
          </span>
        </li>
      ))}
    </ol>
  )
}
