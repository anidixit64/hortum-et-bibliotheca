import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TopicRecord, TopicStats } from '../api/types'
import { ClueList } from '../components/ClueList'
import { Heatmap } from '../components/Heatmap'
import { ConfusionList, RelatedList } from '../components/Related'
import { Timeline } from '../components/Timeline'
import { TopicMap } from '../components/TopicMap'
import { percent } from '../lib/format'

export function TopicPage() {
  const { key = '' } = useParams()
  // Tagged with the key it was loaded for, so a stale record shows as loading.
  const [loaded, setLoaded] = useState<{ key: string; record: TopicRecord } | null>(null)
  const [stats, setStats] = useState<TopicStats | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)

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
  const record = loaded?.key === key ? loaded.record : null
  if (!record) return <p className="muted">Loading…</p>
  const { topic } = record

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

      <section className="card">
        <h2>Clues worth knowing</h2>
        <ClueList clues={record.clues} />
      </section>

      {record.clues.length > 0 && (
        <section className="card">
          <h2>Where the clues come up</h2>
          <Heatmap clues={record.clues} buzzed={stats?.buzzed_clusters ?? {}} />
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
    </>
  )
}
