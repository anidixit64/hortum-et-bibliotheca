import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { RouletteTopic } from '../api/types'
import { buildStrip, CELL_PX, landingIndex, pickWinner, reelOffset, SPIN_MS, topicBlurb, WINDOW } from '../lib/roulette'

function reduceMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function skipMotion() {
  return reduceMotion() || import.meta.env.MODE === 'test'
}

export function Roulette() {
  const [strip, setStrip] = useState<RouletteTopic[]>([])
  const [current, setCurrent] = useState<RouletteTopic | null>(null)
  const [phase, setPhase] = useState<'loading' | 'spinning' | 'landed'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [instant, setInstant] = useState(true)
  const windowRef = useRef<HTMLDivElement>(null)
  const spinId = useRef(0)

  const draw = useCallback(async () => {
    const id = ++spinId.current
    setPhase('loading')
    setError(null)
    setInstant(true)
    setOffset(0)
    try {
      const found = await api.roulette()
      if (id !== spinId.current) return
      const winner = pickWinner(found)
      if (!winner) {
        setStrip([])
        setCurrent(null)
        setError('No topics to draw from yet.')
        setPhase('landed')
        return
      }
      const next = buildStrip(found, winner.topic_id)
      const endIndex = landingIndex(next)
      const height = windowRef.current?.clientHeight || WINDOW * CELL_PX
      const start = reelOffset(Math.floor(WINDOW / 2), height)
      const end = reelOffset(endIndex, height)
      setStrip(next)
      setCurrent(winner)
      setOffset(start)
      if (skipMotion()) {
        setOffset(end)
        setPhase('landed')
        return
      }
      setPhase('spinning')
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      if (id !== spinId.current) return
      setInstant(false)
      setOffset(end)
      window.setTimeout(() => {
        if (id === spinId.current) setPhase('landed')
      }, SPIN_MS + 400)
    } catch {
      if (id !== spinId.current) return
      setCurrent(null)
      setError('Could not draw a topic.')
      setPhase('landed')
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void draw() }, 0)
    return () => {
      window.clearTimeout(timer)
      spinId.current += 1
    }
  }, [draw])

  return (
    <div className="roulette-panel">
      <div className="reel-window" ref={windowRef} aria-hidden={phase !== 'landed'}>
        <div className="reel-line" />
        <div
          className={instant ? 'reel-strip instant' : 'reel-strip'}
          style={{ transform: `translateY(${offset}px)` }}
        >
          {strip.map((topic, index) => (
            <div className="reel-cell" key={`${topic.topic_id}-${index}`}>
              {topic.category && <span>{topic.category}</span>}
              <strong>{topic.name}</strong>
            </div>
          ))}
        </div>
      </div>

      {phase === 'loading' && !current && <p className="roulette-status">Drawing…</p>}

      {phase === 'landed' && current && (
        <div className="roulette-result">
          {current.category && <p className="roulette-kicker">{current.category}</p>}
          <h2>{current.name}</h2>
          <p className="roulette-blurb">{topicBlurb(current)}</p>
          <div className="roulette-actions">
            <Link to={`/topic/${encodeURIComponent(current.topic_id)}`}>
              <button type="button" className="primary">Learn more</button>
            </Link>
            <button type="button" onClick={() => { void draw() }}>Spin again</button>
          </div>
        </div>
      )}
      {phase === 'landed' && error && (
        <div className="roulette-result">
          <p className="error">{error}</p>
          <button type="button" onClick={() => { void draw() }}>Spin again</button>
        </div>
      )}
    </div>
  )
}

/** The spinning reel over a dimmed page, with a way back to Explore. */
export function RouletteLayer({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div className="palette-backdrop roulette-backdrop" />
      <div className="roulette-layer" role="dialog" aria-modal="true" aria-label="Random topic">
        <button type="button" className="roulette-back" onClick={onClose}>
          ← Explore
        </button>
        <Roulette />
      </div>
    </>
  )
}
