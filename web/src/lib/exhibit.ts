import type { WikiImage } from '../api/types'

/** How many collection cards sit above the map, and above the timeline. */
export const SIDE_PHOTOS = 3

export interface PlacedPhotos {
  summary: WikiImage[]
  left: WikiImage[]
  right: WikiImage[]
  gallery: WikiImage[]
}

/** Summary takes two (right, then left). Each sidebar takes up to three.
 *  Everything else stays for the gallery. Example slides keep their own files. */
export function placePhotos(
  images: WikiImage[],
  illustrated: Set<string>,
  hasHeader: boolean,
): PlacedPhotos {
  const pool = (hasHeader ? images.filter((image) => !image.is_main) : images).filter(
    (image) => !illustrated.has(image.file),
  )
  const summary = pool.slice(0, 2)
  const sides = pool.slice(summary.length)
  const left: WikiImage[] = []
  const right: WikiImage[] = []
  for (const image of sides) {
    if (left.length <= right.length && left.length < SIDE_PHOTOS) left.push(image)
    else if (right.length < SIDE_PHOTOS) right.push(image)
    else break
  }
  const used = new Set([...summary, ...left, ...right].map((image) => image.file))
  return { summary, left, right, gallery: pool.filter((image) => !used.has(image.file)) }
}
