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
