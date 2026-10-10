// The browser talks only to the gateway: /api/catalog/..., /api/content/... and /api/study/...
import type {
  BuzzOut,
  DueCard,
  FollowedTopic,
  SearchResult,
  Stats,
  TopicContent,
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

export const api = {
  search: (q: string, limit = 10) =>
    request<SearchResult[]>(catalog(`/search?${new URLSearchParams({ q, limit: String(limit) })}`)),
  topic: (key: string) => request<TopicRecord>(catalog(`/topics/${encodeURIComponent(key)}`)),
  practiceNext: (f: PracticeFilter) => {
    const params = new URLSearchParams()
    if (f.topic) params.set('topic', f.topic)
    if (f.category) params.set('category', f.category)
    if (f.difficultyMin !== undefined) params.set('difficulty_min', String(f.difficultyMin))
    if (f.difficultyMax !== undefined) params.set('difficulty_max', String(f.difficultyMax))
    if (f.exclude?.length) params.set('exclude', f.exclude.join(','))
    return request<Tossup>(catalog(`/practice/next?${params}`))
  },

  content: (topicId: string) =>
    request<TopicContent>(content(`/topics/${encodeURIComponent(topicId)}/content`)),

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
  due: (limit = 100) => request<DueCard[]>(study(`/reviews/due?limit=${limit}`)),
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
}
