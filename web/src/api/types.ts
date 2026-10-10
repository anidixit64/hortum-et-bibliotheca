// Shapes returned by the catalog and study services (see docs/ARCHITECTURE.md).

export interface SearchResult {
  id: string
  name: string
  category: string | null
  description: string | null
  n_tossups: number
  matched_alias: string
  score: number
}

export interface Heatmap {
  position_hist: number[] // 10 bins from lead-in to end
  share_in_power: number
  share_last_line: number
  difficulty: Record<string, number>
  years: [number | null, number | null]
  trend: 'rising' | 'steady' | 'fading'
}

export interface Clue {
  rank: number
  cluster_id: number
  label: string
  text: string
  examples: string[]
  n_sets: number
  n_tossups: number
  impact: number
  median_position: number
  heatmap: Heatmap
}

export interface Related {
  id: string
  name: string
  rank: number
  why: string
  n_questions: number
  n_reverse: number
  example: { clue_id: number; tossup_id: string; text: string }
}

export interface Confusion {
  id: string
  name: string
  rank: number
  reasons: ('reject' | 'same_name' | 'lookalike')[]
  evidence: {
    reject?: { tossup_id: string; text: string }[]
    n_rejects?: number
    same_name?: string
    lookalike?: [string, string]
  }
  distinguishing_clues: { this: string[]; other: string[] }
}

export interface TimelineEvent {
  id: string
  label: string
  event: string
  time: string | null
  precision: number | null // Wikidata: 9 year, 10 month, 11 day
  is_topic: boolean
}

export interface MapPoint {
  id: string
  label: string
  place: string
  kind: string
  lat: number
  lon: number
  role: 'topic' | 'related'
}

export interface TopicRecord {
  schema_version: number
  topic: {
    id: string
    slug: string
    name: string
    wikidata_qid: string | null
    wikipedia_title: string | null
    description: string | null
    category: string | null
    aliases: string[]
    stats: {
      n_tossups: number
      n_sets: number
      difficulty: [number | null, number | null]
      years: [number | null, number | null]
    }
    thin: boolean
  }
  clues: Clue[]
  related: Related[]
  confusions: Confusion[]
  timeline: TimelineEvent[]
  map: MapPoint[]
  tossup_ids: string[]
}

export interface ClueSpan {
  ordinal: number
  kind: 'clue' | 'giveaway' | 'note'
  word_start: number
  word_end: number
  in_power: boolean
  cluster_id: number | null
}

export interface Tossup {
  id: string
  set_name: string | null
  year: number | null
  difficulty: number | null
  category: string | null
  subcategory: string | null
  question: string
  power_word: number | null
  answer: string
  answer_html: string | null
  topic_id: string | null
  clues: ClueSpan[]
}

export type BuzzResult = 'correct' | 'incorrect' | 'no_buzz' | 'prompt'

export interface BuzzOut {
  buzz_id: number | null
  result: BuzzResult
  recorded: boolean
  judged_by: 'auto' | 'self'
  position: number | null
  clue_ordinal: number | null
  in_power: boolean
  answer: string
  missed_cards: number
}

export interface DueCard {
  card_id: string
  topic_id: string
  kind: 'clue' | 'reverse' | 'missed'
  front: string
  back: string
  due: string
}

export interface BuzzStats {
  buzzes: number
  correct: number
  accuracy: number | null
  median_correct_position: number | null
  power_rate: number | null
}

export interface TopicStats {
  topic_id: string
  followed: boolean
  cards: number
  due: number
  buzzing: BuzzStats
  buzzed_clusters: Record<string, number>
}

export interface FollowedTopic {
  topic_id: string
  name: string
  cards: number
  due: number
}

export interface Stats {
  followed_topics: number
  cards: number
  due: number
  reviews_today: number
  buzzing: BuzzStats
}
