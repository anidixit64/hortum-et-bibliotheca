import type { Clue } from '../api/types'
import { cellShades } from '../lib/heatmap'

const CELL = 28
const LABEL_W = 190

/** Rows: clues. Columns: where in the question they're asked, lead-in to giveaway.
 *  Dots mark clusters you've buzzed on in practice. */
export function Heatmap({ clues, buzzed }: { clues: Clue[]; buzzed: Record<string, number> }) {
  const shades = cellShades(clues.map((c) => c.heatmap.position_hist))
  const width = LABEL_W + CELL * 10 + 30
  const height = CELL * clues.length + 24
  return (
    <svg className="heatmap" width="100%" viewBox={`0 0 ${width} ${height}`} role="img"
         aria-label="Where each clue appears in questions">
      {clues.map((clue, row) => (
        <g key={clue.cluster_id} transform={`translate(0, ${row * CELL})`}>
          <text className="label" x={LABEL_W - 8} y={CELL / 2 + 4} textAnchor="end">
            {clue.label.length > 26 ? `${clue.label.slice(0, 25)}…` : clue.label}
          </text>
          {shades[row].map((shade, col) => (
            <rect key={col} x={LABEL_W + col * CELL} y={2} width={CELL - 3} height={CELL - 4} rx={3}
                  fill="var(--accent)" fillOpacity={shade || 0.05}>
              <title>{`${clue.heatmap.position_hist[col]} questions at ${col * 10}–${col * 10 + 10}%`}</title>
            </rect>
          ))}
          {buzzed[String(clue.cluster_id)] && (
            <circle cx={LABEL_W + CELL * 10 + 12} cy={CELL / 2} r={5} fill="var(--accent-2)">
              <title>{`You buzzed on this clue ${buzzed[String(clue.cluster_id)]}×`}</title>
            </circle>
          )}
        </g>
      ))}
      <text x={LABEL_W} y={height - 6}>lead-in</text>
      <text x={LABEL_W + CELL * 10} y={height - 6} textAnchor="end">giveaway</text>
    </svg>
  )
}
