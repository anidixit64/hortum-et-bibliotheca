import React, { Fragment, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Explanation, FunFact, TopicLink, WrittenSummary } from '../api/types'
import { linkClues, parseMarks, type Piece } from '../lib/marks'

/** A clue named in the text: bold; hover or tap shows its one-line summary and a link to
 *  its full explanation further down. */
export function ClueMention({ text, rank, line }: { text: string; rank: number; line?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  const [style, setStyle] = useState<React.CSSProperties>({})

  const show = () => {
    setOpen(true)
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect()
      setStyle({ top: rect.bottom + 4, left: Math.max(8, Math.min(rect.left, window.innerWidth - 340)) })
    }
  }

  return (
    <span
      className="mention"
      ref={ref}
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
    >
      <button type="button" className="mention-text" onClick={() => { if (open) setOpen(false); else show() }} aria-expanded={open}>
        {text}
      </button>
      {open && (
        <span className="popover" role="tooltip" style={style}>
          {line && <span className="popover-line">{line}</span>}
          <a href={`#clue-${rank}`} onClick={() => setOpen(false)}>See more</a>
        </span>
      )}
    </span>
  )
}

/** Render a plain-text span, linking any proper nouns that are themselves topics. */
function LinkedText({ text, links }: { text: string; links: Record<string, TopicLink> }) {
  const keys = Object.keys(links)
  if (!keys.length) return <>{text}</>
  const sorted = keys.sort((a, b) => b.length - a.length)
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(`\\b(${sorted.map(esc).join('|')})\\b`, 'gi')
  const byLower = new Map(keys.map((k) => [k.toLowerCase(), links[k]]))
  const out: { text: string; link?: TopicLink }[] = []
  let at = 0
  for (const m of text.matchAll(pattern)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    const link = byLower.get(m[0].toLowerCase())
    out.push({ text: m[0], link })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return (
    <>
      {out.map((part, i) =>
        part.link ? (
          <Link key={i} to={`/topic/${encodeURIComponent(part.link.id)}`} className="topic-link">
            {part.text}
          </Link>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  )
}

function Pieces({ pieces, lines, topicLinks = {} }: { pieces: Piece[]; lines: Map<number, string>; topicLinks?: Record<string, TopicLink> }) {
  return (
    <>
      {pieces.map((p, i) =>
        p.rank === undefined ? (
          <LinkedText key={i} text={p.text} links={topicLinks} />
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
  topicLinks = {},
  secondImage,
  thirdImage,
}: {
  summary: WrittenSummary
  explanations: Explanation[]
  topicLinks?: Record<string, TopicLink>
  secondImage?: ReactNode
  thirdImage?: ReactNode
}) {
  const lines = new Map(explanations.map((e) => [e.rank, e.one_line]))
  const paragraphs = summary.summary.split(/\n\s*\n/)
  return (
    <>
      {paragraphs.map((para, i) => (
        <Fragment key={i}>
          {i === 2 && secondImage}
          {i === 4 && thirdImage}
          <p className="prose">
            <Pieces pieces={parseMarks(para)} lines={lines} topicLinks={topicLinks} />
          </p>
        </Fragment>
      ))}
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
export function FunFacts({ facts, ornament }: { facts: FunFact[]; ornament?: ReactNode }) {
  if (!facts.length) return null
  return (
    <div className="plaques">
      {ornament}
      {facts.map((f) => (
        <figure key={f.fact} className="plaque">
          <span className="plaque-mark" aria-hidden="true">{'?'}</span>
          {f.kind === 'clue' && f.clue_label && (
            <span className="plaque-clue-label">{f.clue_label}</span>
          )}
          <p>{f.fact}</p>
        </figure>
      ))}
    </div>
  )
}
