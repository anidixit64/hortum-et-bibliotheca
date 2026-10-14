import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Clue, SectionPayloads, TopicLink, TopicRecord, TopicStats, WikiPayload } from '../api/types'
import { ClueCarousel, sortedClues } from '../components/ClueList'
import type { SortMode } from '../components/ClueList'
import { FloatImage, ImageGrid, Reading, Videos, WikiArticle } from '../components/Enrichment'
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
import { useAiMode } from '../lib/aiMode'
import { wikiNote } from '../lib/wikiNote'

const PAGE = 10 // clues shown at first
const MORE = 5 // added by each "show more"

function ExhibitGenerating() {
  return <p className="exhibit-generating">exhibit generating...</p>
}

function isPending(section: { status: string; stale?: boolean } | undefined) {
  return section?.status === 'pending' || section?.stale === true
}

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
  const ai = useAiMode()
  const released = useRef(false)
  const topicKey = useRef(key)
  if (topicKey.current !== key) {
    topicKey.current = key
    released.current = !ai
  }
  if (!ai) released.current = true
  const [loaded, setLoaded] = useState<{ key: string; record: TopicRecord } | null>(null)
  const [stats, setStats] = useState<TopicStats | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState<{ key: string; clues: Clue[] }>({ key: '', clues: [] })
  const [visible, setVisible] = useState<{ key: string; n: number }>({ key: '', n: PAGE })
  const [sortMode, setSortMode] = useState<SortMode>('frequency')
  const [loadingMore, setLoadingMore] = useState(false)
  const current = loaded?.key === key ? loaded.record : null
  const [content, refreshContent] = useTopicContent(current?.topic.id ?? '', ai)
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
  useTopicTheme(ai ? topicTheme : null)
  const cleanedSection = content?.sections.clues
  const cleaned =
    cleanedSection?.status === 'ok'
      ? (cleanedSection.payload as SectionPayloads['clues']).clues
      : null

  const blurbsSection = content?.sections.blurbs
  const blurbs =
    ai && blurbsSection?.status === 'ok'
      ? (blurbsSection.payload as SectionPayloads['blurbs']).blurbs
      : []
  const wikiSection = content?.sections.wiki
  const wiki =
    wikiSection?.status === 'ok' ? (wikiSection.payload as WikiPayload) : null

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

  // AI mode waits on the loader until every generated section is stored. Non-AI opens on
  // the catalog and Wikipedia. Turning AI on from that page keeps it up and fills the
  // sections in place.
  const contentReady = content?.status === 'ready'
  if (!record || (ai && !released.current && !contentReady)) {
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
  // After cleanup the hall is the valid clues only. Show more walks that list in the
  // active order, so rarity is the rarest of all of them, not the rarest of the first 10.
  const pool = cleaned ? applyCleanup(raw, cleaned) : raw
  const ordered = sortedClues(pool, sortMode, null)
  const total = cleaned ? ordered.length : rawTotal
  const n = visible.key === key ? visible.n : PAGE
  const shown = ordered.slice(0, n)
  const articleNotes: Record<number, ReturnType<typeof wikiNote>> = {}
  for (const clue of shown) {
    articleNotes[clue.rank] = wiki ? wikiNote(clue.label, clue.variants ?? [], wiki) : null
  }
  const showMore = async () => {
    if (!cleaned && n + MORE > pool.length && raw.length < rawTotal) {
      setLoadingMore(true)
      try {
        const next = await api.moreClues(topic.id, raw.length, n + MORE - pool.length)
        setMore({ key, clues: [...extra, ...next] })
      } finally {
        setLoadingMore(false)
      }
    }
    setVisible({ key, n: n + MORE })
    if (ai && cleaned && explanations.length < cleaned.length) {
      api
        .explainMore(topic.id, cleaned.length)
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
            {written && ai && <Hook summary={written} />}
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
            {ai && written ? (
              <Summary summary={written} explanations={explanations} topicLinks={topicLinks} />
            ) : (
              <>
                {ai && isPending(summarySection) && <ExhibitGenerating />}
                <WikiArticle section={wikiSection} />
              </>
            )}
          </section>

          {/* Fun facts — museum plaques scattered in the main flow */}
          {ai && facts && facts.facts.length > 0 && (
            <aside className="plaque-row" aria-label="Did you know?">
              <h2>Did you know?</h2>
              <FunFacts facts={facts.facts} />
            </aside>
          )}
          {ai && !facts && isPending(factsSection) && (
            <aside className="plaque-row" aria-label="Did you know?">
              <h2>Did you know?</h2>
              <ExhibitGenerating />
            </aside>
          )}

          {ai && special && (
            <section className="exhibit-feature" id="room-feature">
              {featureFloat && <FloatImage image={featureFloat} side="left" />}
              <Feature special={special} />
            </section>
          )}
          {ai && !special && isPending(specialSection) && (
            <section className="exhibit-feature" id="room-feature">
              <ExhibitGenerating />
            </section>
          )}

        </div>

        {/* Right sidebar: timeline, reading */}
        <aside className="museum-sidebar museum-right">
          {(hasExhibitTimeline || hasWikidataTimeline || (ai && isPending(specialSection))) && (
            <SidebarCard title={special?.timeline.kind === 'discoveries' ? 'Discoveries' : 'Timeline'}>
              {ai && isPending(specialSection) && <ExhibitGenerating />}
              {ai && hasExhibitTimeline && special ? (
                <ExhibitTimeline timeline={special.timeline} />
              ) : (
                hasWikidataTimeline && <Timeline events={record.timeline} />
              )}
            </SidebarCard>
          )}
        </aside>
      </div>

      <section className="exhibit-clues" id="room-clues">
        <h2><span className="room-number">C</span> The clue hall</h2>
        {ai && isPending(explainedSection) && <ExhibitGenerating />}
        <ClueCarousel
          clues={shown}
          explanations={ai && cleaned ? explanations : undefined}
          writing={false}
          topicLinks={topicLinks}
          topicName={topic.name}
          topicId={topic.id}
          images={images}
          sortMode={sortMode}
          onSortMode={setSortMode}
          articleNotes={articleNotes}
          wikiLoaded={wiki !== null}
        />
        {shown.length < total && (
          <button onClick={showMore} disabled={loadingMore}>
            {loadingMore ? 'Loading...' : `Show ${Math.min(MORE, total - shown.length)} more`}
          </button>
        )}
      </section>

      {shown.length > 0 && (
        <section className="exhibit-where" aria-label="Where the clues come up">
          <h2>Where the clues come up</h2>
          <Heatmap clues={shown} buzzed={stats?.buzzed_clusters ?? {}} />
        </section>
      )}

      <section className="exhibit-reading" id="room-reading">
        <h2><span className="room-number">B</span> Bibliography</h2>
        {ai && isPending(blurbsSection) && <ExhibitGenerating />}
        <Reading section={content?.sections.books} blurbs={blurbs} />
      </section>
      <section className="exhibit-connections" id="room-connections">
        <h2><span className="room-number">~</span> Connections</h2>
        <h3>Don't confuse with</h3>
        <ConfusionList confusions={record.confusions} />
      </section>

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
          {ai
            ? 'Summaries, fun facts, explanations, and book notes are AI-generated from Wikipedia and may contain errors. '
            : 'The article text is from Wikipedia. Clues come from the question set. '}
          Images and text are sourced from Wikipedia and Wikimedia Commons under CC BY-SA 4.0.
          Book data from Open Library.
        </p>
      </footer>
    </>
  )
}
