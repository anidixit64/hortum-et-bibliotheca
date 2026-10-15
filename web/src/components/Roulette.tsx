import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { RouletteTopic } from '../api/types'
import { buildReel, pickWinner, RIM, spinDelays, topicBlurb } from '../lib/roulette'

function reduceMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function Roulette() {
  const [rim, setRim] = useState<RouletteTopic[]>([])
  const [current, setCurrent] = useState<RouletteTopic | null>(null)
  const [phase, setPhase] = useState<'loading' | 'spinning' | 'landed'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [turn, setTurn] = useState(0)
  const [tickMs, setTickMs] = useState(40)
  const spinId = useRef(0)

  const draw = useCallback(async () => {
    const id = ++spinId.current
    setPhase('loading')
    setError(null)
    try {
      const found = await api.roulette()
      if (id !== spinId.current) return
      const winner = pickWinner(found)
      if (!winner) {
        setRim([])
        setCurrent(null)
        setError('No topics to draw from yet.')
        setPhase('landed')
        return
      }
      const reel = buildReel(found, winner.topic_id)
      const delays = spinDelays(reel.length)
      setRim(found.slice(0, RIM))
      if (reduceMotion()) {
        setCurrent(winner)
        setTurn(reel.length - 1)
        setPhase('landed')
        return
      }
      setPhase('spinning')
      for (let i = 0; i < reel.length; i++) {
        if (id !== spinId.current) return
        setCurrent(reel[i])
        setTurn(i)
        setTickMs(delays[i])
        const wait = import.meta.env.MODE === 'test' ? 0 : delays[i]
        await new Promise((resolve) => window.setTimeout(resolve, wait))
      }
      if (id !== spinId.current) return
      setCurrent(winner)
      setPhase('landed')
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

  const slice = rim.length ? 360 / rim.length : 36
  const spinning = phase === 'spinning'

  return (
    <div className="roulette-panel">
      <div className="roulette-stage" aria-hidden={phase === 'landed'}>
        <span className="roulette-pointer" />
        <div
          className="roulette-wheel"
          style={{
            transform: `rotate(${-turn * slice}deg)`,
            transitionDuration: spinning ? `${tickMs}ms` : '0ms',
          }}
        >
          <div
            className="roulette-disc"
            style={{
              background: rim.length
                ? `conic-gradient(${rim.map((_, i) => {
                    const tone = i % 2 === 0 ? '#d9d4cc' : '#b7b1a8'
                    const start = (i / rim.length) * 100
                    const end = ((i + 1) / rim.length) * 100
                    return `${tone} ${start}% ${end}%`
                  }).join(', ')})`
                : '#d9d4cc',
            }}
          />
          {rim.map((topic, i) => (
            <span
              key={topic.topic_id}
              className="roulette-label"
              style={{ transform: `rotate(${i * slice}deg) translateY(-118px)` }}
            >
              {topic.name}
            </span>
          ))}
        </div>
        <div className="roulette-hub">
          <span>{spinning ? current?.name : phase === 'loading' ? 'Drawing…' : ''}</span>
        </div>
      </div>

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
