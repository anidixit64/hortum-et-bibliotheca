import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

const KEY = 'museo-ai'

export function readAiMode(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off'
  } catch {
    return true
  }
}

const AiModeContext = createContext<{ ai: boolean; setAi: (on: boolean) => void } | null>(null)

export function AiModeProvider({ children }: { children: ReactNode }) {
  const [ai, setAiState] = useState(readAiMode)
  const setAi = (on: boolean) => {
    localStorage.setItem(KEY, on ? 'on' : 'off')
    setAiState(on)
  }
  return <AiModeContext.Provider value={{ ai, setAi }}>{children}</AiModeContext.Provider>
}

/** AI writing is on unless this browser has switched to Non-AI. */
export function useAiMode(): boolean {
  return useContext(AiModeContext)?.ai ?? readAiMode()
}

export function useSetAiMode(): (on: boolean) => void {
  const ctx = useContext(AiModeContext)
  if (!ctx) return () => {}
  return ctx.setAi
}
