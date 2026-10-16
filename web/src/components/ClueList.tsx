import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, Explanation, TopicLink, WikiImage } from '../api/types'
import type { WikiNote } from '../lib/wikiNote'
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

export type SortMode = 'frequency' | 'rarity' | 'position'
export type SortDir = 'asc' | 'desc'

export function defaultDir(mode: SortMode): SortDir {
  return mode === 'frequency' ? 'desc' : 'asc'
}

function appearances(clue: Clue) {
  return clue.n_questions ?? clue.n_tossups
}

function averagePosition(clue: Clue) {
  return clue.mean_position ?? clue.median_position
}

export function dominantCategory(clue: Clue): string | null {
  const cats = clue.categories
  if (!cats) return null
  let best: string | null = null
  let max = 0
  for (const [cat, n] of Object.entries(cats)) {
    if (n > max) { best = cat; max = n }
  }
  return best
}

function categoryList(clues: Clue[]): string[] {
  const counts = new Map<string, number>()
  for (const clue of clues) {
    const cat = dominantCategory(clue)
    if (cat) counts.set(cat, (counts.get(cat) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k)
}

export function sortedClues(
  clues: Clue[],
  mode: SortMode,
  category: string | null,
  dir: SortDir = defaultDir(mode),
): Clue[] {
  const list = category ? clues.filter((c) => dominantCategory(c) === category) : [...clues]
  const sign = dir === 'asc' ? 1 : -1
  const value = (clue: Clue) => (mode === 'position' ? averagePosition(clue) : appearances(clue))
  return list.sort((a, b) => sign * (value(a) - value(b)) || a.rank - b.rank)
}

export function ClueCarousel({
  clues,
  explanations,
  writing = false,
  topicLinks = {},
  topicName,
  topicId,
  images = [],
  sortMode: sortModeProp,
  onSortMode,
  sortDir: sortDirProp,
  onSortDir,
  ornament,
  articleNotes,
  wikiLoaded = false,
}: {
  clues: Clue[]
  explanations?: Explanation[]
  writing?: boolean
  topicLinks?: Record<string, TopicLink>
  topicName: string
  topicId: string
  images?: WikiImage[]
  /** When set, `clues` are already in this order and the buttons report changes upward. */
  sortMode?: SortMode
  onSortMode?: (mode: SortMode) => void
  sortDir?: SortDir
  onSortDir?: (dir: SortDir) => void
  /** A gallery photo set into the open part of the slide. */
  ornament?: WikiImage | null
  articleNotes?: Record<number, WikiNote | null>
  wikiLoaded?: boolean
}) {
  const [index, setIndex] = useState(0)
  const [flashMsg, setFlashMsg] = useState<string | null>(null)
  const [ownSort, setOwnSort] = useState<SortMode>('frequency')
  const [ownDir, setOwnDir] = useState<SortDir>('desc')
  const sortMode = sortModeProp ?? ownSort
  const sortDir = sortDirProp ?? ownDir
  const [category, setCategory] = useState<string | null>(null)

  const byRank = new Map((explanations ?? []).map((e) => [e.rank, e]))
  const lines = new Map((explanations ?? []).map((e) => [e.rank, e.one_line]))
  const names = clues.map((c) => ({ rank: c.rank, names: [c.label, ...(c.variants ?? [])] }))
  const categories = useMemo(() => categoryList(clues), [clues])

  const sorted = useMemo(() => {
    const ordered = onSortMode ? clues : sortedClues(clues, sortMode, category, sortDir)
    if (onSortMode && category) return ordered.filter((c) => dominantCategory(c) === category)
    return ordered
  }, [clues, sortMode, category, sortDir, onSortMode])
  const clueImages = useMemo(() => matchClueImages(clues, images), [clues, images])

  if (!clues.length) return <p className="muted">Not asked often enough to rank clues yet.</p>

  const safeIndex = Math.min(index, sorted.length - 1)
  const clue = sorted[safeIndex]
  const explanation = byRank.get(clue.rank)
  const clueImage = clueImages.get(clue.rank)
  const allLines = [clue.text, ...clue.examples]
  const currentCategory = dominantCategory(clue)

  const go = (dir: -1 | 1) => {
    setIndex((i) => Math.max(0, Math.min(sorted.length - 1, i + dir)))
    setFlashMsg(null)
  }

  const changeSort = (mode: SortMode) => {
    const dir = defaultDir(mode)
    if (onSortMode) onSortMode(mode)
    else setOwnSort(mode)
    if (onSortDir) onSortDir(dir)
    else setOwnDir(dir)
    setIndex(0)
    setFlashMsg(null)
  }

  const changeDir = () => {
    const dir: SortDir = sortDir === 'asc' ? 'desc' : 'asc'
    if (onSortDir) onSortDir(dir)
    else setOwnDir(dir)
    setIndex(0)
    setFlashMsg(null)
  }

  const changeCategory = (next: string | null) => {
    setCategory(next)
    setIndex(0)
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
      <div className="clue-sort" role="group" aria-label="Sort clues by">
        <button className={`pill-btn${sortMode === 'frequency' ? ' active' : ''}`}
          onClick={() => changeSort('frequency')}>Frequency</button>
        <button className={`pill-btn${sortMode === 'rarity' ? ' active' : ''}`}
          onClick={() => changeSort('rarity')}>Rarity</button>
        <button className={`pill-btn${sortMode === 'position' ? ' active' : ''}`}
          onClick={() => changeSort('position')}>Position</button>
        <button type="button" onClick={changeDir}>
          {sortDir === 'asc' ? 'Ascending' : 'Descending'}
        </button>
      </div>
      {categories.length > 1 && (
        <div className="clue-categories" role="group" aria-label="Filter clues by category">
          <span className="clue-categories-label">Category</span>
          <button className={`cat-chip${category === null ? ' active' : ''}`}
            onClick={() => changeCategory(null)}>All</button>
          {categories.map((cat) => (
            <button key={cat} className={`cat-chip${category === cat ? ' active' : ''}`}
              onClick={() => changeCategory(cat)}>{cat}</button>
          ))}
        </div>
      )}

      <div className="clue-slide" key={clue.cluster_id}>
        {ornament && !clueImage && (
          <figure className="artifact float-image float-left">
            <img src={ornament.url} alt={ornament.caption ?? ornament.file} loading="lazy" />
            {ornament.caption && <figcaption className="muted small">{ornament.caption}</figcaption>}
          </figure>
        )}
        {clueImage && (
          <figure className="float-image float-right clue-img">
            <img src={clueImage.url} alt={clueImage.caption ?? ''} loading="lazy" />
            {clueImage.caption && <figcaption className="muted small">{clueImage.caption}</figcaption>}
          </figure>
        )}

        <p className="clue-slide-rank muted small">
          Clue {safeIndex + 1} of {sorted.length}
          {category && <span className="clue-category-badge">{currentCategory}</span>}
        </p>
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
        ) : articleNotes?.[clue.rank] ? (
          <>
            <p className="one-line">{articleNotes[clue.rank]!.sentence}</p>
            <p className="muted small">
              From Wikipedia{articleNotes[clue.rank]!.heading ? `: ${articleNotes[clue.rank]!.heading}` : ''}
            </p>
            <p className="clue-text muted small">As asked: {clue.text}</p>
          </>
        ) : wikiLoaded ? (
          <>
            <p className="muted">The article excerpt does not cover this clue.</p>
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
          {safeIndex + 1} of {sorted.length}
        </span>
        <button onClick={() => go(1)} disabled={safeIndex === sorted.length - 1} aria-label="Next clue">
          →
        </button>
      </nav>
    </div>
  )
}
