import type { WikiImage } from '../api/types'

/** How many collection cards share each sidebar with the map or the timeline. */
export const SIDE_PHOTOS = 3

export type SidebarSlot = 'lead' | 'photo' | 'rest'

/** Map or timeline first, then photos with the other sidebar cards woven between them. */
export function sidebarSlots(photoCount: number, restCount: number, hasLead: boolean): SidebarSlot[] {
  const slots: SidebarSlot[] = []
  if (hasLead) slots.push('lead')
  let rest = restCount
  if (photoCount === 0) {
    for (let i = 0; i < rest; i++) slots.push('rest')
    return slots
  }
  for (let i = 0; i < photoCount; i++) {
    slots.push('photo')
    if (rest > 0) {
      slots.push('rest')
      rest -= 1
    }
  }
  while (rest > 0) {
    slots.push('rest')
    rest -= 1
  }
  return slots
}

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
