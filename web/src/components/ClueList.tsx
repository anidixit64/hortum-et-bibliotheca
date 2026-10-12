import { useState } from 'react'
import type { Clue, Explanation } from '../api/types'
import { ExplanationText } from './Written'
import { percent } from '../lib/format'

const TREND = { rising: '↑ rising', steady: '→ steady', fading: '↓ fading' } as const

export function ClueList({
  clues,
  explanations,
  writing = false,
}: {
  clues: Clue[]
  explanations?: Explanation[] // written for the cleaned clues; rank = clue rank
  writing?: boolean // explanations are being written
}) {
  const [open, setOpen] = useState<number | null>(null)
  const byRank = new Map((explanations ?? []).map((e) => [e.rank, e]))
  const lines = new Map((explanations ?? []).map((e) => [e.rank, e.one_line]))
  const names = clues.map((c) => ({ rank: c.rank, names: [c.label, ...(c.variants ?? [])] }))
  if (!clues.length) return <p className="muted">Not asked often enough to rank clues yet.</p>
  return (
    <ol className="clues">
      {clues.map((clue) => (
        <li key={clue.cluster_id} id={`clue-${clue.rank}`}>
          <div>
            <span className="clue-label">{clue.rank}. {clue.label}</span>{' '}
            <span className="muted small">
              {clue.n_questions ?? clue.n_tossups} questions · {clue.n_sets} sets · usually at{' '}
              {percent(clue.median_position)} of the question · {TREND[clue.heatmap.trend]}
              {clue.heatmap.share_in_power > 0.5 && ' · often in power'}
            </span>
          </div>
          {byRank.get(clue.rank) ? (
            <>
              <p className="one-line">{byRank.get(clue.rank)!.one_line}</p>
              <ExplanationText explanation={byRank.get(clue.rank)!} names={names} lines={lines} />
              <p className="clue-text muted small">As asked: {clue.text}</p>
            </>
          ) : (
            <>
              <p className="clue-text">{clue.text}</p>
              {writing && <p className="muted small writing-note">Explanation being written…</p>}
            </>
          )}
          {clue.cooccurs && clue.cooccurs.length > 0 && (
            <p className="muted small">
              Often with: {clue.cooccurs.slice(0, 3).map((c) => c.label).join(' · ')}
            </p>
          )}
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
