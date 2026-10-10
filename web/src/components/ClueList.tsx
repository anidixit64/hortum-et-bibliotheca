import { useState } from 'react'
import type { Clue } from '../api/types'
import { percent } from '../lib/format'

const TREND = { rising: '↑ rising', steady: '→ steady', fading: '↓ fading' } as const

export function ClueList({ clues }: { clues: Clue[] }) {
  const [open, setOpen] = useState<number | null>(null)
  if (!clues.length) return <p className="muted">Not asked often enough to rank clues yet.</p>
  return (
    <ol className="clues">
      {clues.map((clue) => (
        <li key={clue.cluster_id}>
          <div>
            <span className="clue-label">{clue.rank}. {clue.label}</span>{' '}
            <span className="muted small">
              {clue.n_sets} sets · usually at {percent(clue.median_position)} of the question ·{' '}
              {TREND[clue.heatmap.trend]}
              {clue.heatmap.share_in_power > 0.5 && ' · often in power'}
            </span>
          </div>
          <p className="clue-text">{clue.text}</p>
          {clue.examples.length > 0 && (
            <button className="small" onClick={() => setOpen(open === clue.cluster_id ? null : clue.cluster_id)}>
              {open === clue.cluster_id ? 'Hide' : `${clue.examples.length} other wording${clue.examples.length > 1 ? 's' : ''}`}
            </button>
          )}
          {open === clue.cluster_id && (
            <ul className="examples">
              {clue.examples.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}
        </li>
      ))}
    </ol>
  )
}
