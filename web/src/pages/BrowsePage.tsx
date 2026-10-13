import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'

const DEBOUNCE_MS = 200

export function BrowsePage() {
  const [params, setParams] = useSearchParams()
  const initial = params.get('q') ?? ''
  const [query, setQuery] = useState(initial)
  const [results, setResults] = useState<SearchResult[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); return }
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .search(q)
        .then((found) => !cancelled && (setResults(found), setError(null)))
        .catch((e: Error) => !cancelled && setError(e.message))
    }, DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setParams(query.trim() ? { q: query.trim() } : {})
  }

  return (
    <div className="browse-page">
      <h1 className="browse-title">Search the Collection</h1>
      <form className="browse-search" onSubmit={submit}>
        <input
          type="search"
          placeholder="Soccer, Invisible Man, mitosis..."
          aria-label="Search topics"
          value={query}
          autoFocus
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="search-go" aria-label="Search">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {query.trim() && results.length === 0 && !error && (
        <p className="muted browse-empty">No exhibits found. Try another search.</p>
      )}
      <ul className="results browse-results" aria-label="Search results">
        {results.map((r) => (
          <li key={r.id}>
            <Link to={`/topic/${encodeURIComponent(r.id)}`}>
              <strong>{r.name}</strong>{' '}
              <span className="muted small">
                {r.category ?? 'Uncategorized'} · asked {r.n_tossups}x
                {r.matched_alias.toLowerCase() !== r.name.toLowerCase() && ` · "${r.matched_alias}"`}
              </span>
              {r.description && <div className="muted small">{r.description}</div>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
