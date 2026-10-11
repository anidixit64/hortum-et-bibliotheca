import { useState } from 'react'
import type { Explanation, FunFact, WrittenSummary } from '../api/types'
import { linkClues, parseMarks, type Piece } from '../lib/marks'

/** A clue named in the text: bold; hover or tap shows its one-line summary and a link to
 *  its full explanation further down. */
export function ClueMention({ text, rank, line }: { text: string; rank: number; line?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span
      className="mention"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button type="button" className="mention-text" onClick={() => setOpen(!open)} aria-expanded={open}>
        {text}
      </button>
      {open && (
        <span className="popover" role="tooltip">
          {line && <span className="popover-line">{line}</span>}
          <a href={`#clue-${rank}`} onClick={() => setOpen(false)}>See more</a>
        </span>
      )}
    </span>
  )
}

function Pieces({ pieces, lines }: { pieces: Piece[]; lines: Map<number, string> }) {
  return (
    <>
      {pieces.map((p, i) =>
        p.rank === undefined ? (
          <span key={i}>{p.text}</span>
        ) : (
          <ClueMention key={i} text={p.text} rank={p.rank} line={lines.get(p.rank)} />
        ),
      )}
    </>
  )
}

export function Hook({ summary }: { summary: WrittenSummary }) {
  return <p className="hook">{summary.hook}</p>
}

export function Summary({
  summary,
  explanations,
}: {
  summary: WrittenSummary
  explanations: Explanation[]
}) {
  const lines = new Map(explanations.map((e) => [e.rank, e.one_line]))
  return (
    <>
      {summary.summary.split(/\n\s*\n/).map((para, i) => (
        <p key={i} className="prose">
          <Pieces pieces={parseMarks(para)} lines={lines} />
        </p>
      ))}
      <p className="muted small attribution">
        Written by AI from{' '}
        {summary.source ? (
          <>
            the Wikipedia article{' '}
            <a href={summary.source.url} target="_blank" rel="noreferrer">
              “{summary.source.title}”
            </a>{' '}
            ({summary.source.license})
          </>
        ) : (
          'general knowledge'
        )}
        . Bold terms are clues: hover or tap for a summary.
      </p>
    </>
  )
}

/** A clue's explanation, with the topic's other clues it names linked to their cards. */
export function ExplanationText({
  explanation,
  names,
  lines,
}: {
  explanation: Explanation
  names: { rank: number; names: string[] }[]
  lines: Map<number, string>
}) {
  return (
    <p className="prose explanation">
      <Pieces pieces={linkClues(explanation.explanation, names, explanation.rank)} lines={lines} />
    </p>
  )
}

/** "Did you know?" plaques: each fact with the Wikipedia sentence it rests on. */
export function FunFacts({ facts, source }: { facts: FunFact[]; source?: { title: string; url: string } }) {
  if (!facts.length) return null
  return (
    <>
      <div className="plaques">
        {facts.map((f) => (
          <figure key={f.fact} className="plaque">
            <span className="plaque-mark" aria-hidden>?</span>
            <p>{f.fact}</p>
            <figcaption className="muted small" title={f.source_sentence}>
              From Wikipedia: “{f.source_sentence.length > 140 ? `${f.source_sentence.slice(0, 140)}…` : f.source_sentence}”
            </figcaption>
          </figure>
        ))}
      </div>
      {source && (
        <p className="muted small attribution">
          Facts picked by AI from{' '}
          <a href={source.url} target="_blank" rel="noreferrer">“{source.title}”</a> (CC BY-SA 4.0).
        </p>
      )}
    </>
  )
}
