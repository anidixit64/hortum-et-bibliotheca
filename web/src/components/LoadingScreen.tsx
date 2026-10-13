import type { FormEvent } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { BuzzOut, Tossup } from '../api/types'
import { msPerWord, pastPower, words as split } from '../lib/reveal'

const IMAGES = Array.from({ length: 8 }, (_, i) => `/loading/${i + 1}.png`)

interface Props {
  topicId?: string
  progress: number // 0-1
  topicName?: string
}

// --- Mini practice game ---------------------------------------------------

type MiniPhase = 'loading' | 'reading' | 'answering' | 'result' | 'empty'

function MiniPractice({ topicId }: { topicId?: string }) {
  const [tossup, setTossup] = useState<Tossup | null>(null)
  const [shown, setShown] = useState(0)
  const [phase, setPhase] = useState<MiniPhase>('loading')
  const [buzzAt, setBuzzAt] = useState<number | null>(null)
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<BuzzOut | null>(null)
  const seen = useRef<string[]>([])
  const input = useRef<HTMLInputElement>(null)
  const wpm = 200

  const words = tossup ? split(tossup.question) : []

  const load = useCallback(() => {
    setPhase('loading')
    setTossup(null)
    setShown(0)
    setBuzzAt(null)
    setAnswer('')
    setResult(null)
    api
      .practiceNext({ topic: topicId, exclude: seen.current })
      .then((t) => {
        seen.current = [...seen.current, t.id]
        setTossup(t)
        setPhase('reading')
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) setPhase('empty')
      })
  }, [topicId])

  useEffect(load, [load])

  const submit = useCallback(
    async (wordIndex: number | null, given?: string) => {
      if (!tossup) return
      try {
        const out = await api.buzz({
          tossup_id: tossup.id,
          word_index: wordIndex,
          answer_given: given,
        })
        setResult(out)
        if (out.result === 'prompt') {
          setAnswer('')
          input.current?.focus()
        } else {
          setShown(words.length)
          setPhase('result')
        }
      } catch {
        // ignore errors in mini game
      }
    },
    [tossup, words.length],
  )

  useEffect(() => {
    if (phase !== 'reading' || !tossup) return
    const timer = setTimeout(() => {
      if (shown >= words.length) void submit(null)
      else setShown((n) => n + 1)
    }, msPerWord(wpm))
    return () => clearTimeout(timer)
  }, [phase, shown, tossup, words.length, submit])

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

  if (phase === 'empty') return <p className="muted small">No questions available.</p>
  if (!tossup) return <p className="muted small">Loading question...</p>

  return (
    <div className="mini-practice">
      <p className="muted small mini-meta">
        {tossup.category} {tossup.year && `(${tossup.year})`}
      </p>
      <div className="mini-reader" aria-live="polite">
        {words.slice(0, shown).map((w, i) => (
          <span key={i}>
            {w}
            {buzzAt === i && <span className="buzz-mark"> *</span>}
            {tossup.power_word !== null &&
              i === tossup.power_word - 1 &&
              pastPower(tossup.power_word, shown) && <span className="power">(*)</span>}{' '}
          </span>
        ))}
      </div>

      {phase === 'reading' && (
        <button className="primary mini-buzz" onClick={buzz}>
          Buzz (space)
        </button>
      )}

      {phase === 'answering' && (
        <form
          className="mini-answer"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            void submit(buzzAt, answer)
          }}
        >
          <input
            ref={input}
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Your answer"
          />
          <button className="primary" type="submit">
            Answer
          </button>
          {result?.result === 'prompt' && <span className="muted small">Be more specific</span>}
        </form>
      )}

      {phase === 'result' && result && (
        <div className="mini-result">
          <span className={`result-${result.result === 'no_buzz' ? 'incorrect' : result.result}`}>
            {result.result === 'correct'
              ? 'Correct!'
              : result.result === 'no_buzz'
                ? 'No buzz'
                : 'Incorrect'}
          </span>
          <span className="mini-answer-text">
            Answer: <strong>{tossup.answer}</strong>
          </span>
          <button className="primary" onClick={load}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}

// --- Main loading screen --------------------------------------------------

export function LoadingScreen({ topicId, progress }: Props) {
  const image = useMemo(() => IMAGES[Math.floor(Math.random() * IMAGES.length)], [])
  const [playing, setPlaying] = useState(false)

  if (playing) {
    return (
      <div className="loading-screen">
        <button className="loading-back" onClick={() => setPlaying(false)}>
          Back to loading
        </button>
        <MiniPractice topicId={topicId} />
      </div>
    )
  }

  return (
    <div className="loading-screen">
      <div className="loading-orbit">
        <img src={image} alt="" className="loading-image" draggable={false} />
      </div>
      <div className="loading-bar-track">
        <div className="loading-bar-fill" style={{ width: `${Math.max(progress * 100, 3)}%` }} />
      </div>
      <p className="muted small loading-hint">
        {progress < 0.8 ? 'Curating this exhibit...' : 'Finishing touches...'}
      </p>
      <button className="loading-play" onClick={() => setPlaying(true)}>
        Practice while you wait
      </button>
    </div>
  )
}
