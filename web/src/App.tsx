import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api/client'
import { PracticePage } from './pages/PracticePage'
import { ReviewPage } from './pages/ReviewPage'
import { HomePage } from './pages/HomePage'
import { BrowsePage } from './pages/BrowsePage'
import { SettingsPage } from './pages/SettingsPage'
import { TopicPage } from './pages/TopicPage'
import { ExplorePage } from './pages/ExplorePage'
import { PracticeHistoryPage } from './pages/PracticeHistoryPage'
import { AiModeProvider, useAiMode, useSetAiMode } from './lib/aiMode'
import { applyPalette, readPalette } from './lib/palette'
import { applyMode, onModeChange, readMode, saveMode } from './lib/colorMode'

const MODE_LABELS = { light: 'Light', dark: 'Dark', auto: 'Auto' } as const
const MODE_CYCLE: Array<'light' | 'dark' | 'auto'> = ['auto', 'light', 'dark']

function useColorMode() {
  return useSyncExternalStore(onModeChange, readMode, () => 'auto' as const)
}

function ColorModeButton() {
  const mode = useColorMode()
  const next = MODE_CYCLE[(MODE_CYCLE.indexOf(mode) + 1) % MODE_CYCLE.length]
  return (
    <button
      type="button"
      className="nav-color-mode"
      onClick={() => saveMode(next)}
      title={`Theme: ${MODE_LABELS[mode]}`}
    >
      {mode === 'dark' ? '☾' : mode === 'light' ? '☀' : '◑'} {MODE_LABELS[mode]}
    </button>
  )
}

function Shell() {
  const [due, setDue] = useState<number | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const location = useLocation()
  const isHome = location.pathname === '/'
  const ai = useAiMode()
  const setAi = useSetAiMode()

  const refreshDue = useCallback(() => {
    api.stats().then((s) => setDue(s.due)).catch(() => setDue(null))
  }, [])
  useEffect(refreshDue, [refreshDue, location.pathname])
  useEffect(() => setMenuOpen(false), [location.pathname])

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  return (
    <>
      <header className="shell-header">
        {!isHome && (
          <Link to="/" className="nav-home" aria-label="Home">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          </Link>
        )}
        <div className="nav-menu" ref={menuRef}>
          <button
            className="nav-menu-toggle"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="4" y1="6" x2="20" y2="6" />
              <line x1="4" y1="12" x2="20" y2="12" />
              <line x1="4" y1="18" x2="20" y2="18" />
            </svg>
          </button>
          {menuOpen && (
            <nav className="nav-dropdown">
              <Link to="/search">Search</Link>
              <Link to="/search#explore">Explore</Link>
              <Link to="/practice">Practice</Link>
              <Link to="/review">
                Review
                {due ? <span className="badge">{due}</span> : null}
              </Link>
              <Link to="/settings">Settings</Link>
              <div className="nav-mode">
                <span className={ai ? 'nav-mode-on' : undefined}>AI</span>
                <button
                  type="button"
                  className={`nav-switch${ai ? ' on' : ''}`}
                  role="switch"
                  aria-checked={ai}
                  aria-label="AI writing"
                  onClick={() => setAi(!ai)}
                >
                  <span />
                </button>
                <span className={!ai ? 'nav-mode-on' : undefined}>Non-AI</span>
              </div>
              <ColorModeButton />
            </nav>
          )}
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<BrowsePage />} />
          <Route path="/explore/:slug" element={<ExplorePage />} />
          <Route path="/topic/:key" element={<TopicPage />} />
          <Route path="/practice" element={<PracticePage />} />
          <Route path="/practice/history" element={<PracticeHistoryPage />} />
          <Route path="/review" element={<ReviewPage onReviewed={refreshDue} />} />
          <Route path="/studying" element={<Navigate to="/review" replace />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Home</Link></p>} />
        </Routes>
      </main>
    </>
  )
}

export function App() {
  useEffect(() => {
    applyMode()
    const idx = readPalette()
    if (idx !== 0) applyPalette(idx)
    const update = () => applyPalette(readPalette())
    const unsubMode = onModeChange(update)
    if (typeof window.matchMedia !== 'function') return unsubMode
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', update)
    return () => { mq.removeEventListener('change', update); unsubMode() }
  }, [])

  return (
    <AiModeProvider>
      <Shell />
    </AiModeProvider>
  )
}
