import { Link } from 'react-router-dom'
import type { Confusion, Related as RelatedTopic } from '../api/types'

const link = (id: string) => `/topic/${encodeURIComponent(id)}`

export function RelatedList({ related }: { related: RelatedTopic[] }) {
  if (!related.length) return <p className="muted">No related topics found.</p>
  return (
    <ul className="clues">
      {related.map((r) => (
        <li key={r.id}>
          <Link to={link(r.id)}><strong>{r.name}</strong></Link>{' '}
          <span className="muted small">{r.why}</span>
          <p className="clue-text small">“{r.example.text}”</p>
        </li>
      ))}
    </ul>
  )
}

const REASON = { reject: 'answer lines reject it', same_name: 'same name', lookalike: 'look-alike name' }

export function ConfusionList({ confusions }: { confusions: Confusion[] }) {
  if (!confusions.length) return <p className="muted">Nothing commonly confused with this topic.</p>
  return (
    <ul className="clues">
      {confusions.map((c) => (
        <li key={c.id}>
          <Link to={link(c.id)}><strong>{c.name}</strong></Link>{' '}
          {c.reasons.map((r) => <span key={r} className="pill">{REASON[r]}</span>)}
          {c.evidence.reject?.[0] && (
            <div className="muted small">
              e.g. “do not accept {c.evidence.reject[0].text}”
              {c.evidence.n_rejects && c.evidence.n_rejects > 1 && ` (${c.evidence.n_rejects} questions)`}
            </div>
          )}
          {(c.distinguishing_clues.this.length > 0 || c.distinguishing_clues.other.length > 0) && (
            <div className="small">
              <span className="muted">This topic:</span> {c.distinguishing_clues.this.join(', ') || '—'}
              <br />
              <span className="muted">{c.name}:</span> {c.distinguishing_clues.other.join(', ') || '—'}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
