import { useCallback, useEffect, useState } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api/client'
import { PracticePage } from './pages/PracticePage'
import { ReviewPage } from './pages/ReviewPage'
import { SearchPage } from './pages/SearchPage'
import { StudyingPage } from './pages/StudyingPage'
import { TopicPage } from './pages/TopicPage'

export function App() {
  const [due, setDue] = useState<number | null>(null)
  const location = useLocation()
  const refreshDue = useCallback(() => {
    api.stats().then((s) => setDue(s.due)).catch(() => setDue(null))
  }, [])
  useEffect(refreshDue, [refreshDue, location.pathname])

  return (
    <>
      <header className="shell-header">
        <Link to="/" className="brand">Hortum et Bibliotheca</Link>
        <nav>
          <Link to="/">Search</Link>
          <Link to="/practice">Practice</Link>
          <Link to="/review">Review {due ? <span className="badge">{due}</span> : null}</Link>
          <Link to="/studying">Studying</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/topic/:key" element={<TopicPage />} />
          <Route path="/practice" element={<PracticePage />} />
          <Route path="/review" element={<ReviewPage onReviewed={refreshDue} />} />
          <Route path="/studying" element={<StudyingPage />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Search</Link></p>} />
        </Routes>
      </main>
    </>
  )
}
