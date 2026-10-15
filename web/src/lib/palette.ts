export interface Palette {
  name: string
  mood: string
  light: {
    bg: string; surface: string; text: string; muted: string; border: string
    accent: string; accent2: string; accentSoft: string
  }
  dark: {
    bg: string; surface: string; text: string; muted: string; border: string
    accent: string; accent2: string; accentSoft: string
  }
}

export const PALETTES: Palette[] = [
  {
    name: 'Default',
    mood: 'classic museum',
    light: { bg: '#f7f6f2', surface: '#ffffff', text: '#1f2328', muted: '#5f6670', border: '#e3e1da', accent: '#2f6f5e', accent2: '#b5651d', accentSoft: '#e4efe9' },
    dark: { bg: '#15171a', surface: '#1d2024', text: '#e8e6e1', muted: '#a3a8af', border: '#2f3338', accent: '#7fc4ad', accent2: '#e2a160', accentSoft: '#23332e' },
  },
  {
    name: 'Antiquarian Ink',
    mood: 'scholarly and calm',
    light: { bg: '#f2f4f5', surface: '#ffffff', text: '#0f1a24', muted: '#4c6675', border: '#c7d0d6', accent: '#1f3a4a', accent2: '#4c6675', accentSoft: '#dce3e8' },
    dark: { bg: '#0f1a24', surface: '#162633', text: '#e8edf0', muted: '#8ca0ad', border: '#243644', accent: '#7fb5d0', accent2: '#a0bfcf', accentSoft: '#1a2e3d' },
  },
  {
    name: 'Terracotta Exhibit',
    mood: 'earthy and welcoming',
    light: { bg: '#f6efe8', surface: '#ffffff', text: '#3a2a21', muted: '#7a6155', border: '#e3d5ca', accent: '#8d4a36', accent2: '#c66b4b', accentSoft: '#f0ddd2' },
    dark: { bg: '#2a1e18', surface: '#362820', text: '#f0e6de', muted: '#b09585', border: '#4a3a30', accent: '#e3b39d', accent2: '#c66b4b', accentSoft: '#3d2d24' },
  },
  {
    name: 'Gallery Stone',
    mood: 'grounded and refined',
    light: { bg: '#e6dfd2', surface: '#f2ede4', text: '#2f3437', muted: '#6e7a7f', border: '#cdc6b8', accent: '#6e7a7f', accent2: '#c49a6c', accentSoft: '#d8d1c4' },
    dark: { bg: '#2f3437', surface: '#3a3e42', text: '#e6dfd2', muted: '#9aa3a8', border: '#4a4e52', accent: '#c49a6c', accent2: '#b7b0a4', accentSoft: '#3e4245' },
  },
  {
    name: 'Night at the Museum',
    mood: 'moody and cinematic',
    light: { bg: '#f0f2f6', surface: '#ffffff', text: '#0b0d12', muted: '#5a6578', border: '#d0d4dc', accent: '#2f3f5c', accent2: '#5a6578', accentSoft: '#dfe3ec' },
    dark: { bg: '#0b0d12', surface: '#141824', text: '#f0f2f6', muted: '#7a8899', border: '#242d40', accent: '#9aa7b8', accent2: '#6b7b94', accentSoft: '#1a2233' },
  },
]

const KEY = 'museo-palette'

export function readPalette(): number {
  try {
    const v = localStorage.getItem(KEY)
    if (v !== null) {
      const n = Number(v)
      if (n >= 0 && n < PALETTES.length) return n
    }
  } catch {}
  return 0
}

export function savePalette(index: number) {
  try { localStorage.setItem(KEY, String(index)) } catch {}
}

export function applyPalette(index: number) {
  const p = PALETTES[index] ?? PALETTES[0]
  const isDark = typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
  const colors = isDark ? p.dark : p.light
  const root = document.documentElement
  if (index === 0) {
    root.style.removeProperty('--bg')
    root.style.removeProperty('--surface')
    root.style.removeProperty('--text')
    root.style.removeProperty('--muted')
    root.style.removeProperty('--border')
    root.style.removeProperty('--accent')
    root.style.removeProperty('--accent-2')
    root.style.removeProperty('--accent-soft')
  } else {
    root.style.setProperty('--bg', colors.bg)
    root.style.setProperty('--surface', colors.surface)
    root.style.setProperty('--text', colors.text)
    root.style.setProperty('--muted', colors.muted)
    root.style.setProperty('--border', colors.border)
    root.style.setProperty('--accent', colors.accent)
    root.style.setProperty('--accent-2', colors.accent2)
    root.style.setProperty('--accent-soft', colors.accentSoft)
  }
  document.body.style.background = index === 0 ? '' : colors.bg
}
