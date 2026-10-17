import { useEffect } from 'react'
import type { Theme, ThemeColors } from '../api/types'
import { applyPalette, readPalette } from './palette'

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

const TOKEN_TO_PROP: Record<string, string> = {
  bg: '--bg', surface: '--surface', text: '--text', muted: '--muted',
  accent: '--accent', accent2: '--accent-2', accent_soft: '--accent-soft',
  header_tint: '--header-tint',
}

const PROPS = [...Object.values(TOKEN_TO_PROP), '--border', '--font-body']

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

/** Colors the whole page while a topic with a theme is open.
 *  Sets --bg, --accent etc. directly as inline styles so they override any site palette. */
export function useTopicTheme(theme: Theme | null) {
  useEffect(() => {
    if (!theme) return
    const root = document.documentElement

    function apply() {
      const isDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
      const colors = isDark ? theme!.dark : theme!.light
      for (const [token, prop] of Object.entries(TOKEN_TO_PROP)) {
        root.style.setProperty(prop, colors[token as keyof ThemeColors])
      }
      root.style.setProperty('--border', colors.accent_soft)
      root.style.setProperty('--font-body', FONTS[theme!.font] ?? FONTS['classical-serif'])
      document.body.style.background = colors.bg
    }

    const vars = themeVariables(theme)
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v)
    apply()
    root.classList.add('themed')

    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    const handler = () => apply()
    mq?.addEventListener('change', handler)

    return () => {
      mq?.removeEventListener('change', handler)
      for (const k of Object.keys(vars)) root.style.removeProperty(k)
      for (const prop of PROPS) root.style.removeProperty(prop)
      document.body.style.background = ''
      root.classList.remove('themed')
      applyPalette(readPalette())
    }
  }, [theme])
}
