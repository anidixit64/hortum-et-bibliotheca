import type { ContentKind, Section, SectionPayloads } from '../api/types'

function payload<K extends ContentKind>(section: Section<K>): SectionPayloads[K] | null {
  return section.status === 'ok' ? (section.payload as SectionPayloads[K]) : null
}

function Status({ section, what }: { section: Section; what: string }) {
  switch (section.status) {
    case 'pending':
      return <p className="muted">Fetching {what}…</p>
    case 'failed':
      return <p className="muted">Couldn't fetch {what} right now. Try again later.</p>
    case 'unavailable':
      return <p className="muted">{what[0].toUpperCase() + what.slice(1)}: coming soon.</p>
    case 'empty':
      return <p className="muted">No {what} found.</p>
    default:
      return null
  }
}

export function WikiSummary({ section }: { section: Section<'wiki'> }) {
  const wiki = payload(section)
  if (!wiki) return <Status section={section} what="the Wikipedia summary" />
  return (
    <>
      {wiki.lead.split('\n').map((p, i) => (
        <p key={i} className="prose">
          {p}
        </p>
      ))}
      {wiki.sections.length > 0 && (
        <details>
          <summary>More from the article ({wiki.sections.length} sections)</summary>
          {wiki.sections.map((s) => (
            <div key={s.heading}>
              <h3>{s.heading}</h3>
              {s.text.split('\n').map((p, i) => (
                <p key={i} className="prose">
                  {p}
                </p>
              ))}
            </div>
          ))}
        </details>
      )}
      <p className="muted small attribution">
        {wiki.attribution}{' '}
        <a href={wiki.url} target="_blank" rel="noreferrer">
          Read on Wikipedia
        </a>{' '}
        ·{' '}
        <a href={wiki.license_url} target="_blank" rel="noreferrer">
          {wiki.license}
        </a>
      </p>
    </>
  )
}

export function Gallery({ section }: { section: Section<'images'> }) {
  const data = payload(section)
  if (!data) return <Status section={section} what="images" />
  if (data.images.length === 0) return <p className="muted">No images found.</p>
  return (
    <div className="gallery">
      {data.images.map((img) => (
        <figure key={img.file}>
          <a href={img.page ?? img.url} target="_blank" rel="noreferrer">
            <img src={img.url} alt={img.caption ?? img.file} loading="lazy" />
          </a>
          <figcaption className="small muted">
            {img.caption && <span className="caption">{img.caption}</span>}
            <span>
              {img.artist && <>{img.artist} · </>}
              {img.license_url ? (
                <a href={img.license_url} target="_blank" rel="noreferrer">
                  {img.license}
                </a>
              ) : (
                img.license
              )}
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

export function Reading({ section }: { section: Section<'books'> }) {
  const data = payload(section)
  if (!data) return <Status section={section} what="books" />
  const books = data.books.filter((b) => b.title)
  return (
    <>
      {books.length === 0 ? (
        <p className="muted">No books found.</p>
      ) : (
        <ul className="books">
          {books.map((b) => (
            <li key={b.open_library ?? b.title}>
              {b.cover ? (
                <img src={b.cover} alt="" loading="lazy" />
              ) : (
                <div className="no-cover" aria-hidden />
              )}
              <div>
                <a href={b.open_library ?? '#'} target="_blank" rel="noreferrer">
                  {b.title}
                </a>
                <div className="muted small">
                  {[b.author, b.year].filter(Boolean).join(', ')}
                  {b.cited > 0 && <span className="pill">cited by Wikipedia</span>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data.references.length > 0 && (
        <p className="small">
          Reference works:{' '}
          {data.references.map((r, i) => (
            <span key={r.url}>
              {i > 0 && ' · '}
              <a href={r.url} target="_blank" rel="noreferrer">
                {r.name}
              </a>
            </span>
          ))}
        </p>
      )}
      <p className="muted small">Book data from Open Library.</p>
    </>
  )
}

function minutes(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function Videos({ section }: { section: Section<'videos'> }) {
  const data = payload(section)
  if (!data) return <Status section={section} what="videos" />
  if (data.videos.length === 0) return <p className="muted">No videos found.</p>
  return (
    <div className="videos">
      {data.videos.map((v) => (
        <figure key={v.id}>
          <iframe
            src={v.embed}
            title={v.title}
            loading="lazy"
            allow="encrypted-media; picture-in-picture"
            allowFullScreen
          />
          <figcaption className="small">
            <a href={v.url} target="_blank" rel="noreferrer">
              {v.title}
            </a>
            <span className="muted">
              {' '}
              · {v.channel} · {minutes(v.seconds)}
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}
