import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { BuzzOut, Tossup } from '../api/types'
import { msPerWord, pastPower, words as split } from '../lib/reveal'

type Phase = 'loading' | 'reading' | 'answering' | 'result' | 'empty'

const WPM_KEY = 'hortum.wpm'

export function PracticePage() {
  const [params] = useSearchParams()
  const topic = params.get('topic') ?? undefined
  const category = params.get('category') ?? undefined
  const [wpm, setWpm] = useState(() => Number(localStorage.getItem(WPM_KEY)) || 200)
  const [tossup, setTossup] = useState<Tossup | null>(null)
  const [shown, setShown] = useState(0)
  const [phase, setPhase] = useState<Phase>('loading')
  const [buzzAt, setBuzzAt] = useState<number | null>(null)
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<BuzzOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seen = useRef<string[]>([])
  const input = useRef<HTMLInputElement>(null)

  const words = tossup ? split(tossup.question) : []

  const load = useCallback(() => {
    api
      .practiceNext({ topic, category, exclude: seen.current })
      .then((t) => {
        seen.current = [...seen.current, t.id]
        setTossup(t)
        setPhase('reading')
      })
      .catch((e: Error & { status?: number }) => {
        if (e.status === 404) setPhase('empty')
        else setError(e.message)
      })
  }, [topic, category])

  useEffect(load, [load])

  const next = () => {
    setPhase('loading')
    setTossup(null)
    setShown(0)
    setBuzzAt(null)
    setAnswer('')
    setResult(null)
    setError(null)
    load()
  }
  useEffect(() => localStorage.setItem(WPM_KEY, String(wpm)), [wpm])

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
        }
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [tossup, words.length],
  )

  // Reveal one word at a time; reading to the end without a buzz records "no buzz".
  useEffect(() => {
    if (phase !== 'reading' || !tossup) return
    const timer = setTimeout(() => {
      if (shown >= words.length) void submit(null)
      else setShown((n) => n + 1)
    }, msPerWord(wpm))
    return () => clearTimeout(timer)
  }, [phase, shown, tossup, words.length, wpm, submit])

  const buzz = useCallback(() => {
    if (phase !== 'reading') return
    setBuzzAt(Math.max(shown - 1, 0))
    setPhase('answering')
    setTimeout(() => input.current?.focus(), 0)
  }, [phase, shown])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' && phase === 'reading') {
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
    setResult({ ...result, result: judgment, judged_by: 'self' })
  }

  if (error) return <p className="error">{error}</p>
  if (phase === 'empty')
    return (
      <div className="card">
        <p>No more questions match. <Link to="/">Search another topic</Link>.</p>
      </div>
    )
  if (!tossup) return <p className="muted">Loading a question…</p>

  return (
    <div className="card">
      <p className="muted small">
        {tossup.set_name} {tossup.year && `(${tossup.year})`} · {tossup.category}
        {topic && <> · practicing <Link to={`/topic/${encodeURIComponent(topic)}`}>this topic</Link></>}
      </p>
      <div className="reader" aria-live="polite">
        {words.slice(0, shown).map((w, i) => (
          <span key={i}>
            {w}
            {buzzAt === i && <span className="buzz-mark"> 🔔</span>}
            {tossup.power_word !== null && i === tossup.power_word - 1 && pastPower(tossup.power_word, shown) && (
              <span className="power">(*)</span>
            )}{' '}
          </span>
        ))}
        {phase === 'result' && shown < words.length && <span className="unread">{words.slice(shown).join(' ')}</span>}
      </div>

      {phase === 'reading' && (
        <div className="controls">
          <button className="primary" onClick={buzz}>Buzz (space)</button>
          <label className="small muted">
            Speed {wpm} wpm{' '}
            <input type="range" min={100} max={400} step={20} value={wpm}
                   onChange={(e) => setWpm(Number(e.target.value))} />
          </label>
        </div>
      )}

      {phase === 'answering' && (
        <form className="controls" onSubmit={(e) => { e.preventDefault(); void submit(buzzAt, answer) }}>
          <input ref={input} type="text" aria-label="Your answer" value={answer}
                 onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer" />
          <button className="primary" type="submit">Answer</button>
          {result?.result === 'prompt' && <span className="result-prompt">Prompt: be more specific</span>}
        </form>
      )}

      {phase === 'result' && result && (
        <div>
          <p>
            <span className={`result-${result.result === 'no_buzz' ? 'incorrect' : result.result}`}>
              {result.result === 'correct' ? 'Correct' : result.result === 'no_buzz' ? 'No buzz' : 'Incorrect'}
            </span>
            {result.in_power && result.result === 'correct' && ' · in power'}
            {result.judged_by === 'self' && ' · your call'}
            {result.missed_cards > 0 && ` · ${result.missed_cards} new flashcard${result.missed_cards > 1 ? 's' : ''}`}
          </p>
          <p><strong>Answer:</strong> {tossup.answer}</p>
          <div className="controls">
            <button className="primary" onClick={next}>Next question</button>
            {result.buzz_id !== null && result.result !== 'no_buzz' && (
              result.result === 'correct'
                ? <button onClick={() => override('incorrect')}>I was wrong</button>
                : <button onClick={() => override('correct')}>I was right</button>
            )}
            {tossup.topic_id && <Link to={`/topic/${encodeURIComponent(tossup.topic_id)}`}>About this answer</Link>}
          </div>
        </div>
      )}
    </div>
  )
}
