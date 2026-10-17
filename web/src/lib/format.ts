export const percent = (x: number | null | undefined, digits = 0): string =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(digits)}%`

/** A Wikidata time at its precision: 9 year, 10 month, 11 day; BCE years shown as "BC". */
export function formatTime(time: string | null, precision: number | null): string {
  if (!time) return '?'
  const match = /^([+-])?(\d+)-(\d{2})-(\d{2})/.exec(time)
  if (!match) return time
  const [, sign, y, m, d] = match
  const year = Number(y)
  const era = sign === '-' ? ' BC' : ''
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  if ((precision ?? 9) >= 11) return `${Number(d)} ${months[Number(m) - 1]} ${year}${era}`
  if ((precision ?? 9) === 10) return `${months[Number(m) - 1]} ${year}${era}`
  if ((precision ?? 9) <= 7) return `${Math.ceil(year / 100)}th century${era}`
  return `${year}${era}`
}

/** A signed year for ordering timeline events. */
export function yearOf(time: string | null): number | null {
  const match = time && /^([+-])?(\d+)/.exec(time)
  if (!match) return null
  return match[1] === '-' ? -Number(match[2]) : Number(match[2])
}

export const DIFFICULTY_BANDS: Record<string, string> = {
  middle_school: 'Middle school',
  high_school: 'High school',
  college: 'College',
  open: 'Open',
  unrated: 'Unrated',
}

export const DIFFICULTY_LABELS: Record<number, string> = {
  0: 'Pop Culture',
  1: 'Middle School',
  2: 'Easy High School',
  3: 'Regular High School',
  4: 'Hard High School',
  5: 'National High School',
  6: '● / Easy College',
  7: '●● / Medium College',
  8: '●●● / Regionals College',
  9: '●●●● / Nationals College',
  10: 'Open',
}

export function difficultyLabel(d: number | null | undefined): string {
  if (d === null || d === undefined) return ''
  return DIFFICULTY_LABELS[d] ?? `D${d}`
}
