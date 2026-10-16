import type { BookBlurb, ContentKind, Section, SectionPayloads, WikiImage } from '../api/types'

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

export function WikiArticle({ section }: { section: Section<'wiki'> | undefined }) {
  if (!section) return <p className="muted">Fetching the Wikipedia article…</p>
  const wiki = payload(section)
  if (!wiki) return <Status section={section} what="the Wikipedia article" />
  return (
    <div className="wiki-article">
      {wiki.lead.split('\n').filter(Boolean).map((p, i) => (
        <p key={i} className="prose">{p}</p>
      ))}
      {wiki.sections.map((s) => (
        <details key={s.heading} className="wiki-section">
          <summary>{s.heading}</summary>
          {s.text.split('\n').filter(Boolean).map((p, i) => (
            <p key={i} className="prose">{p}</p>
          ))}
        </details>
      ))}
      <p className="muted small">
        <a href={wiki.url} target="_blank" rel="noreferrer">Read on Wikipedia</a>
      </p>
    </div>
  )
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
      <p className="muted small">
        <a href={wiki.url} target="_blank" rel="noreferrer">
          Read on Wikipedia
        </a>
      </p>
    </>
  )
}

/** A museum label's title: the caption, or the file name made readable. */
function labelTitle(img: WikiImage) {
  const text = img.caption ?? img.file.replace(/^File:/, '').replace(/\.[a-z0-9]+$/i, '').replace(/_/g, ' ')
  const words = text.split(/\s+/)
  return words.length > 16 ? `${words.slice(0, 14).join(' ')}…` : text // full caption on hover
}

export function FloatImage({ image, side }: { image: WikiImage; side: 'left' | 'right' }) {
  return (
    <figure className={`float-image float-${side}`}>
      <a href={image.page ?? image.url} target="_blank" rel="noreferrer">
        <img src={image.url} alt={image.caption ?? image.file} loading="lazy" />
      </a>
      <figcaption className="museum-label small">
        <strong title={image.caption ?? undefined}>{labelTitle(image)}</strong>
        <span>
          {image.artist && <>{image.artist} · </>}
          {image.license_url ? (
            <a href={image.license_url} target="_blank" rel="noreferrer">
              {image.license}
            </a>
          ) : (
            image.license
          )}
        </span>
      </figcaption>
    </figure>
  )
}

function ImageFigure({ img }: { img: WikiImage }) {
  return (
    <figure key={img.file}>
      <a href={img.page ?? img.url} target="_blank" rel="noreferrer">
        <img src={img.url} alt={img.caption ?? img.file} loading="lazy" />
      </a>
      <figcaption className="museum-label small">
        <strong title={img.caption ?? undefined}>{labelTitle(img)}</strong>
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
  )
}

/** A gallery photo set into an open part of the exhibit, small enough for text to pass it. */
export function Artifact({ image, float }: { image: WikiImage; float?: 'left' | 'right' }) {
  return (
    <figure className={`artifact${float ? ` float-image float-${float}` : ''}`}>
      <a href={image.page ?? image.url} target="_blank" rel="noreferrer">
        <img src={image.url} alt={image.caption ?? image.file} loading="lazy" />
      </a>
      <figcaption className="museum-label small">
        <strong title={image.caption ?? undefined}>{labelTitle(image)}</strong>
      </figcaption>
    </figure>
  )
}

export function ImageGrid({ images }: { images: WikiImage[] }) {
  if (!images.length) return null
  return (
    <div className="gallery">
      {images.map((img) => <ImageFigure key={img.file} img={img} />)}
    </div>
  )
}

export function Gallery({ section }: { section: Section<'images'> }) {
  const data = payload(section)
  if (!data) return <Status section={section} what="images" />
  if (data.images.length === 0) return <p className="muted">No images found.</p>
  return <ImageGrid images={data.images} />
}

function foldTitle(title: string) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

export function Reading({
  section,
  blurbs = [],
}: {
  section: Section<'books'> | undefined
  blurbs?: BookBlurb[]
}) {
  if (!section) return <p className="muted">Fetching books…</p>
  const data = payload(section)
  if (!data) return <Status section={section} what="books" />
  const all = data.books.filter((b) => b.title)
  const books = all.length % 2 === 1 ? all.slice(0, -1) : all
  const blurbFor = new Map(blurbs.map((b) => [foldTitle(b.title), b.blurb]))
  return (
    <>
      {books.length === 0 ? (
        <p className="muted">No books found for a general reader.</p>
      ) : (
        <ul className="books">
          {books.map((b) => {
            const blurb = b.title ? blurbFor.get(foldTitle(b.title)) : undefined
            return (
              <li key={b.open_library ?? b.title}>
                {b.cover ? (
                  <img src={b.cover} alt="" loading="lazy" />
                ) : (
                  <div className="no-cover" aria-hidden />
                )}
                <div>
                  {b.open_library ? (
                    <a href={b.open_library} target="_blank" rel="noreferrer">{b.title}</a>
                  ) : (
                    <strong>{b.title}</strong>
                  )}
                  <div className="muted small">
                    {[b.author, b.year, b.publisher].filter(Boolean).join(', ')}
                  </div>
                  {blurb && <p className="book-blurb">{blurb}</p>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {data.references.length > 0 && (
        <p className="small">
          Reference works:{' '}
          {data.references.map((r, i) => (
            <span key={r.url}>
              {i > 0 && ' · '}
              <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a>
            </span>
          ))}
        </p>
      )}
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
