import type { RouletteTopic } from '../api/types'

export const RIM = 10
/** How many names the window is built to show. The center line sits on the middle one. */
export const WINDOW = 7
export const CELL_PX = 104
export const SPIN_MS = 3600

/** A long vertical strip. The winner is placed so it can rest on the center line, with room to spin. */
export function buildStrip(pool: RouletteTopic[], winnerId: string, loops = 6): RouletteTopic[] {
  const rim = pool.slice(0, RIM)
  if (!rim.length) return []
  const winner = rim.find((topic) => topic.topic_id === winnerId) ?? rim[0]
  const pad = Math.floor(WINDOW / 2)
  const strip = Array.from({ length: loops }, () => rim).flat()
  strip.push(winner)
  for (let i = 0; i < pad; i++) strip.push(rim[i % rim.length])
  return strip
}

/** The cell that should sit on the center line: the winner, with padding after it. */
export function landingIndex(strip: RouletteTopic[]): number {
  return Math.max(0, strip.length - 1 - Math.floor(WINDOW / 2))
}

/** Translate the strip so `index` is centered in a window of `windowPx`. */
export function reelOffset(index: number, windowPx: number, cell = CELL_PX): number {
  return windowPx / 2 - cell / 2 - index * cell
}

export function pickWinner(pool: RouletteTopic[]): RouletteTopic | null {
  const rim = pool.slice(0, RIM)
  if (!rim.length) return null
  return rim[Math.floor(Math.random() * rim.length)]
}

export function topicBlurb(topic: RouletteTopic): string {
  const text = topic.description?.trim()
  if (text) return text
  const filed = topic.category ? ` in ${topic.category}` : ''
  const asked = topic.count === 1 ? '1 question' : `${topic.count} questions`
  return `A quiz bowl answer${filed}, asked in ${asked}.`
}
