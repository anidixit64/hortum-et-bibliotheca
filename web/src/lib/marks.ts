/** Text pieces for the summary and explanations: plain text, or a mention of a clue. */
export type Piece = { text: string; rank?: number }

const MARK = /\[\[(\d+)\|([^\]]+)\]\]/g

/** The summary's [[rank|words]] marks as pieces. */
export function parseMarks(text: string): Piece[] {
  const out: Piece[] = []
  let at = 0
  for (const m of text.matchAll(MARK)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    out.push({ text: m[2], rank: Number(m[1]) })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}

/** Extract capitalized names from summary text (after stripping [[rank|words]] marks).
 *  Collects phrases of capitalized words joined by lowercase connectors (of, the, and…),
 *  strips leading articles, and sends the result to the lookup endpoint which filters to
 *  actual topics. Over-extraction is fine — the backend rejects non-topics. */
export function extractProperNouns(text: string): string[] {
  const plain = text.replace(/\[\[\d+\|([^\]]+)\]\]/g, '$1')
  const names = new Set<string>()
  const JOINER = /^(of|the|and|in|on|at|for|de|von|van|del|di|le|la|el|al|ibn|bin|y|e|da|du|des|den)$/i
  // Split into sentences so a period breaks a phrase ("Brussels. Napoleon" → two names).
  for (const sentence of plain.split(/(?<=[.!?])\s+/)) {
    const ws = sentence.split(/\s+/).filter(Boolean)
    for (let i = 0; i < ws.length; i++) {
      const w = ws[i].replace(/[.,;:!?)"]+$/, '').replace(/^[("]+/, '')
      if (!/^[A-Z][a-zA-Z'-]*$/.test(w)) continue
      const parts = [w]
      let j = i + 1
      while (j < ws.length) {
        const raw = ws[j].replace(/[.,;:!?)"]+$/, '').replace(/^[("]+/, '')
        if (/^[A-Z][a-zA-Z'-]*$/.test(raw)) {
          parts.push(raw)
          j++
        } else if (JOINER.test(raw) && j + 1 < ws.length && /^[A-Z]/.test(ws[j + 1])) {
          parts.push(raw)
          j++
        } else {
          break
        }
      }
      // Strip a leading article: "The Battle of Waterloo" → "Battle of Waterloo"
      const full = parts.join(' ')
      const trimmed = full.replace(/^(The|A|An)\s+/, '')
      if (trimmed.length > 1) names.add(trimmed)
      // Also add the full form if different (some topics include the article).
      if (full !== trimmed && full.length > 1) names.add(full)
      i = j - 1
    }
  }
  return [...names]
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Other clues named in a text (by label or spelling, first mention only), as pieces:
 *  "Burnside's Bridge" in Ambrose Burnside's explanation becomes a link to its card. */
export function linkClues(
  text: string,
  clues: { rank: number; names: string[] }[],
  self: number,
): Piece[] {
  const names = clues
    .filter((c) => c.rank !== self)
    .flatMap((c) => c.names.filter((n) => n.length > 2).map((n) => ({ name: n, rank: c.rank })))
    .sort((a, b) => b.name.length - a.name.length)
  if (!names.length) return [{ text }]
  const pattern = new RegExp(`(?<![\\w])(${names.map((n) => escape(n.name)).join('|')})(?![\\w])`, 'gi')
  const rankOf = new Map(names.map((n) => [n.name.toLowerCase(), n.rank]))
  const seen = new Set<number>()
  const out: Piece[] = []
  let at = 0
  for (const m of text.matchAll(pattern)) {
    const rank = rankOf.get(m[0].toLowerCase())
    if (rank === undefined || seen.has(rank)) continue
    seen.add(rank)
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    out.push({ text: m[0], rank })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}
