import { SearchBox } from '../components/SearchBox'

export function SearchPage() {
  return (
    <>
      <section className="hero">
        <h1>Hortum et Bibliotheca</h1>
        <p className="muted">Look up any quiz bowl answer: the clues worth knowing, what it's confused with, and practice on real questions.</p>
      </section>
      <div className="card">
        <SearchBox autoFocus />
      </div>
    </>
  )
}
