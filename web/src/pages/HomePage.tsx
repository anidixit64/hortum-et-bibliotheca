import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export function HomePage() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    } else {
      navigate('/search')
    }
  }

  return (
    <div className="home">
      <div className="home-center">
        <h1 className="home-title">Museo</h1>
        <p className="home-subtitle">Your exhibit for every quiz bowl answer</p>
        <form className="home-search" onSubmit={submit}>
          <input
            type="search"
            placeholder="Search a topic..."
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
      </div>
    </div>
  )
}
