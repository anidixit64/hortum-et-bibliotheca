// The browser talks only to the gateway: /api/catalog/..., /api/content/... and /api/study/...
import type {
  AdminUsage,
  BuzzOut,
  Clue,
  DueCard,
  ExploreResult,
  FollowedTopic,
  SearchResult,
  Stats,
  TopicContent,
  TopicLink,
  TopicRecord,
  TopicStats,
  Tossup,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = (await response.json()).detail ?? detail
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, detail)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

const catalog = (path: string) => `/api/catalog${path}`
const content = (path: string) => `/api/content${path}`
const study = (path: string) => `/api/study${path}`

export interface PracticeFilter {
  topic?: string
  category?: string
  difficultyMin?: number
  difficultyMax?: number
  exclude?: string[]
}

export interface CardFilter {
  limit?: number
  category?: string
  subcategory?: string
  difficultyMin?: number
  difficultyMax?: number
}

function cardQuery(f: CardFilter = {}): string {
  const params = new URLSearchParams()
  if (f.limit !== undefined) params.set('limit', String(f.limit))
  if (f.category) params.set('category', f.category)
  if (f.subcategory) params.set('subcategory', f.subcategory)
  if (f.difficultyMin !== undefined) params.set('difficulty_min', String(f.difficultyMin))
  if (f.difficultyMax !== undefined) params.set('difficulty_max', String(f.difficultyMax))
  const q = params.toString()
  return q ? `?${q}` : ''
}

export const api = {
  search: (q: string, limit = 10) =>
    request<SearchResult[]>(catalog(`/search?${new URLSearchParams({ q, limit: String(limit) })}`)),
  topic: (key: string) => request<TopicRecord>(catalog(`/topics/${encodeURIComponent(key)}`)),
  moreClues: (key: string, offset: number, limit = 5) =>
    request<Clue[]>(
      catalog(`/topics/${encodeURIComponent(key)}/clues?offset=${offset}&limit=${limit}`),
    ),
  practiceNext: (f: PracticeFilter) => {
    const params = new URLSearchParams()
    if (f.topic) params.set('topic', f.topic)
    if (f.category) params.set('category', f.category)
    if (f.difficultyMin !== undefined) params.set('difficulty_min', String(f.difficultyMin))
    if (f.difficultyMax !== undefined) params.set('difficulty_max', String(f.difficultyMax))
    if (f.exclude?.length) params.set('exclude', f.exclude.join(','))
    return request<Tossup>(catalog(`/practice/next?${params}`))
  },

  exploreTop: (opts: {
    category: string
    subcategory?: string
    altSubcategory?: string
    difficultyMin?: number
    difficultyMax?: number
    limit?: number
  }) => {
    const params = new URLSearchParams({ category: opts.category })
    if (opts.subcategory) params.set('subcategory', opts.subcategory)
    if (opts.altSubcategory) params.set('alt_subcategory', opts.altSubcategory)
    if (opts.difficultyMin !== undefined) params.set('difficulty_min', String(opts.difficultyMin))
    if (opts.difficultyMax !== undefined) params.set('difficulty_max', String(opts.difficultyMax))
    if (opts.limit !== undefined) params.set('limit', String(opts.limit))
    return request<ExploreResult[]>(catalog(`/explore/top?${params}`))
  },

  cluesBrief: (topicId: string, limit = 10) =>
    request<{ label: string; count: number }[]>(
      catalog(`/topics/${encodeURIComponent(topicId)}/clues-brief?limit=${limit}`),
    ),

  content: (topicId: string, generate = true) =>
    request<TopicContent>(
      content(`/topics/${encodeURIComponent(topicId)}/content?generate=${generate ? 'true' : 'false'}`),
    ),
  explainMore: (topicId: string, through: number) =>
    request<{ queued: boolean }>(
      content(`/topics/${encodeURIComponent(topicId)}/explain-more?through=${through}`),
      { method: 'POST' },
    ),

  thumbnails: (topicIds: string[]) =>
    request<Record<string, string | null>>(content('/thumbnails'), {
      method: 'POST',
      body: JSON.stringify({ topic_ids: topicIds }),
    }),

  topicLinks: (names: string[], exclude?: string) =>
    request<Record<string, TopicLink>>(catalog('/topics/lookup'), {
      method: 'POST',
      body: JSON.stringify({ names, exclude: exclude ?? null }),
    }),

  createClueCards: (topicId: string, lines: string[], answer: string, clueLabel: string) =>
    request<{ created: number; total: number }>(
      study(`/topics/${encodeURIComponent(topicId)}/clue-cards`),
      { method: 'POST', body: JSON.stringify({ lines, answer, clue_label: clueLabel }) },
    ),

  follow: (topicId: string) =>
    request<{ cards_created: number; cards_total: number }>(
      study(`/topics/${encodeURIComponent(topicId)}/follow`),
      { method: 'POST' },
    ),
  unfollow: (topicId: string) =>
    request<void>(study(`/topics/${encodeURIComponent(topicId)}/follow`), { method: 'DELETE' }),
  followed: () => request<FollowedTopic[]>(study('/topics')),
  topicStats: (topicId: string) =>
    request<TopicStats>(study(`/topics/${encodeURIComponent(topicId)}/stats`)),
  stats: () => request<Stats>(study('/stats')),
  due: (f: CardFilter = {}) => request<DueCard[]>(study(`/reviews/due${cardQuery({ limit: 100, ...f })}`)),
  cards: (f: CardFilter = {}) => request<DueCard[]>(study(`/cards${cardQuery({ limit: 500, ...f })}`)),
  updateCard: (cardId: string, front: string, back: string) =>
    request<DueCard>(study(`/cards/${encodeURIComponent(cardId)}`), {
      method: 'PATCH',
      body: JSON.stringify({ front, back }),
    }),
  deleteCard: (cardId: string) =>
    request<void>(study(`/cards/${encodeURIComponent(cardId)}`), { method: 'DELETE' }),
  review: (cardId: string, rating: 1 | 2 | 3 | 4) =>
    request<{ due: string }>(study('/reviews'), {
      method: 'POST',
      body: JSON.stringify({ card_id: cardId, rating }),
    }),
  buzz: (body: { tossup_id: string; word_index: number | null; answer_given?: string }) =>
    request<BuzzOut>(study('/buzzes'), { method: 'POST', body: JSON.stringify(body) }),
  overrideBuzz: (buzzId: number, result: 'correct' | 'incorrect') =>
    request<{ result: string }>(study(`/buzzes/${buzzId}`), {
      method: 'PATCH',
      body: JSON.stringify({ result }),
    }),

  adminUsage: (pin: string) =>
    request<AdminUsage>(content('/admin/usage'), {
      headers: { 'X-Admin-Pin': pin },
    }),
}
