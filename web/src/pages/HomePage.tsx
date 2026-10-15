import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'
import { PALETTES, readPalette, savePalette, applyPalette } from '../lib/palette'

const DEBOUNCE_MS = 200

export function HomePage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({})
  const [focused, setFocused] = useState(false)
  const navigate = useNavigate()
  const wrapRef = useRef<HTMLDivElement>(null)
  const thumbReq = useRef(0)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); return }
    let cancelled = false
    const timer = setTimeout(() => {
      api.search(q).then((found) => {
        if (cancelled) return
        setResults(found)
        const ids = found.map((r) => r.id)
        if (ids.length) {
          const req = ++thumbReq.current
          api.thumbnails(ids).then((t) => {
            if (req === thumbReq.current) setThumbs((prev) => ({ ...prev, ...t }))
          }).catch(() => {})
        }
      }).catch(() => {})
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
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    } else {
      navigate('/search')
    }
  }

  const [palette, setPaletteIdx] = useState(readPalette)
  const choosePalette = (i: number) => {
    setPaletteIdx(i)
    savePalette(i)
    applyPalette(i)
  }

  const showDropdown = focused && query.trim().length > 0 && results.length > 0

  return (
    <div className="home">
      <div className="home-center">
        <h1 className="home-title">Museo</h1>
        <p className="home-subtitle">Your exhibit for every quiz bowl answer</p>
        <div className="home-search-wrap" ref={wrapRef}>
          <form className="home-search" onSubmit={submit}>
            <input
              type="search"
              placeholder="Search a topic..."
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
                        {r.category ?? 'Uncategorized'} · {r.n_tossups}x
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="palette-picker">
        {PALETTES.map((p, i) => (
          <button
            key={p.name}
            className={`palette-swatch${palette === i ? ' active' : ''}`}
            onClick={() => choosePalette(i)}
            aria-label={`${p.name} theme`}
            title={p.mood}
          >
            <div className="palette-dots">
              {Object.values(p.dark).slice(0, 5).map((c, j) => (
                <span key={j} className="palette-dot" style={{ background: c }} />
              ))}
            </div>
            <span className="palette-swatch-label">{p.name}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
