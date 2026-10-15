import { useState } from 'react'
import type { FeatureStep, SpecialPayload, WikiImage } from '../api/types'

function year(y: number) {
  return y < 0 ? `${-y} BCE` : String(y)
}

/** The Wikipedia-grounded timeline: each event shows the sentence it was taken from. */
export function ExhibitTimeline({ timeline }: { timeline: SpecialPayload['timeline'] }) {
  if (!timeline.events.length) return null
  return (
    <ol className="exhibit-timeline">
      {timeline.events.map((e) => (
        <li key={`${e.year}-${e.label}`}>
          <span className="exhibit-year">{year(e.year)}</span>
          <span title={`From Wikipedia: “${e.source}”`}>{e.label}</span>
        </li>
      ))}
    </ol>
  )
}

/** A concept as a flow of steps, always drawn the same way: boxes joined by arrows. */
export function StepDiagram({ steps }: { steps: FeatureStep[] }) {
  if (steps.length < 2) return null
  return (
    <ol className="step-diagram" aria-label="Diagram">
      {steps.map((s, i) => (
        <li key={`${i}-${s.label}`}>
          <span className="step-number">{i + 1}</span>
          <strong>{s.label}</strong>
          <span className="muted small">{s.detail}</span>
        </li>
      ))}
    </ol>
  )
}

export function Feature({
  special,
  illustrations = {},
}: {
  special: SpecialPayload
  illustrations?: Record<string, WikiImage>
}) {
  const { feature, source } = special
  const entries = feature.entries?.filter((entry) => entry.name && entry.text) ?? []
  const diagram = feature.steps.length >= 2
  const [index, setIndex] = useState(0)
  const safe = entries.length ? Math.min(index, entries.length - 1) : 0
  const entry = entries[safe]
  const image = entry ? illustrations[entry.name] : undefined
  return (
    <article className="feature">
      <h3>{feature.title}</h3>
      {feature.dramatized && !diagram && (
        <p className="muted small">
          A dramatized scene: the events, people and places are real; the atmosphere is imagined.
        </p>
      )}
      {entry ? (
        <div className="example-carousel">
          <div className="clue-slide" key={entry.name}>
            {image && (
              <figure className="float-image float-right clue-img">
                <img src={image.url} alt={image.caption || entry.name} loading="lazy" />
                {image.caption && <figcaption className="muted small">{image.caption}</figcaption>}
              </figure>
            )}
            <p className="clue-slide-rank muted small">
              Example {safe + 1} of {entries.length}
            </p>
            <h3 className="clue-slide-title">{entry.name}</h3>
            <p className="prose">{entry.text}</p>
          </div>
          <nav className="clue-nav" aria-label="Example navigation">
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={safe === 0}
              aria-label="Previous example"
            >
              ←
            </button>
            <span>
              {safe + 1} of {entries.length}
            </span>
            <button
              type="button"
              onClick={() => setIndex((i) => Math.min(entries.length - 1, i + 1))}
              disabled={safe === entries.length - 1}
              aria-label="Next example"
            >
              →
            </button>
          </nav>
        </div>
      ) : (
        !diagram &&
        feature.body.split(/\n\s*\n/).filter(Boolean).map((p, i) => (
          <p key={i} className="prose">{p}</p>
        ))
      )}
      {diagram && (
        <div className="diagram-block">
          <StepDiagram steps={feature.steps} />
          {feature.diagram_blurb?.trim() && (
            <p className="prose diagram-blurb">{feature.diagram_blurb.trim()}</p>
          )}
        </div>
      )}
      {source && (
        <p className="muted small attribution">
          Written by AI from <a href={source.url} target="_blank" rel="noreferrer">“{source.title}”</a>{' '}
          (CC BY-SA 4.0).
        </p>
      )}
    </article>
  )
}
