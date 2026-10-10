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
