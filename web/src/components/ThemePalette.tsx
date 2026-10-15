import { useEffect, useState } from 'react'
import type { Theme, ThemeColors } from '../api/types'

const SWATCHES: { key: keyof ThemeColors; label: string }[] = [
  { key: 'bg', label: 'Ground' },
  { key: 'surface', label: 'Cards' },
  { key: 'accent', label: 'Accent' },
  { key: 'accent2', label: 'Second' },
  { key: 'accent_soft', label: 'Soft' },
]

export function ThemePalette({ theme, topicName }: { theme: Theme; topicName: string }) {
  const [open, setOpen] = useState(false)
  const colors = theme.light

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const why = theme.rationale?.trim()
    || `These colors were chosen to give ${topicName} a palette of its own.`

  return (
    <>
      <button
        type="button"
        className="palette-peek"
        aria-label="Color palette"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span style={{ background: colors.accent }} />
        <span style={{ background: colors.accent2 }} />
        <span style={{ background: colors.accent_soft }} />
      </button>
      {open && (
        <>
          <button type="button" className="palette-note-backdrop" aria-label="Dismiss palette" onClick={() => setOpen(false)} />
          <div className="palette-note" role="dialog" aria-label="Color palette">
            <div className="palette-note-head">
              <h2>This page's palette</h2>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close palette">
                Close
              </button>
            </div>
            <p>{why}</p>
            <ul className="palette-swatches">
              {SWATCHES.map((swatch) => (
                <li key={swatch.key}>
                  <span style={{ background: colors[swatch.key] }} />
                  <em>{swatch.label}</em>
                  <code>{colors[swatch.key]}</code>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  )
}
