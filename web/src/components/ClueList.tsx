import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, Explanation, TopicLink, WikiImage } from '../api/types'
import { ExplanationText } from './Written'
import { percent } from '../lib/format'

const TREND = { rising: '↑ rising', steady: '→ steady', fading: '↓ fading' } as const

export function ClueList({
  clues,
  explanations,
  writing = false,
  topicLinks = {},
}: {
  clues: Clue[]
  explanations?: Explanation[]
  writing?: boolean
  topicLinks?: Record<string, TopicLink>
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
            <span className="clue-label">
              {clue.rank}.{' '}
              {topicLinks[clue.label] ? (
                <Link to={`/topic/${encodeURIComponent(topicLinks[clue.label].id)}`} className="topic-link">
                  {clue.label}
                </Link>
              ) : clue.label}
            </span>{' '}
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

function matchClueImages(clues: Clue[], images: WikiImage[]): Map<number, WikiImage> {
  const matched = new Map<number, WikiImage>()
  const used = new Set<string>()
  for (const clue of clues) {
    const words = clue.label.toLowerCase().split(/[\s']+/).filter((w) => w.length > 3)
    if (!words.length) continue
    for (const img of images) {
      if (used.has(img.file)) continue
      const hay = `${img.caption ?? ''} ${img.file}`.toLowerCase().replace(/_/g, ' ')
      if (words.some((w) => hay.includes(w))) {
        matched.set(clue.rank, img)
        used.add(img.file)
        break
      }
    }
  }
  return matched
}

export function ClueCarousel({
  clues,
  explanations,
  writing = false,
  topicLinks = {},
  topicName,
  topicId,
  images = [],
}: {
  clues: Clue[]
  explanations?: Explanation[]
  writing?: boolean
  topicLinks?: Record<string, TopicLink>
  topicName: string
  topicId: string
  images?: WikiImage[]
}) {
  const [index, setIndex] = useState(0)
  const [flashMsg, setFlashMsg] = useState<string | null>(null)

  const byRank = new Map((explanations ?? []).map((e) => [e.rank, e]))
  const lines = new Map((explanations ?? []).map((e) => [e.rank, e.one_line]))
  const names = clues.map((c) => ({ rank: c.rank, names: [c.label, ...(c.variants ?? [])] }))

  const clueImages = useMemo(() => matchClueImages(clues, images), [clues, images])

  if (!clues.length) return <p className="muted">Not asked often enough to rank clues yet.</p>

  const safeIndex = Math.min(index, clues.length - 1)
  const clue = clues[safeIndex]
  const explanation = byRank.get(clue.rank)
  const clueImage = clueImages.get(clue.rank)
  const allLines = [clue.text, ...clue.examples]

  const go = (dir: -1 | 1) => {
    setIndex((i) => Math.max(0, Math.min(clues.length - 1, i + dir)))
    setFlashMsg(null)
  }

  const makeFlashcards = async () => {
    try {
      const result = await api.createClueCards(topicId, allLines, topicName, clue.label)
      setFlashMsg(
        result.created > 0
          ? `Added ${result.created} flashcard${result.created > 1 ? 's' : ''}`
          : 'Flashcards already exist',
      )
    } catch {
      setFlashMsg('Could not create flashcards')
    }
  }

  return (
    <div className="clue-carousel">
      <div className="clue-slide" key={clue.cluster_id}>
        {clueImage && (
          <figure className="float-image float-right clue-img">
            <img src={clueImage.url} alt={clueImage.caption ?? ''} loading="lazy" />
            {clueImage.caption && <figcaption className="muted small">{clueImage.caption}</figcaption>}
          </figure>
        )}

        <p className="clue-slide-rank muted small">Clue {clue.rank} of {clues.length}</p>
        <h3 className="clue-slide-title">
          {topicLinks[clue.label] ? (
            <Link to={`/topic/${encodeURIComponent(topicLinks[clue.label].id)}`} className="topic-link">
              {clue.label}
            </Link>
          ) : (
            clue.label
          )}
        </h3>

        <p className="muted small">
          {clue.n_questions ?? clue.n_tossups} questions · {clue.n_sets} sets · usually at{' '}
          {percent(clue.median_position)} of the question · {TREND[clue.heatmap.trend]}
          {clue.heatmap.share_in_power > 0.5 && ' · often in power'}
        </p>

        {explanation ? (
          <>
            <p className="one-line">{explanation.one_line}</p>
            <ExplanationText explanation={explanation} names={names} lines={lines} />
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

        <details className="clue-lines">
          <summary>
            {allLines.length} question wording{allLines.length > 1 ? 's' : ''}
          </summary>
          <ul>
            {allLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </details>

        <div className="clue-actions">
          <button className="small" onClick={makeFlashcards}>
            Add {allLines.length} flashcard{allLines.length > 1 ? 's' : ''}
          </button>
          {flashMsg && <span className="muted small">{flashMsg}</span>}
        </div>
      </div>

      <nav className="clue-nav" aria-label="Clue navigation">
        <button onClick={() => go(-1)} disabled={safeIndex === 0} aria-label="Previous clue">
          ←
        </button>
        <span>
          {safeIndex + 1} of {clues.length}
        </span>
        <button onClick={() => go(1)} disabled={safeIndex === clues.length - 1} aria-label="Next clue">
          →
        </button>
      </nav>
    </div>
  )
}
