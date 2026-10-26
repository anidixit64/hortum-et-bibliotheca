const KEY = 'museo-color-mode'
type Mode = 'light' | 'dark' | 'auto'

let listeners: Array<() => void> = []

function notify() { listeners.forEach((fn) => fn()) }

export function readMode(): Mode {
  try {
    const v = localStorage.getItem(KEY) as Mode | null
    if (v === 'light' || v === 'dark') return v
  } catch {}
  return 'auto'
}

export function saveMode(mode: Mode) {
  try { localStorage.setItem(KEY, mode) } catch {}
  applyMode(mode)
  notify()
}

export function resolvedIsDark(mode?: Mode): boolean {
  const m = mode ?? readMode()
  if (m === 'light') return false
  if (m === 'dark') return true
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyMode(mode?: Mode) {
  const m = mode ?? readMode()
  const root = document.documentElement
  if (m === 'auto') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', m)
  }
}

export function onModeChange(fn: () => void) {
  listeners.push(fn)
  return () => { listeners = listeners.filter((f) => f !== fn) }
}
