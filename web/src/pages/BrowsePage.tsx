import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'
import { SECTIONS } from '../lib/categories'

const DEBOUNCE_MS = 200

export function BrowsePage() {
  const [params, setParams] = useSearchParams()
  const initial = params.get('q') ?? ''
  const [query, setQuery] = useState(initial)
  const { hash } = useLocation()

  useEffect(() => {
    if (hash === '#explore') {
      document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [hash])
  const [results, setResults] = useState<SearchResult[]>([])
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({})
  const [error, setError] = useState<string | null>(null)
  const [focused, setFocused] = useState(false)
  const thumbReq = useRef(0)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); return }
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .search(q)
        .then((found) => {
          if (cancelled) return
          setResults(found)
          setError(null)
          const ids = found.map((r) => r.id)
          if (ids.length) {
            const req = ++thumbReq.current
            api.thumbnails(ids).then((t) => {
              if (req === thumbReq.current) setThumbs((prev) => ({ ...prev, ...t }))
            }).catch(() => {})
          }
        })
        .catch((e: Error) => !cancelled && setError(e.message))
    }, DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query])

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setFocused(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setParams(query.trim() ? { q: query.trim() } : {})
  }

  const showDropdown = focused && query.trim().length > 0 && results.length > 0

  return (
    <div className="browse-page">
      <h1 className="browse-title">Search the Collection</h1>
      <div className="browse-search-wrap" ref={wrapRef}>
        <form className="browse-search" onSubmit={submit}>
          <input
            type="search"
            placeholder="Soccer, Invisible Man, mitosis..."
            aria-label="Search topics"
            value={query}
            autoFocus
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setFocused(true)}
          />
          <button type="submit" className="search-go" aria-label="Search">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
        </form>
        {showDropdown && (
          <ul className="search-dropdown" role="listbox">
            {results.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/topic/${encodeURIComponent(r.id)}`}
                  className="search-dropdown-row"
                  onClick={() => setFocused(false)}
                >
                  <div className="search-dropdown-thumb">
                    {thumbs[r.id] ? (
                      <img src={thumbs[r.id]!} alt="" loading="lazy" />
                    ) : (
                      <div className="search-dropdown-thumb-ph" />
                    )}
                  </div>
                  <div className="search-dropdown-info">
                    <strong>{r.name}</strong>{' '}
                    <span className="muted small">
                      {r.category ?? 'Uncategorized'} · asked {r.n_tossups}x
                      {r.matched_alias.toLowerCase() !== r.name.toLowerCase() && ` · "${r.matched_alias}"`}
                    </span>
                    {r.description && <div className="muted small">{r.description}</div>}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      {error && <p className="error">{error}</p>}

      <div id="explore" className="explore-sections">
        {SECTIONS.map((section) => (
          <section key={section.title} className="explore-section">
            <h2 className="explore-section-title">{section.title}</h2>
            <div className="explore-grid">
              {section.cards.map((card) => (
                <Link
                  to={`/explore/${card.slug}`}
                  key={card.slug}
                  className="explore-card"
                >
                  <img src={card.image} alt="" loading="lazy" className="explore-card-img" />
                  <span className="explore-card-label">{card.label}</span>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
