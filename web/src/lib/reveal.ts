// Word-by-word reading, like a moderator.
import type { ClueSpan } from '../api/types'

export const words = (question: string): string[] => question.split(/\s+/).filter(Boolean)

/** Milliseconds per word at a reading speed in words per minute. */
export const msPerWord = (wpm: number): number => Math.round(60_000 / Math.max(wpm, 30))

/** The clue being read when word ``index`` appears. */
export function clueAt(clues: ClueSpan[], index: number): ClueSpan | undefined {
  return clues.find((c) => c.word_start <= index && index < c.word_end)
}

/** Has the reader passed the power mark (shown after the last word in power)? */
export const pastPower = (powerWord: number | null, shown: number): boolean =>
  powerWord !== null && shown >= powerWord
