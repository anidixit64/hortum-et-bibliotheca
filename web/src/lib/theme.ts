import { useEffect } from 'react'
import type { Theme, ThemeColors } from '../api/types'

const FONTS: Record<string, string> = {
  'classical-serif': "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif",
  'modern-sans': "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  humanist: "Optima, Candara, 'Gill Sans', 'Segoe UI', sans-serif",
  'elegant-serif': "Didot, 'Bodoni 72', 'Bodoni MT', 'Times New Roman', serif",
  geometric: "Futura, Avenir, 'Century Gothic', 'Trebuchet MS', sans-serif",
  slab: "Rockwell, 'Roboto Slab', 'Courier New', serif",
  typewriter: "'American Typewriter', 'Courier Prime', 'Courier New', monospace",
}

const TOKENS: (keyof ThemeColors)[] = [
  'bg', 'surface', 'text', 'muted', 'accent', 'accent2', 'accent_soft', 'header_tint',
]

/** CSS variables for a topic's colors: --l-* and --d-* sets, which index.css maps to the
 *  page's --bg, --text... by color scheme. */
export function themeVariables(theme: Theme): Record<string, string> {
  const vars: Record<string, string> = {}
  for (const token of TOKENS) {
    const name = token.replace('_', '-')
    vars[`--l-${name}`] = theme.light[token]
    vars[`--d-${name}`] = theme.dark[token]
  }
  vars['--font-body'] = FONTS[theme.font] ?? FONTS['classical-serif']
  return vars
}

/** Colors the whole page while a topic with a theme is open. */
export function useTopicTheme(theme: Theme | null) {
  useEffect(() => {
    if (!theme) return
    const root = document.documentElement
    const vars = themeVariables(theme)
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v)
    root.classList.add('themed')
    return () => {
      for (const k of Object.keys(vars)) root.style.removeProperty(k)
      root.classList.remove('themed')
    }
  }, [theme])
}
