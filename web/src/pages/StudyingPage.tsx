import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { FollowedTopic, Stats } from '../api/types'
import { percent } from '../lib/format'

export function StudyingPage() {
  const [topics, setTopics] = useState<FollowedTopic[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.followed(), api.stats()])
      .then(([t, s]) => (setTopics(t), setStats(s)))
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!topics || !stats) return <p className="muted">Loading…</p>
  return (
    <>
      <div className="card">
        <h2>Your progress</h2>
        <div className="stats-row">
          <div><strong>{stats.followed_topics}</strong><span className="muted small">topics</span></div>
          <div><strong>{stats.cards}</strong><span className="muted small">cards</span></div>
          <div><strong>{stats.due}</strong><span className="muted small">due now</span></div>
          <div><strong>{stats.reviews_today}</strong><span className="muted small">reviewed today</span></div>
          <div><strong>{percent(stats.buzzing.accuracy)}</strong><span className="muted small">buzz accuracy</span></div>
          <div><strong>{percent(stats.buzzing.median_correct_position)}</strong><span className="muted small">median correct buzz</span></div>
        </div>
      </div>
      <div className="card">
        <h2>Following</h2>
        {topics.length === 0 ? (
          <p className="muted">You aren't following any topics yet.</p>
        ) : (
          <ul className="results">
            {topics.map((t) => (
              <li key={t.topic_id}>
                <Link to={`/topic/${encodeURIComponent(t.topic_id)}`}>
                  <strong>{t.name}</strong>{' '}
                  <span className="muted small">{t.cards} cards · {t.due} due</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}
