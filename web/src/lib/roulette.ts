import type { RouletteTopic } from '../api/types'

export const RIM = 10

/** Delays for each tick of a spin: short at first, then longer, so the wheel slows down. */
export function spinDelays(steps: number): number[] {
  if (steps <= 1) return [0]
  return Array.from({ length: steps }, (_, i) => {
    const t = i / (steps - 1)
    const eased = 1 - (1 - t) ** 3
    return Math.round(36 + eased * 240)
  })
}

/** Names around the wheel, ending with the pointer on `winner`. */
export function buildReel(pool: RouletteTopic[], winnerId: string, steps = 22): RouletteTopic[] {
  const rim = pool.slice(0, RIM)
  if (!rim.length) return []
  const winnerAt = Math.max(0, rim.findIndex((topic) => topic.topic_id === winnerId))
  let count = Math.max(steps, 1)
  while ((count - 1) % rim.length !== winnerAt) count += 1
  return Array.from({ length: count }, (_, i) => rim[i % rim.length])
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
