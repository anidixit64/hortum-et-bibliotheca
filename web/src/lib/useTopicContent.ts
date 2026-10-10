import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TopicContent } from '../api/types'

const POLL_MS = 3000
const MAX_POLLS = 40 // two minutes: past that the worker is down or backed off

/** The topic's fetched content, polling while the worker is still filling it in. */
export function useTopicContent(topicId: string): TopicContent | null {
  const [loaded, setLoaded] = useState<TopicContent | null>(null)

  useEffect(() => {
    if (!topicId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = (polls: number) => {
      api
        .content(topicId)
        .then((c) => {
          if (cancelled) return
          setLoaded(c)
          if (c.status === 'partial' && polls < MAX_POLLS) {
            timer = setTimeout(() => load(polls + 1), POLL_MS)
          }
        })
        .catch(() => {
          // content service offline: the sections just stay hidden
        })
    }
    load(0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [topicId])

  return topicId && loaded?.topic_id === topicId ? loaded : null
}
