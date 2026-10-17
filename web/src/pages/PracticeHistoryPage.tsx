import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { PracticeHistory } from '../api/types'
import { DIFFICULTY_LABELS, difficultyLabel } from '../lib/format'


function pct(n: number | null): string {
  if (n === null) return '—'
  return `${(n * 100).toFixed(0)}%`
}

function posLabel(pos: number | null): string {
  if (pos === null) return '—'
  if (pos < 0.33) return 'Early'
  if (pos < 0.66) return 'Mid'
  return 'Late'
}

function wikiUrl(topicId: string): string {
  return `https://en.wikipedia.org/wiki/Special:Search?search=${encodeURIComponent(topicId)}`
}

export function PracticeHistoryPage() {
  const [data, setData] = useState<PracticeHistory | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.practiceHistory()
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="history-page"><p className="error">{error}</p></div>
  if (!data) return <div className="history-page"><p className="muted">Loading history...</p></div>

  return (
    <div className="history-page">
      <div className="history-header">
        <Link to="/practice" className="explore-back">&larr; Practice</Link>
        <h1 className="history-title">Practice History</h1>
      </div>

      <div className="history-overview">
        <div className="history-stat-card">
          <span className="history-stat-value">{data.total_buzzes}</span>
          <span className="history-stat-label">Total Buzzes</span>
        </div>
        <div className="history-stat-card">
          <span className="history-stat-value result-correct">{data.total_correct}</span>
          <span className="history-stat-label">Correct</span>
        </div>
        <div className="history-stat-card">
          <span className="history-stat-value result-incorrect">{data.total_incorrect}</span>
          <span className="history-stat-label">Incorrect</span>
        </div>
        <div className="history-stat-card">
          <span className="history-stat-value">{data.total_no_buzz}</span>
          <span className="history-stat-label">No Buzz</span>
        </div>
        <div className="history-stat-card">
          <span className="history-stat-value">{pct(data.overall.accuracy)}</span>
          <span className="history-stat-label">Accuracy</span>
        </div>
        <div className="history-stat-card">
          <span className="history-stat-value">{pct(data.overall.power_rate)}</span>
          <span className="history-stat-label">Power Rate</span>
        </div>
      </div>

      {data.by_category.length > 0 && (
        <section className="history-section">
          <h2 className="history-section-title">By Category</h2>
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Subcategory</th>
                  <th>Buzzes</th>
                  <th>Correct</th>
                  <th>Incorrect</th>
                  <th>Accuracy</th>
                  <th>Power</th>
                </tr>
              </thead>
              <tbody>
                {data.by_category.map((c, i) => (
                  <tr key={i}>
                    <td>{c.category}</td>
                    <td className="muted">{c.subcategory ?? '—'}</td>
                    <td>{c.buzzes}</td>
                    <td className="result-correct">{c.correct}</td>
                    <td className="result-incorrect">{c.incorrect}</td>
                    <td>{pct(c.accuracy)}</td>
                    <td>{pct(c.power_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {data.by_difficulty.length > 0 && (
        <section className="history-section">
          <h2 className="history-section-title">By Difficulty</h2>
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Difficulty</th>
                  <th>Buzzes</th>
                  <th>Correct</th>
                  <th>Incorrect</th>
                  <th>Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {data.by_difficulty.map((d) => (
                  <tr key={d.difficulty}>
                    <td>{DIFFICULTY_LABELS[d.difficulty] ?? d.difficulty}</td>
                    <td>{d.buzzes}</td>
                    <td className="result-correct">{d.correct}</td>
                    <td className="result-incorrect">{d.incorrect}</td>
                    <td>{pct(d.accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {data.struggled_topics.length > 0 && (
        <section className="history-section">
          <h2 className="history-section-title">Struggled Topics</h2>
          <p className="muted small">Topics you missed 2+ times</p>
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Topic</th>
                  <th>Buzzes</th>
                  <th>Correct</th>
                  <th>Incorrect</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.struggled_topics.map((t) => (
                  <tr key={t.topic_id}>
                    <td>
                      <Link to={`/topic/${encodeURIComponent(t.topic_id)}`}>{t.answer}</Link>
                    </td>
                    <td>{t.buzzes}</td>
                    <td className="result-correct">{t.correct}</td>
                    <td className="result-incorrect">{t.incorrect}</td>
                    <td>
                      <a href={wikiUrl(t.answer)} target="_blank" rel="noopener noreferrer" className="history-wiki-link">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {data.recent.length > 0 && (
        <section className="history-section">
          <h2 className="history-section-title">Recent Questions</h2>
          <ol className="history-recent">
            {data.recent.map((r) => (
              <li key={r.buzz_id} className="history-recent-item">
                <div className="history-recent-header">
                  <span className={`result-${r.result === 'no_buzz' ? 'incorrect' : r.result}`}>
                    {r.result === 'correct' ? 'Correct' : r.result === 'no_buzz' ? 'No buzz' : 'Incorrect'}
                  </span>
                  {r.in_power && r.result === 'correct' && <span className="practice-power-tag">Power</span>}
                  <span className="muted small">
                    {r.category ?? ''}{r.subcategory ? ` · ${r.subcategory}` : ''}
                    {r.difficulty !== null ? ` · ${difficultyLabel(r.difficulty)}` : ''}
                  </span>
                </div>
                <div className="history-recent-body">
                  <strong>{r.answer ?? 'Unknown'}</strong>
                  {r.position !== null && (
                    <span className="muted small"> · Buzzed {posLabel(r.position)} ({(r.position * 100).toFixed(0)}%)</span>
                  )}
                  {r.answer_given && r.result !== 'correct' && (
                    <span className="muted small"> · You said: &ldquo;{r.answer_given}&rdquo;</span>
                  )}
                </div>
                <div className="history-recent-links">
                  {r.topic_id && (
                    <Link to={`/topic/${encodeURIComponent(r.topic_id)}`} className="history-link-btn">
                      View topic
                    </Link>
                  )}
                  {r.answer && (
                    <a href={wikiUrl(r.answer)} target="_blank" rel="noopener noreferrer" className="history-link-btn">
                      Wikipedia
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}
