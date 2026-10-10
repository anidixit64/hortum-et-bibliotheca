// Clue heatmap: rows are clues, columns are 10 position bins from lead-in to end.

/** Opacity for a cell: 0 for empty, scaled so the busiest cell of the grid is 1. */
export function cellShades(rows: number[][]): number[][] {
  const max = Math.max(1, ...rows.flat())
  return rows.map((row) => row.map((n) => (n === 0 ? 0 : 0.15 + 0.85 * (n / max))))
}

/** The bin a reading position (0..1) falls in, for "you buzzed here" markers. */
export const binOf = (position: number): number => Math.min(9, Math.max(0, Math.floor(position * 10)))
