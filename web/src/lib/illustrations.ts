import type { WikiImage } from '../api/types'

export interface ExampleShot {
  name: string
  image: WikiImage
}

function matchNamedImages(names: string[], images: WikiImage[]): Map<string, WikiImage> {
  const matched = new Map<string, WikiImage>()
  const used = new Set<string>()
  for (const name of names) {
    const words = name.toLowerCase().split(/[\s']+/).filter((word) => word.length > 3)
    if (!words.length) continue
    for (const image of images) {
      if (used.has(image.file)) continue
      const hay = `${image.caption ?? ''} ${image.file}`.toLowerCase().replace(/_/g, ' ')
      if (words.some((word) => hay.includes(word))) {
        matched.set(name, image)
        used.add(image.file)
        break
      }
    }
  }
  return matched
}

function farthestName(names: string[], have: Set<string>, hits: Map<string, WikiImage>): string | null {
  const held = names.flatMap((name, index) => (have.has(name) ? [index] : []))
  let best: string | null = null
  let bestDist = -1
  names.forEach((name, index) => {
    if (!hits.has(name) || have.has(name)) return
    const dist = held.length === 0 ? index : Math.min(...held.map((at) => Math.abs(at - index)))
    if (dist > bestDist) {
      bestDist = dist
      best = name
    }
  })
  return best
}

/** At most two pictures, preferring a looked-up photo of the example itself. */
export function chooseIllustrations(
  names: string[],
  lookedUp: ExampleShot[],
  gallery: WikiImage[] = [],
): Record<string, WikiImage> {
  const lookup = new Map<string, WikiImage>()
  for (const shot of lookedUp) {
    if (names.includes(shot.name) && !lookup.has(shot.name)) lookup.set(shot.name, shot.image)
  }
  const indexes = names.flatMap((name, index) => (lookup.has(name) ? [index] : []))
  const chosen = new Map<string, WikiImage>()
  const keep = indexes.length <= 2 ? indexes : [indexes[0], indexes[indexes.length - 1]]
  for (const index of keep) {
    const image = lookup.get(names[index])
    if (image) chosen.set(names[index], image)
  }
  const galleryHits = matchNamedImages(names, gallery)
  while (chosen.size < 2) {
    const next = farthestName(names, new Set(chosen.keys()), galleryHits)
    if (!next) break
    const image = galleryHits.get(next)
    if (image) chosen.set(next, image)
  }
  return Object.fromEntries(chosen)
}
