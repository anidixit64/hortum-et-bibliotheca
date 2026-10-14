import type { WikiPayload } from '../api/types'

export interface WikiNote {
  heading: string
  sentence: string
}

function fold(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.replace(/\s+/g, ' ').trim())
    .filter((s) => s.length > 40)
}

/** The Wikipedia sentence that best matches a clue, preferring a section over the lead. */
export function wikiNote(label: string, variants: string[], wiki: WikiPayload): WikiNote | null {
  const names = [label, ...variants].map(fold).filter((n) => n.length >= 3)
  if (!names.length) return null
  const pools = [
    ...wiki.sections.map((s) => ({ heading: s.heading, text: s.text })),
    { heading: '', text: wiki.lead },
  ]
  let best: { score: number; heading: string; sentence: string } | null = null
  for (const pool of pools) {
    const headingFold = fold(pool.heading)
    for (const sentence of sentences(pool.text)) {
      const hay = fold(sentence)
      let score = 0
      for (const name of names) {
        if (hay.includes(name)) score += 5 + name.length
        else {
          const words = name.split(' ').filter((w) => w.length > 3)
          if (words.length && words.every((w) => hay.includes(w))) score += 2
        }
        if (name && headingFold.includes(name)) score += 3
      }
      if (score > 0 && (!best || score > best.score)) best = { score, heading: pool.heading, sentence }
    }
  }
  return best ? { heading: best.heading, sentence: best.sentence } : null
}
