import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TopicContent } from '../api/types'

const POLL_MS = 3000
const MAX_POLLS = 100 // five minutes (first-open writing takes 2-3): past that the worker is down

/** The topic's fetched and written content, polling while the worker is still filling it
 *  in; ``refresh`` starts polling again (after asking for more, say). */
export function useTopicContent(
  topicId: string,
  generate: boolean,
): [TopicContent | null, () => void] {
  const [loaded, setLoaded] = useState<TopicContent | null>(null)
  const [round, setRound] = useState(0)

  useEffect(() => {
    if (!topicId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = (polls: number) => {
      api
        .content(topicId, generate)
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
  }, [topicId, generate, round])

  const refresh = useCallback(() => setRound((r) => r + 1), [])
  return [topicId && loaded?.topic_id === topicId ? loaded : null, refresh]
}
