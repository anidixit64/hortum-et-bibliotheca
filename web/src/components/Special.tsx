import type { FeatureStep, SpecialPayload } from '../api/types'

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

export function Feature({ special }: { special: SpecialPayload }) {
  const { feature, source } = special
  const entries = feature.entries?.filter((entry) => entry.name && entry.text) ?? []
  const diagram = feature.steps.length >= 2
  return (
    <article className="feature">
      <h3>{feature.title}</h3>
      {feature.dramatized && !diagram && (
        <p className="muted small">
          A dramatized scene: the events, people and places are real; the atmosphere is imagined.
        </p>
      )}
      {entries.length > 0 ? (
        <ol className="handful">
          {entries.map((entry) => (
            <li key={entry.name}>
              <strong>{entry.name}</strong>
              <p className="prose">{entry.text}</p>
            </li>
          ))}
        </ol>
      ) : (
        !diagram &&
        feature.body.split(/\n\s*\n/).filter(Boolean).map((p, i) => (
          <p key={i} className="prose">{p}</p>
        ))
      )}
      <StepDiagram steps={feature.steps} />
      {source && (
        <p className="muted small attribution">
          Written by AI from <a href={source.url} target="_blank" rel="noreferrer">“{source.title}”</a>{' '}
          (CC BY-SA 4.0).
        </p>
      )}
    </article>
  )
}
