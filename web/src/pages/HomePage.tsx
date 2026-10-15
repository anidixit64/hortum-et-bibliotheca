import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'
import { PALETTES, readPalette, savePalette, applyPalette } from '../lib/palette'

const DEBOUNCE_MS = 200
const NODE_RADIUS = 160

/** One wedge per palette, centered on its swatch, using the two colors that name it. */
function wheelGradient() {
  const n = PALETTES.length
  const slice = 100 / n
  const stops = PALETTES.map((p, i) => {
    const start = i * slice
    const mid = start + slice / 2
    const end = (i + 1) * slice
    return `${p.light.accent} ${start}% ${mid}%, ${p.light.accent2} ${mid}% ${end}%`
  }).join(', ')
  return `conic-gradient(from ${-90 - 180 / n}deg, ${stops})`
}

/** Gray wedges, so the colored swatches read against the open wheel. */
function monoWheelGradient() {
  const tones = ['#d5d5d5', '#8d8d8d', '#efefef', '#6e6e6e', '#c4c4c4', '#9a9a9a', '#e2e2e2', '#7a7a7a']
  const n = PALETTES.length
  const slice = 100 / n
  const stops = PALETTES.map((_, i) => {
    const start = i * slice
    const mid = start + slice / 2
    const end = (i + 1) * slice
    const light = tones[i % tones.length]
    const dark = tones[(i + 3) % tones.length]
    return `${light} ${start}% ${mid}%, ${dark} ${mid}% ${end}%`
  }).join(', ')
  return `conic-gradient(from ${-90 - 180 / n}deg, ${stops})`
}

function paletteRing(p: (typeof PALETTES)[number]) {
  return `conic-gradient(from -24deg, ${p.light.accent}, ${p.light.accent2}, ${p.dark.accent}, ${p.light.accentSoft}, ${p.light.accent})`
}

function swatchGradient(p: (typeof PALETTES)[number]) {
  const colors = [p.light.accent, p.light.accent2, p.dark.accent, p.light.accentSoft]
  const stops = colors
    .map((c, j) => `${c} ${(j / colors.length) * 100}% ${((j + 1) / colors.length) * 100}%`)
    .join(', ')
  return `conic-gradient(from 0deg, ${stops})`
}

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
  const [wheelOpen, setWheelOpen] = useState(false)
  const [hovered, setHovered] = useState<number | null>(null)
  const choosePalette = (i: number) => {
    setPaletteIdx(i)
    savePalette(i)
    applyPalette(i)
    setWheelOpen(false)
  }

  const showDropdown = focused && query.trim().length > 0 && results.length > 0

  const previewIdx = hovered ?? palette
  const preview = PALETTES[previewIdx]
  const previewColors = preview.dark

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

      {wheelOpen && <div className="palette-backdrop" />}

      {/* Footer: trigger + wheel live in one container for seamless hover */}
      <div
        className="palette-footer"
        onMouseEnter={() => setWheelOpen(true)}
        onMouseLeave={() => { setWheelOpen(false); setHovered(null) }}
      >
        <div className="palette-trigger" aria-label="Pick colors">
          <span className="palette-trigger-ring" style={{ background: wheelGradient() }} />
          <span className="palette-trigger-label">pick colors</span>
        </div>

        {/* Wheel — floats above the trigger */}
        {wheelOpen && (
          <div className="palette-wheel">
            <div className="palette-wheel-ring" style={{ background: monoWheelGradient() }} />
            <div
              className={`palette-wheel-ring palette-wheel-ring-color${hovered !== null ? ' on' : ''}`}
              style={{ background: hovered !== null ? paletteRing(PALETTES[hovered]) : undefined }}
            />

            <div className="palette-wheel-center" style={{ background: previewColors.bg }}>
              <span className="palette-center-title" style={{ color: previewColors.accent }}>
                Museo
              </span>
              <span className="palette-center-mood" style={{ color: previewColors.muted }}>
                {preview.mood}
              </span>
              {hovered === null && (
                <span className="palette-center-hint" style={{ color: previewColors.muted }}>
                  hover a swatch to preview
                </span>
              )}
              {hovered !== null && (
                <span className="palette-center-name" style={{ color: previewColors.text }}>
                  {preview.name}
                </span>
              )}
            </div>

            {PALETTES.map((p, i) => {
              const angle = (2 * Math.PI * i) / PALETTES.length - Math.PI / 2
              const x = Math.cos(angle) * NODE_RADIUS
              const y = Math.sin(angle) * NODE_RADIUS
              const isActive = palette === i
              const isHov = hovered === i
              return (
                <button
                  key={p.name}
                  className={`palette-node${isActive ? ' active' : ''}${isHov ? ' hovered' : ''}`}
                  style={{ transform: `translate(${x}px, ${y}px)${isHov ? ' scale(1.2)' : ''}` }}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => choosePalette(i)}
                  aria-label={`${p.name} theme`}
                >
                  <span
                    className="palette-node-fill"
                    style={{ background: swatchGradient(p) }}
                  />
                  {isActive && (
                    <span className="palette-node-check">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
