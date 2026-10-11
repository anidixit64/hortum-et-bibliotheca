import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, SectionPayloads, TopicRecord, TopicStats } from '../api/types'
import { ClueList } from '../components/ClueList'
import { Gallery, Reading, Videos, WikiSummary } from '../components/Enrichment'
import { Hook, Summary } from '../components/Written'
import { Heatmap } from '../components/Heatmap'
import { ConfusionList, RelatedList } from '../components/Related'
import { Timeline } from '../components/Timeline'
import { TopicMap } from '../components/TopicMap'
import { applyCleanup, CLEANED_FROM } from '../lib/cleanClues'
import { percent } from '../lib/format'
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
  const content = useTopicContent(current?.topic.id ?? '')
  const summarySection = content?.sections.summary
  const written =
    summarySection?.status === 'ok' ? (summarySection.payload as SectionPayloads['summary']) : null
  const explainedSection = content?.sections.explanations
  const explanations =
    explainedSection?.status === 'ok'
      ? (explainedSection.payload as SectionPayloads['explanations']).clues
      : []
  const cleanedSection = content?.sections.clues
  const cleaned =
    cleanedSection?.status === 'ok'
      ? (cleanedSection.payload as SectionPayloads['clues']).clues
      : null

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

  return (
    <>
      <div className="card">
        <div className="topic-head">
          <div>
            <h1>{topic.name}</h1>
            {written && <Hook summary={written} />}
            {topic.description && <p className="muted">{topic.description}</p>}
            {topic.thin && <span className="pill">rarely asked</span>}
            {topic.category && <span className="pill">{topic.category}</span>}
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
      </div>

      {content && (
        <section className="card">
          <h2>About</h2>
          {written ? (
            <Summary summary={written} explanations={explanations} />
          ) : (
            <WikiSummary section={content.sections.wiki} />
          )}
        </section>
      )}

      <section className="card">
        <h2>Clues worth knowing</h2>
        {cleaned && (
          <p className="muted small" title="An AI pass merged duplicate spellings, dropped generic terms and fixed labels; counts are recomputed from the questions.">
            Tidied by AI{cleanedSection?.stale ? ' (updating…)' : ''}
          </p>
        )}
        <ClueList clues={shown} explanations={cleaned ? explanations : undefined} />
        {shown.length < total && (
          <button onClick={showMore} disabled={loadingMore}>
            {loadingMore ? 'Loading…' : `Show ${Math.min(MORE, total - shown.length)} more`}
          </button>
        )}
      </section>

      {shown.length > 0 && (
        <section className="card">
          <h2>Where the clues come up</h2>
          <Heatmap clues={shown} buzzed={stats?.buzzed_clusters ?? {}} />
        </section>
      )}

      <div className="grid-2">
        <section className="card">
          <h2>Related</h2>
          <RelatedList related={record.related} />
        </section>
        <section className="card">
          <h2>Don't confuse with</h2>
          <ConfusionList confusions={record.confusions} />
        </section>
      </div>

      <section className="card">
        <h2>Timeline</h2>
        <Timeline events={record.timeline} />
      </section>
      <section className="card">
        <h2>Map</h2>
        <TopicMap points={record.map} />
      </section>

      {content && (
        <>
          <section className="card">
            <h2>Images</h2>
            <Gallery section={content.sections.images} />
          </section>
          <section className="card">
            <h2>Further reading</h2>
            <Reading section={content.sections.books} />
          </section>
          <section className="card">
            <h2>Videos</h2>
            <Videos section={content.sections.videos} />
          </section>
        </>
      )}
    </>
  )
}
