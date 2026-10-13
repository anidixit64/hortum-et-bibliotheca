import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, SectionPayloads, TopicLink, TopicRecord, TopicStats } from '../api/types'
import { ClueCarousel } from '../components/ClueList'
import { FloatImage, ImageGrid, Reading, Videos, WikiSummary } from '../components/Enrichment'
import { FunFacts, Hook, Summary } from '../components/Written'
import { Heatmap } from '../components/Heatmap'
import { ConfusionList } from '../components/Related'
import { Timeline } from '../components/Timeline'
import { ExhibitTimeline, Feature } from '../components/Special'
import { TopicMap } from '../components/TopicMap'
import { LoadingScreen } from '../components/LoadingScreen'
import { applyCleanup, CLEANED_FROM } from '../lib/cleanClues'
import { extractProperNouns } from '../lib/marks'
import { percent } from '../lib/format'
import { useTopicTheme } from '../lib/theme'
import { HeaderImage } from '../components/HeaderImage'
import { useTopicContent } from '../lib/useTopicContent'

const PAGE = 10 // clues shown at first
const MORE = 5 // added by each "show more"

function SidebarCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <aside className="sidebar-card">
      {title && <h3 className="sidebar-title">{title}</h3>}
      {children}
    </aside>
  )
}

export function TopicPage() {
  const { key = '' } = useParams()
  const [loaded, setLoaded] = useState<{ key: string; record: TopicRecord } | null>(null)
  const [stats, setStats] = useState<TopicStats | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState<{ key: string; clues: Clue[] }>({ key: '', clues: [] })
  const [visible, setVisible] = useState<{ key: string; n: number }>({ key: '', n: PAGE })
  const [loadingMore, setLoadingMore] = useState(false)
  const current = loaded?.key === key ? loaded.record : null
  const [content, refreshContent] = useTopicContent(current?.topic.id ?? '')
  const summarySection = content?.sections.summary
  const written =
    summarySection?.status === 'ok' ? (summarySection.payload as SectionPayloads['summary']) : null
  const explainedSection = content?.sections.explanations
  const explanations =
    explainedSection?.status === 'ok'
      ? (explainedSection.payload as SectionPayloads['explanations']).clues
      : []
  const factsSection = content?.sections.facts
  const specialSection = content?.sections.special
  const special =
    specialSection?.status === 'ok' ? (specialSection.payload as SectionPayloads['special']) : null
  const facts = factsSection?.status === 'ok' ? (factsSection.payload as SectionPayloads['facts']) : null
  const themeSection = content?.sections.theme
  const topicTheme = themeSection?.status === 'ok' ? (themeSection.payload as SectionPayloads['theme']) : null
  useTopicTheme(topicTheme)
  const cleanedSection = content?.sections.clues
  const cleaned =
    cleanedSection?.status === 'ok'
      ? (cleanedSection.payload as SectionPayloads['clues']).clues
      : null

  const imagesSection = content?.sections.images
  const images =
    imagesSection?.status === 'ok'
      ? (imagesSection.payload as SectionPayloads['images']).images
      : []

  // Topic links: proper nouns in the summary + clue labels that are themselves topics.
  const [topicLinks, setTopicLinks] = useState<Record<string, TopicLink>>({})
  const topicId = current?.topic.id
  useEffect(() => {
    if (!topicId) return
    const names: string[] = []
    if (cleaned) names.push(...cleaned.map((c) => c.label))
    if (written) names.push(...extractProperNouns(written.summary))
    if (!names.length) return
    const unique = [...new Set(names)]
    api
      .topicLinks(unique, topicId)
      .then(setTopicLinks)
      .catch(() => setTopicLinks({}))
  }, [topicId, written?.summary, cleaned?.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const needRaw = cleaned !== null && current !== null && more.key !== key
  useEffect(() => {
    if (!needRaw || !current) return
    api
      .moreClues(current.topic.id, current.clues.length, CLEANED_FROM - current.clues.length)
      .then((clues) => setMore({ key, clues }))
      .catch(() => setMore({ key, clues: [] }))
  }, [needRaw, current, key])

  const loadStats = useCallback((id: string) => {
    api.topicStats(id).then(setStats).catch(() => setStats(null))
  }, [])

  useEffect(() => {
    api
      .topic(key)
      .then((r) => {
        setLoaded({ key, record: r })
        document.title = `${r.topic.name} · Museo`
        loadStats(r.topic.id)
      })
      .catch((e: Error) => setError({ key, message: e.message }))
  }, [key, loadStats])

  if (error?.key === key) return <p className="error">{error.message}</p>
  const record = current

  // Generated sections (summary, clues, explanations, facts, theme, special) have to be
  // stored before the exhibit opens. Fetched Wikipedia text is not a stand-in for them.
  const contentReady = content?.status === 'ready'
  if (!record || !contentReady) {
    const sectionKeys = content ? Object.keys(content.sections) : []
    const done = content
      ? sectionKeys.filter((k) => {
          const s = content.sections[k as keyof typeof content.sections]
          return s.status === 'ok' || s.status === 'empty' || s.status === 'unavailable'
        }).length
      : 0
    const total = sectionKeys.length || 10
    const progress = record ? done / total : 0

    return (
      <LoadingScreen
        topicId={record?.topic.id}
        progress={progress}
        topicName={record?.topic.name}
      />
    )
  }

  const { topic } = record

  const extra = more.key === key ? more.clues : []
  const raw = [...record.clues, ...extra]
  const rawTotal = record.n_clues ?? record.clues.length
  const list = cleaned
    ? [...applyCleanup(raw, cleaned), ...raw.filter((c) => c.rank > CLEANED_FROM)]
    : raw
  const total = cleaned ? cleaned.length + Math.max(0, rawTotal - CLEANED_FROM) : rawTotal
  const n = visible.key === key ? visible.n : PAGE
  const shown = list.slice(0, n)
  const showMore = async () => {
    if (n + MORE > list.length && raw.length < rawTotal) {
      setLoadingMore(true)
      try {
        const next = await api.moreClues(topic.id, raw.length, n + MORE - list.length)
        setMore({ key, clues: [...extra, ...next] })
      } finally {
        setLoadingMore(false)
      }
    }
    setVisible({ key, n: n + MORE })
    const through = Math.min(n + MORE, cleaned?.length ?? 0)
    if (cleaned && through > explanations.length) {
      api
        .explainMore(topic.id, through)
        .then(refreshContent)
        .catch(() => {})
    }
  }

  const toggleFollow = async () => {
    setBusy(true)
    try {
      if (stats?.followed) await api.unfollow(topic.id)
      else await api.follow(topic.id)
      loadStats(topic.id)
    } finally {
      setBusy(false)
    }
  }

  // Distribute images across the page like a museum exhibit / DK Eyewitness
  const hasHeader = !!topicTheme?.header
  const scatterPool = hasHeader ? images.filter((img) => !img.is_main) : images
  const summaryFloat = scatterPool[0] ?? null
  const featureFloat = special ? (scatterPool[1] ?? null) : null
  const galleryImages = scatterPool.slice(featureFloat ? 2 : 1)

  // Has a timeline?
  const hasExhibitTimeline = special && special.timeline.events.length >= 3
  const hasWikidataTimeline = !hasExhibitTimeline && record.timeline.length >= 3

  return (
    <>
      {topicTheme?.header && <HeaderImage image={topicTheme.header} />}

      {/* --- Entrance: topic header --- */}
      <header className="card entrance">
        <div className="topic-head">
          <div>
            <p className="exhibit-kicker">{topic.category ?? 'Exhibit'}</p>
            <h1 className="exhibit-sign">{topic.name}</h1>
            {written && <Hook summary={written} />}
            {topic.description && <p className="muted">{topic.description}</p>}
            {topic.thin && <span className="pill">rarely asked</span>}
          </div>
          <div className="topic-actions">
            <Link to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
              <button>Practice</button>
            </Link>
            <button className="primary" onClick={toggleFollow} disabled={busy || stats === null}>
              {stats?.followed ? 'Following' : 'Follow'}
            </button>
          </div>
        </div>
        <div className="stats-row">
          <div><strong>{topic.stats.n_tossups}</strong><span className="muted small">questions</span></div>
          <div><strong>{topic.stats.n_sets}</strong><span className="muted small">sets</span></div>
          <div>
            <strong>{topic.stats.years[0] ?? '?'}-{topic.stats.years[1] ?? '?'}</strong>
            <span className="muted small">years asked</span>
          </div>
          {stats && stats.buzzing.buzzes > 0 && (
            <div><strong>{percent(stats.buzzing.accuracy)}</strong><span className="muted small">your accuracy</span></div>
          )}
          {stats?.followed && (
            <div><strong>{stats.due}</strong><span className="muted small">cards due</span></div>
          )}
        </div>
        {topic.aliases.length > 0 && (
          <p className="muted small">Also: {topic.aliases.join(' · ')}</p>
        )}
      </header>

      {/* --- Museum layout: main + sidebars --- */}
      <div className="museum-layout">

        {/* Left sidebar: map + videos */}
        <aside className="museum-sidebar museum-left">
          {record.map.length > 0 && (
            <SidebarCard title="Map">
              <TopicMap points={record.map} />
            </SidebarCard>
          )}
          {content && (
            <SidebarCard title="Screening room">
              <Videos section={content.sections.videos} />
            </SidebarCard>
          )}
        </aside>

        {/* Center: the main exhibit */}
        <div className="museum-center">
          {/* Summary — the centerpiece, with key image floated alongside */}
          <section className="exhibit-main" id="room-introduction">
            {summaryFloat && <FloatImage image={summaryFloat} side="right" />}
            {written ? (
              <Summary summary={written} explanations={explanations} topicLinks={topicLinks} />
            ) : (
              <WikiSummary section={content.sections.wiki} />
            )}
          </section>

          {/* Fun facts — museum plaques scattered in the main flow */}
          {facts && facts.facts.length > 0 && (
            <aside className="plaque-row" aria-label="Did you know?">
              <h2>Did you know?</h2>
              <FunFacts facts={facts.facts} />
            </aside>
          )}

          {/* Feature piece, with second image floated alongside */}
          {special && (
            <section className="exhibit-feature" id="room-feature">
              {featureFloat && <FloatImage image={featureFloat} side="left" />}
              <Feature special={special} />
            </section>
          )}

          {/* Clue hall — slideshow carousel */}
          <section className="exhibit-clues" id="room-clues">
            <h2><span className="room-number">C</span> The clue hall</h2>
            <ClueCarousel
              clues={shown}
              explanations={cleaned ? explanations : undefined}
              writing={false}
              topicLinks={topicLinks}
              topicName={topic.name}
              topicId={topic.id}
              images={images}
            />
            {shown.length < total && (
              <button onClick={showMore} disabled={loadingMore}>
                {loadingMore ? 'Loading...' : `Show ${Math.min(MORE, total - shown.length)} more`}
              </button>
            )}
            {shown.length > 0 && (
              <>
                <h3>Where the clues come up</h3>
                <Heatmap clues={shown} buzzed={stats?.buzzed_clusters ?? {}} />
              </>
            )}
          </section>

          {/* Connections */}
          <section className="exhibit-connections" id="room-connections">
            <h2><span className="room-number">~</span> Connections</h2>
            <h3>Don't confuse with</h3>
            <ConfusionList confusions={record.confusions} />
          </section>
        </div>

        {/* Right sidebar: timeline, reading */}
        <aside className="museum-sidebar museum-right">
          {hasExhibitTimeline && special && (
            <SidebarCard title={special.timeline.kind === 'discoveries' ? 'Discoveries' : 'Timeline'}>
              <ExhibitTimeline timeline={special.timeline} />
            </SidebarCard>
          )}
          {hasWikidataTimeline && (
            <SidebarCard title="Timeline">
              <Timeline events={record.timeline} />
            </SidebarCard>
          )}
          {content && (
            <SidebarCard title="Library">
              <Reading section={content.sections.books} />
            </SidebarCard>
          )}
        </aside>
      </div>

      {/* Gallery: remaining images in a full-width grid */}
      {galleryImages.length > 0 && (
        <section className="exhibit-gallery">
          <h2><span className="room-number">G</span> Gallery</h2>
          <ImageGrid images={galleryImages} />
        </section>
      )}

      {/* Exit */}
      <section className="card exit">
        <h2>Test yourself</h2>
        <p className="muted">
          Buzz on real questions about {topic.name}, or follow it to get flashcards for the clues you miss.
        </p>
        <div className="controls">
          <Link to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
            <button className="primary">Practice</button>
          </Link>
          <button onClick={toggleFollow} disabled={busy || stats === null}>
            {stats?.followed ? 'Following' : 'Follow'}
          </button>
        </div>
      </section>

      <footer className="page-disclaimer">
        <p>
          Summaries, fun facts, and explanations are AI-generated from Wikipedia and may contain errors.
          Images and text are sourced from Wikipedia and Wikimedia Commons under CC BY-SA 4.0.
          Book data from Open Library.
        </p>
      </footer>
    </>
  )
}
