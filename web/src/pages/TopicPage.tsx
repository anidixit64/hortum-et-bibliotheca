import { Fragment, useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, SectionPayloads, TopicLink, TopicRecord, TopicStats } from '../api/types'
import { ClueList } from '../components/ClueList'
import { Gallery, Reading, Videos, WikiSummary } from '../components/Enrichment'
import { FunFacts, Hook, Summary } from '../components/Written'
import { Heatmap } from '../components/Heatmap'
import { ConfusionList } from '../components/Related'
import { Timeline } from '../components/Timeline'
import { ExhibitTimeline, Feature } from '../components/Special'
import { TopicMap } from '../components/TopicMap'
import { applyCleanup, CLEANED_FROM } from '../lib/cleanClues'
import { extractProperNouns } from '../lib/marks'
import { percent } from '../lib/format'
import { useTopicTheme } from '../lib/theme'
import { HeaderImage } from '../components/HeaderImage'
import { useTopicContent } from '../lib/useTopicContent'

const PAGE = 10 // clues shown at first
const MORE = 5 // added by each "show more"

export function TopicPage() {
  const { key = '' } = useParams()
  // Tagged with the key it was loaded for, so a stale record shows as loading.
  const [loaded, setLoaded] = useState<{ key: string; record: TopicRecord } | null>(null)
  const [stats, setStats] = useState<TopicStats | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)
  // Raw clue records past the first page, and how many clues to show; both tagged with
  // the topic they belong to.
  const [more, setMore] = useState<{ key: string; clues: Clue[] }>({ key: '', clues: [] })
  const [visible, setVisible] = useState<{ key: string; n: number }>({ key: '', n: PAGE })
  const [loadingMore, setLoadingMore] = useState(false)
  const current = loaded?.key === key ? loaded.record : null
  const [content, refreshContent] = useTopicContent(current?.topic.id ?? '')
  const summarySection = content?.sections.summary
  const written =
    summarySection?.status === 'ok' ? (summarySection.payload as SectionPayloads['summary']) : null
  const explainedSection = content?.sections.explanations
  const explanations =
    explainedSection?.status === 'ok'
      ? (explainedSection.payload as SectionPayloads['explanations']).clues
      : []
  const factsSection = content?.sections.facts
  const specialSection = content?.sections.special
  const special =
    specialSection?.status === 'ok' ? (specialSection.payload as SectionPayloads['special']) : null
  const facts = factsSection?.status === 'ok' ? (factsSection.payload as SectionPayloads['facts']) : null
  const themeSection = content?.sections.theme
  const topicTheme = themeSection?.status === 'ok' ? (themeSection.payload as SectionPayloads['theme']) : null
  useTopicTheme(topicTheme)
  const cleanedSection = content?.sections.clues
  const cleaned =
    cleanedSection?.status === 'ok'
      ? (cleanedSection.payload as SectionPayloads['clues']).clues
      : null

  // Topic links: proper nouns in the summary + clue labels that are themselves topics.
  const [topicLinks, setTopicLinks] = useState<Record<string, TopicLink>>({})
  const topicId = current?.topic.id
  useEffect(() => {
    if (!topicId) return
    // Collect names to look up: clue labels + proper nouns from the summary text.
    const names: string[] = []
    if (cleaned) names.push(...cleaned.map((c) => c.label))
    if (written) names.push(...extractProperNouns(written.summary))
    if (!names.length) return
    const unique = [...new Set(names)]
    api
      .topicLinks(unique, topicId)
      .then(setTopicLinks)
      .catch(() => setTopicLinks({}))
  }, [topicId, written?.summary, cleaned?.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // The cleanup was made from the top 25 raw clues: load the ones past the first page.
  const needRaw = cleaned !== null && current !== null && more.key !== key
  useEffect(() => {
    if (!needRaw || !current) return
    api
      .moreClues(current.topic.id, current.clues.length, CLEANED_FROM - current.clues.length)
      .then((clues) => setMore({ key, clues }))
      .catch(() => setMore({ key, clues: [] }))
  }, [needRaw, current, key])

  const loadStats = useCallback((id: string) => {
    api.topicStats(id).then(setStats).catch(() => setStats(null)) // study may be offline
  }, [])

  useEffect(() => {
    api
      .topic(key)
      .then((r) => {
        setLoaded({ key, record: r })
        document.title = `${r.topic.name} · Hortum et Bibliotheca`
        loadStats(r.topic.id)
      })
      .catch((e: Error) => setError({ key, message: e.message }))
  }, [key, loadStats])

  if (error?.key === key) return <p className="error">{error.message}</p>
  const record = current
  if (!record) return <p className="muted">Loading…</p>
  const { topic } = record

  const extra = more.key === key ? more.clues : []
  const raw = [...record.clues, ...extra]
  const rawTotal = record.n_clues ?? record.clues.length
  // With a cleanup: its clues, then raw ones it didn't look at (ranked past CLEANED_FROM).
  const list = cleaned
    ? [...applyCleanup(raw, cleaned), ...raw.filter((c) => c.rank > CLEANED_FROM)]
    : raw
  const total = cleaned ? cleaned.length + Math.max(0, rawTotal - CLEANED_FROM) : rawTotal
  const n = visible.key === key ? visible.n : PAGE
  const shown = list.slice(0, n)
  const showMore = async () => {
    if (n + MORE > list.length && raw.length < rawTotal) {
      setLoadingMore(true)
      try {
        const next = await api.moreClues(topic.id, raw.length, n + MORE - list.length)
        setMore({ key, clues: [...extra, ...next] })
      } finally {
        setLoadingMore(false)
      }
    }
    setVisible({ key, n: n + MORE })
    // Newly shown cleaned clues get their explanations written (only the missing ones).
    const through = Math.min(n + MORE, cleaned?.length ?? 0)
    if (cleaned && through > explanations.length) {
      api
        .explainMore(topic.id, through)
        .then(refreshContent)
        .catch(() => {}) // content service offline: the clues still show
    }
  }

  const toggleFollow = async () => {
    setBusy(true)
    try {
      if (stats?.followed) await api.unfollow(topic.id)
      else await api.follow(topic.id)
      loadStats(topic.id)
    } finally {
      setBusy(false)
    }
  }

  // AI sections still being written (the page polls until they arrive).
  const WRITING: [keyof SectionPayloads, string][] = [
    ['summary', 'summary'], ['theme', 'colors'], ['explanations', 'clue explanations'],
    ['facts', 'fun facts'], ['special', 'special sections'],
  ]
  const isWriting = (kind: keyof SectionPayloads) => {
    const s = content?.sections[kind]
    return !!s && (s.status === 'pending' || !!s.stale)
  }
  const writing = WRITING.filter(([kind]) => isWriting(kind)).map(([, name]) => name)

  // The exhibit's rooms, numbered in walking order; a room shows only when it has something.
  const rooms: { id: string; title: string; body: ReactNode }[] = []
  const room = (id: string, title: string, body: ReactNode) => rooms.push({ id, title, body })
  if (content) {
    room('introduction', 'Introduction', written
      ? <Summary summary={written} explanations={explanations} topicLinks={topicLinks} />
      : (
        <>
          {isWriting('summary') && (
            <p className="muted small writing-note">
              The AI summary is being written. Meanwhile, the opening of the Wikipedia article:
            </p>
          )}
          <WikiSummary section={content.sections.wiki} />
        </>
      ))
    room('gallery', 'Gallery', <Gallery section={content.sections.images} />)
  }
  if (special) room('feature', special.feature.form, <Feature special={special} />)
  // The Wikipedia-grounded timeline when it has a few events; else Wikidata's dates, when
  // there are enough of them to be a timeline.
  if (special && special.timeline.events.length >= 3) {
    room('timeline', special.timeline.kind === 'discoveries' ? 'Timeline of discoveries' : 'Timeline',
      <ExhibitTimeline timeline={special.timeline} />)
  } else if (record.timeline.length >= 3) {
    room('timeline', 'Timeline', <Timeline events={record.timeline} />)
  }
  room('clues', 'The clue hall', (
    <>
      {cleaned && (
        <p className="muted small" title="An AI pass merged duplicate spellings, dropped generic terms and fixed labels; counts are recomputed from the questions.">
          Tidied by AI{cleanedSection?.stale ? ' (updating…)' : ''}
        </p>
      )}
      <ClueList clues={shown} explanations={cleaned ? explanations : undefined}
                writing={isWriting('explanations') || isWriting('clues')}
                topicLinks={topicLinks} />
      {shown.length < total && (
        <button onClick={showMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : `Show ${Math.min(MORE, total - shown.length)} more`}
        </button>
      )}
      {shown.length > 0 && (
        <>
          <h3>Where the clues come up</h3>
          <Heatmap clues={shown} buzzed={stats?.buzzed_clusters ?? {}} />
        </>
      )}
    </>
  ))
  room('connections', 'Connections', (
    <>
      {/* Related topics are left out for now: the summary links the topics it names. */}
      <h3>Don't confuse with</h3>
      <ConfusionList confusions={record.confusions} />
      {record.map.length > 0 && (
        <>
          <h3>Map</h3>
          <TopicMap points={record.map} />
        </>
      )}
    </>
  ))
  if (content) {
    room('screening', 'Screening room', <Videos section={content.sections.videos} />)
    room('library', 'Library', <Reading section={content.sections.books} />)
  }
  const plaquesAfter = rooms.findIndex((r) => r.id === 'gallery')

  return (
    <>
      {topicTheme?.header && <HeaderImage image={topicTheme.header} />}
      <header className="card entrance">
        <div className="topic-head">
          <div>
            <p className="exhibit-kicker">{topic.category ?? 'Exhibit'}</p>
            <h1 className="exhibit-sign">{topic.name}</h1>
            {written && <Hook summary={written} />}
            {writing.length > 0 && (
              <p className="writing-banner" role="status">
                <span className="spinner" aria-hidden /> Writing this exhibit: {writing.join(', ')}. The
                page fills in as each part is ready (a few minutes the first time anyone opens a topic).
              </p>
            )}
            {topic.description && <p className="muted">{topic.description}</p>}
            {topic.thin && <span className="pill">rarely asked</span>}
          </div>
          <div className="topic-actions">
            <Link to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
              <button>Practice</button>
            </Link>
            <button className="primary" onClick={toggleFollow} disabled={busy || stats === null}>
              {stats?.followed ? 'Following ✓' : 'Follow'}
            </button>
          </div>
        </div>
        <div className="stats-row">
          <div><strong>{topic.stats.n_tossups}</strong><span className="muted small">questions</span></div>
          <div><strong>{topic.stats.n_sets}</strong><span className="muted small">sets</span></div>
          <div>
            <strong>{topic.stats.years[0] ?? '?'}–{topic.stats.years[1] ?? '?'}</strong>
            <span className="muted small">years asked</span>
          </div>
          {stats && stats.buzzing.buzzes > 0 && (
            <div><strong>{percent(stats.buzzing.accuracy)}</strong><span className="muted small">your accuracy</span></div>
          )}
          {stats?.followed && (
            <div><strong>{stats.due}</strong><span className="muted small">cards due</span></div>
          )}
        </div>
        {topic.aliases.length > 0 && (
          <p className="muted small">Also: {topic.aliases.join(' · ')}</p>
        )}
        <nav className="floor-plan" aria-label="Rooms">
          {rooms.map((r, i) => (
            <a key={r.id} href={`#room-${r.id}`}>
              <span className="room-number">{i + 1}</span>
              {r.title}
            </a>
          ))}
        </nav>
      </header>

      {rooms.map((r, i) => (
        <Fragment key={r.id}>
          <section className="card room" id={`room-${r.id}`}>
            <h2>
              <span className="room-number">{i + 1}</span>
              {r.title}
            </h2>
            {r.body}
          </section>
          {i === plaquesAfter && facts && facts.facts.length > 0 && (
            <aside className="plaque-row" aria-label="Did you know?">
              <h2>Did you know?</h2>
              <FunFacts facts={facts.facts} source={facts.source} />
            </aside>
          )}
        </Fragment>
      ))}

      <section className="card exit">
        <h2>Test yourself</h2>
        <p className="muted">
          Buzz on real questions about {topic.name}, or follow it to get flashcards for the clues you miss.
        </p>
        <div className="controls">
          <Link to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
            <button className="primary">Practice</button>
          </Link>
          <button onClick={toggleFollow} disabled={busy || stats === null}>
            {stats?.followed ? 'Following ✓' : 'Follow'}
          </button>
        </div>
      </section>
    </>
  )
}
