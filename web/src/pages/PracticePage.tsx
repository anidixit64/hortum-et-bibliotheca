import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { BuzzOut, ClueSpan, Tossup } from '../api/types'
import { msPerWord, pastPower, words as split } from '../lib/reveal'

type Phase = 'loading' | 'reading' | 'countdown' | 'answering' | 'result' | 'empty'

const WPM_KEY = 'museo.wpm'
const HIGH_SCORE_KEY = 'museo.practice.highScore'
const COUNTDOWN_SECONDS = 10

const CATEGORIES = [
  'Current Events', 'Fine Arts', 'Geography', 'History', 'Literature',
  'Mythology', 'Other Academic', 'Philosophy', 'Pop Culture', 'Religion',
  'Science', 'Social Science',
]

const DIFFICULTY_LABELS: Record<number, string> = {
  0: 'MS', 1: '1', 2: '2', 3: '3', 4: '4',
  5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'Open',
}

function computePoints(
  buzzResult: 'correct' | 'incorrect' | 'no_buzz' | 'prompt',
  buzzAt: number | null,
  powerWord: number | null,
  totalWords: number,
): number {
  if (buzzResult !== 'correct' || buzzAt === null) return 0
  const lastLineStart = Math.max(0, totalWords - Math.ceil(totalWords * 0.15))
  if (powerWord !== null && buzzAt < powerWord) return 30
  if (buzzAt >= lastLineStart) return 10
  return 15
}

function readHighScore(): number {
  try { return Number(localStorage.getItem(HIGH_SCORE_KEY)) || 0 } catch { return 0 }
}

export function PracticePage() {
  const [params, setParams] = useSearchParams()
  const topic = params.get('topic') ?? undefined
  const initCategory = params.get('category') ?? undefined
  const [wpm, setWpm] = useState(() => Number(localStorage.getItem(WPM_KEY)) || 200)

  // Filters
  const [filterCategory, setFilterCategory] = useState<string | undefined>(initCategory)
  const [diffMin, setDiffMin] = useState<number | undefined>(undefined)
  const [diffMax, setDiffMax] = useState<number | undefined>(undefined)

  // Game state
  const [tossup, setTossup] = useState<Tossup | null>(null)
  const [shown, setShown] = useState(0)
  const [phase, setPhase] = useState<Phase>('loading')
  const [buzzAt, setBuzzAt] = useState<number | null>(null)
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<BuzzOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS)
  const seen = useRef<string[]>([])
  const input = useRef<HTMLInputElement>(null)

  // Score tracking
  const [score, setScore] = useState(0)
  const [highScore, setHighScore] = useState(readHighScore)
  const [lastPoints, setLastPoints] = useState<number | null>(null)

  const words = tossup ? split(tossup.question) : []

  const load = useCallback(() => {
    api
      .practiceNext({
        topic,
        category: filterCategory,
        difficultyMin: diffMin,
        difficultyMax: diffMax,
        exclude: seen.current,
      })
      .then((t) => {
        seen.current = [...seen.current, t.id]
        setTossup(t)
        setPhase('reading')
      })
      .catch((e: Error & { status?: number }) => {
        if (e.status === 404) setPhase('empty')
        else setError(e.message)
      })
  }, [topic, filterCategory, diffMin, diffMax])

  useEffect(load, [load])

  const next = () => {
    setPhase('loading')
    setTossup(null)
    setShown(0)
    setBuzzAt(null)
    setAnswer('')
    setResult(null)
    setError(null)
    setCountdown(COUNTDOWN_SECONDS)
    setLastPoints(null)
    load()
  }

  useEffect(() => localStorage.setItem(WPM_KEY, String(wpm)), [wpm])

  const applyPoints = useCallback((buzzResult: BuzzOut['result'], buzzIndex: number | null, totalWords: number, powerWord: number | null) => {
    const pts = computePoints(buzzResult, buzzIndex, powerWord, totalWords)
    setLastPoints(pts)
    if (pts > 0) {
      setScore(prev => {
        const newScore = prev + pts
        setHighScore(old => {
          const best = Math.max(old, newScore)
          try { localStorage.setItem(HIGH_SCORE_KEY, String(best)) } catch {}
          return best
        })
        return newScore
      })
    }
  }, [])

  const submit = useCallback(
    async (wordIndex: number | null, given?: string) => {
      if (!tossup) return
      try {
        const out = await api.buzz({ tossup_id: tossup.id, word_index: wordIndex, answer_given: given })
        setResult(out)
        if (out.result === 'prompt') {
          setAnswer('')
          input.current?.focus()
        } else {
          setShown(words.length)
          setPhase('result')
          applyPoints(out.result, wordIndex, words.length, tossup.power_word)
        }
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [tossup, words.length, applyPoints],
  )

  // Reveal one word at a time; when done, enter countdown phase
  useEffect(() => {
    if (phase !== 'reading' || !tossup) return
    const timer = setTimeout(() => {
      if (shown >= words.length) {
        setShown(words.length)
        setPhase('countdown')
      } else {
        setShown((n) => n + 1)
      }
    }, msPerWord(wpm))
    return () => clearTimeout(timer)
  }, [phase, shown, tossup, words.length, wpm])

  // Countdown timer after full question read
  useEffect(() => {
    if (phase !== 'countdown') return
    if (countdown <= 0) {
      void submit(null)
      return
    }
    const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [phase, countdown, submit])

  const buzz = useCallback(() => {
    if (phase !== 'reading' && phase !== 'countdown') return
    setBuzzAt(phase === 'countdown' ? words.length - 1 : Math.max(shown - 1, 0))
    setPhase('answering')
    setTimeout(() => input.current?.focus(), 0)
  }, [phase, shown, words.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' && (phase === 'reading' || phase === 'countdown')) {
        e.preventDefault()
        buzz()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [buzz, phase])

  const override = async (judgment: 'correct' | 'incorrect') => {
    if (!result?.buzz_id) return
    await api.overrideBuzz(result.buzz_id, judgment)
    const prevResult = result.result
    setResult({ ...result, result: judgment, judged_by: 'self' })
    if (prevResult === 'correct' && judgment === 'incorrect' && lastPoints) {
      setScore(s => Math.max(0, s - lastPoints))
      setLastPoints(0)
    } else if (prevResult !== 'correct' && judgment === 'correct') {
      const pts = computePoints('correct', buzzAt, tossup?.power_word ?? null, words.length)
      setLastPoints(pts)
      setScore(s => {
        const newScore = s + pts
        setHighScore(old => {
          const best = Math.max(old, newScore)
          try { localStorage.setItem(HIGH_SCORE_KEY, String(best)) } catch {}
          return best
        })
        return newScore
      })
    }
  }

  const newGame = () => {
    setHighScore(old => {
      const best = Math.max(old, score)
      try { localStorage.setItem(HIGH_SCORE_KEY, String(best)) } catch {}
      return best
    })
    setScore(0)
    setLastPoints(null)
    seen.current = []
    next()
  }

  const updateCategory = (cat: string | undefined) => {
    setFilterCategory(cat)
    const p = new URLSearchParams(params)
    if (cat) p.set('category', cat); else p.delete('category')
    setParams(p, { replace: true })
  }

  // ── Render ──────────────────────────────────────────────────────────

  if (error) return <div className="practice-page"><p className="error">{error}</p></div>
  if (phase === 'empty')
    return (
      <div className="practice-page">
        <div className="practice-card">
          <p>No more questions match your filters. <Link to="/">Search another topic</Link>.</p>
        </div>
      </div>
    )

  return (
    <div className="practice-page">
      <h1 className="practice-title">Practice</h1>

      <div className="practice-layout">
        {/* ── Left sidebar: filters ── */}
        <aside className="practice-sidebar">
          <div className="sidebar-card">
            <h3 className="sidebar-title">Filters</h3>

            <label className="filter-label">Category</label>
            <select
              className="filter-select"
              value={filterCategory ?? ''}
              onChange={e => { updateCategory(e.target.value || undefined); }}
            >
              <option value="">All categories</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>

            <label className="filter-label">Difficulty</label>
            <div className="filter-diff-row">
              <select
                className="filter-select filter-select-half"
                value={diffMin ?? ''}
                onChange={e => setDiffMin(e.target.value ? Number(e.target.value) : undefined)}
              >
                <option value="">Min</option>
                {Array.from({ length: 11 }, (_, i) => (
                  <option key={i} value={i}>{DIFFICULTY_LABELS[i]}</option>
                ))}
              </select>
              <span className="filter-dash">–</span>
              <select
                className="filter-select filter-select-half"
                value={diffMax ?? ''}
                onChange={e => setDiffMax(e.target.value ? Number(e.target.value) : undefined)}
              >
                <option value="">Max</option>
                {Array.from({ length: 11 }, (_, i) => (
                  <option key={i} value={i}>{DIFFICULTY_LABELS[i]}</option>
                ))}
              </select>
            </div>

            <label className="filter-label">Speed</label>
            <div className="filter-speed">
              <input type="range" min={100} max={400} step={20} value={wpm}
                     onChange={e => setWpm(Number(e.target.value))} />
              <span className="filter-speed-val">{wpm} wpm</span>
            </div>

            {topic && (
              <div className="filter-topic-badge">
                <span className="pill">Topic</span>
                <Link to={`/topic/${encodeURIComponent(topic)}`}>{topic}</Link>
              </div>
            )}
          </div>
        </aside>

        {/* ── Center: question ── */}
        <div className="practice-center">
          {!tossup ? (
            <div className="practice-card">
              <p className="muted practice-loading">Loading a question…</p>
            </div>
          ) : (
            <div className="practice-card">
              <p className="practice-meta muted small">
                {tossup.set_name} {tossup.year && `(${tossup.year})`} · {tossup.category}
                {tossup.difficulty !== null && ` · D${tossup.difficulty}`}
              </p>

              <div className="reader" aria-live="polite">
                {words.slice(0, shown).map((w, i) => (
                  <span key={i}>
                    {w}
                    {buzzAt === i && <span className="buzz-mark"> &#x1F514;</span>}
                    {tossup.power_word !== null && i === tossup.power_word - 1 && pastPower(tossup.power_word, shown) && (
                      <span className="power">(*)</span>
                    )}{' '}
                  </span>
                ))}
                {(phase === 'result' || phase === 'countdown') && shown >= words.length && phase === 'result' && null}
              </div>

              {phase === 'reading' && (
                <div className="controls">
                  <button className="primary practice-buzz-btn" onClick={buzz}>Buzz (space)</button>
                </div>
              )}

              {phase === 'countdown' && (
                <div className="controls practice-countdown-controls">
                  <button className="primary practice-buzz-btn" onClick={buzz}>Buzz (space)</button>
                  <div className="countdown-ring">
                    <svg viewBox="0 0 40 40" className="countdown-svg">
                      <circle cx="20" cy="20" r="17" className="countdown-track" />
                      <circle cx="20" cy="20" r="17" className="countdown-fill"
                        strokeDasharray={`${(countdown / COUNTDOWN_SECONDS) * 106.8} 106.8`} />
                    </svg>
                    <span className="countdown-number">{countdown}</span>
                  </div>
                </div>
              )}

              {phase === 'answering' && (
                <form className="controls" onSubmit={e => { e.preventDefault(); void submit(buzzAt, answer) }}>
                  <input ref={input} type="text" aria-label="Your answer" value={answer}
                         onChange={e => setAnswer(e.target.value)} placeholder="Your answer"
                         className="practice-answer-input" />
                  <button className="primary" type="submit">Answer</button>
                  {result?.result === 'prompt' && <span className="result-prompt">Prompt: be more specific</span>}
                </form>
              )}

              {phase === 'result' && result && (
                <div className="practice-result">
                  <div className="practice-result-header">
                    <span className={`result-${result.result === 'no_buzz' ? 'incorrect' : result.result}`}>
                      {result.result === 'correct' ? 'Correct' : result.result === 'no_buzz' ? 'No buzz' : 'Incorrect'}
                    </span>
                    {result.in_power && result.result === 'correct' && <span className="practice-power-tag">Power!</span>}
                    {lastPoints !== null && lastPoints > 0 && (
                      <span className="practice-points-earned">+{lastPoints} pts</span>
                    )}
                    {result.judged_by === 'self' && <span className="muted small"> · your call</span>}
                  </div>
                  <p className="practice-answer-reveal"><strong>Answer:</strong> {tossup.answer}</p>
                  <div className="controls practice-result-controls">
                    <button className="primary" onClick={next}>Next question</button>
                    {result.buzz_id !== null && result.result !== 'no_buzz' && (
                      result.result === 'correct'
                        ? <button onClick={() => override('incorrect')}>I was wrong</button>
                        : <button onClick={() => override('correct')}>I was right</button>
                    )}
                  </div>
                  {tossup.topic_id && (
                    <AddCardPanel
                      tossup={tossup}
                      words={words}
                      buzzAt={buzzAt}
                      wasIncorrect={result.result === 'incorrect' || result.result === 'no_buzz'}
                    />
                  )}
                  {tossup.topic_id && (
                    <div className="practice-topic-link-wrapper">
                      <TopicLinkButton topicId={tossup.topic_id} />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right sidebar: score ── */}
        <aside className="practice-sidebar">
          <div className="sidebar-card practice-score-card">
            <h3 className="sidebar-title">Score</h3>
            <div className="score-display">
              <span className="score-current">{score}</span>
            </div>
            <div className="score-high">
              Best: <strong>{highScore}</strong>
            </div>
            <div className="score-legend">
              <div className="score-legend-row">
                <span className="score-dot score-dot-power" />
                <span>Before power mark</span>
                <strong>30 pts</strong>
              </div>
              <div className="score-legend-row">
                <span className="score-dot score-dot-normal" />
                <span>After power mark</span>
                <strong>15 pts</strong>
              </div>
              <div className="score-legend-row">
                <span className="score-dot score-dot-last" />
                <span>Last line</span>
                <strong>10 pts</strong>
              </div>
            </div>
            <button className="practice-new-game" onClick={newGame}>Start New Game</button>
          </div>
        </aside>
      </div>
    </div>
  )
}

function clueSpanText(question: string, clue: ClueSpan): string {
  const w = question.split(/\s+/).filter(Boolean)
  return w.slice(clue.word_start, clue.word_end).join(' ')
}

function AddCardPanel({
  tossup, buzzAt, wasIncorrect,
}: {
  tossup: Tossup
  words: string[]
  buzzAt: number | null
  wasIncorrect: boolean
}) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(() => {
    if (!wasIncorrect || buzzAt === null) return new Set()
    const buzzedClue = tossup.clues.find(
      c => c.kind === 'clue' && c.word_start <= buzzAt && buzzAt < c.word_end,
    )
    return buzzedClue ? new Set([buzzedClue.ordinal]) : new Set()
  })
  const [adding, setAdding] = useState(false)
  const [added, setAdded] = useState(false)

  const clueLines = tossup.clues.filter(c => c.kind === 'clue')
  if (clueLines.length === 0) return null

  const toggle = (ordinal: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(ordinal)) next.delete(ordinal); else next.add(ordinal)
      return next
    })
  }

  const addCards = async () => {
    if (!tossup.topic_id || selected.size === 0) return
    setAdding(true)
    const lines = clueLines
      .filter(c => selected.has(c.ordinal))
      .map(c => clueSpanText(tossup.question, c))
    try {
      await api.createClueCards(tossup.topic_id, lines, tossup.answer, 'from practice')
      setAdded(true)
    } catch {}
    setAdding(false)
  }

  if (added) {
    return (
      <div className="add-card-panel">
        <span className="add-card-done">Added {selected.size} flashcard{selected.size > 1 ? 's' : ''}</span>
      </div>
    )
  }

  return (
    <div className="add-card-panel">
      {!open ? (
        <button className="add-card-toggle" onClick={() => setOpen(true)}>
          + Add flashcard{clueLines.length > 1 ? 's' : ''}
        </button>
      ) : (
        <>
          <p className="add-card-hint muted small">Select lines to make into flashcards:</p>
          <ul className="add-card-lines">
            {clueLines.map(c => {
              const text = clueSpanText(tossup.question, c)
              return (
                <li key={c.ordinal}>
                  <label className="add-card-line-label">
                    <input
                      type="checkbox"
                      checked={selected.has(c.ordinal)}
                      onChange={() => toggle(c.ordinal)}
                    />
                    <span className={c.in_power ? 'add-card-power' : undefined}>
                      {text}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
          <div className="add-card-actions">
            <button
              className="primary"
              disabled={selected.size === 0 || adding}
              onClick={addCards}
            >
              {adding ? 'Adding…' : `Add ${selected.size} card${selected.size !== 1 ? 's' : ''}`}
            </button>
            <button onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </>
      )}
    </div>
  )
}

function TopicLinkButton({ topicId }: { topicId: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div className="topic-link-split" ref={ref}>
      <button
        className="topic-link-btn"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        About this answer
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 5l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <div className="topic-link-dropdown">
          <Link to={`/topic/${encodeURIComponent(topicId)}`} onClick={() => setOpen(false)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            Non-AI
          </Link>
          <Link to={`/topic/${encodeURIComponent(topicId)}?ai=1`} onClick={() => setOpen(false)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z" />
              <path d="M6 10v1a6 6 0 0 0 12 0v-1" /><line x1="12" y1="18" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </svg>
            AI-Enhanced
          </Link>
        </div>
      )}
    </div>
  )
}
