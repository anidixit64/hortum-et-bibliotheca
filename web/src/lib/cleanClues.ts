import type { CleanedClue, Clue } from '../api/types'

/** How many raw clues the cleanup looked at: past these, "show more" shows raw ones. */
export const CLEANED_FROM = 25

/** The page's clue list after cleanup: each cleaned clue built from its corpus clues
 *  (label and count from the cleanup; text, examples and heatmap from the records). */
export function applyCleanup(records: Clue[], cleaned: CleanedClue[]): Clue[] {
  const byId = new Map(records.map((r) => [r.cluster_id, r]))
  const out: Clue[] = []
  for (const c of cleaned) {
    const parts = c.clue_ids.map((id) => byId.get(id)).filter((r): r is Clue => r !== undefined)
    const home = parts[0]
    if (!home) continue
    const hist = home.heatmap.position_hist.map((_, i) =>
      parts.reduce((sum, p) => sum + (p.heatmap.position_hist[i] ?? 0), 0),
    )
    const examples = [...new Set([...home.examples, ...parts.slice(1).flatMap((p) => [p.text, ...p.examples])])]
      .filter((e) => e !== home.text)
      .slice(0, 3)
    out.push({
      ...home,
      rank: c.rank,
      label: c.label,
      n_questions: c.n_questions,
      n_tossups: c.n_questions,
      n_sets: Math.max(...parts.map((p) => p.n_sets)),
      examples,
      heatmap: { ...home.heatmap, position_hist: hist },
    })
  }
  return out
}
