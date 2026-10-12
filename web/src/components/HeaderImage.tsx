import type { WikiImage } from '../api/types'

/** The topic's header image, fading into the page's colors, with its credit. */
export function HeaderImage({ image }: { image: WikiImage }) {
  return (
    <figure className="header-image">
      <div className="header-image-picture" style={{ backgroundImage: `url("${image.url}")` }} role="img"
           aria-label={image.caption ?? image.file} />
      <figcaption className="muted small">
        {image.artist && <>{image.artist} · </>}
        {image.license_url ? (
          <a href={image.license_url} target="_blank" rel="noreferrer">{image.license}</a>
        ) : (
          image.license
        )}
        {image.page && (
          <>
            {' · '}
            <a href={image.page} target="_blank" rel="noreferrer">source</a>
          </>
        )}
      </figcaption>
    </figure>
  )
}
