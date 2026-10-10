"""Educational videos from YouTube: allowlisted channels, 4–40 minutes, ranked without an LLM.

Needs a YouTube Data API key. Quota is 10,000 units a day; a search costs 100 and a video
lookup 1, so a topic costs ~100–200 units.
"""

import re
from typing import Any

from content.fetchers import Topic, Unavailable
from content.http import PoliteClient
from hortum_common.text import normalize

VERSION = 1
SEARCH = "https://www.googleapis.com/youtube/v3/search"
VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
EDUCATION_CATEGORY = "27"
MIN_SECONDS, MAX_SECONDS = 4 * 60, 40 * 60
KEEP = 3
HINTS = {
    "Science": "science",
    "History": "history",
    "Literature": "literature",
    "Fine Arts": "art",
    "Philosophy": "philosophy",
    "Religion": "religion",
    "Mythology": "mythology",
    "Geography": "geography",
    "Social Science": "explained",
}
_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def seconds(iso: str) -> int:
    """ISO 8601 duration ("PT12M30S") -> seconds."""
    match = _DURATION.fullmatch(iso or "")
    if not match:
        return 0
    d, h, m, s = (int(x) if x else 0 for x in match.groups())
    return d * 86400 + h * 3600 + m * 60 + s


def query(topic: Topic) -> str:
    hint = HINTS.get(topic.category or "", "")
    return f"{topic.name} {hint}".strip()


def fetch(topic: Topic, http: PoliteClient, api_key: str, channels: list[str]) -> dict[str, Any]:
    if not api_key:
        raise Unavailable("no YouTube API key configured (CONTENT_YOUTUBE_API_KEY)")
    priority = {normalize(c): i for i, c in enumerate(channels)}
    base = {
        "part": "snippet",
        "type": "video",
        "videoEmbeddable": "true",
        "maxResults": 50,
        "q": query(topic),
        "key": api_key,
    }
    found: dict[str, dict[str, Any]] = {}
    for extra in ({}, {"videoCategoryId": EDUCATION_CATEGORY}):
        for item in http.get_json(SEARCH, {**base, **extra}).get("items", []):
            snippet, vid = item["snippet"], item["id"].get("videoId")
            allowed = normalize(snippet.get("channelTitle", "")) in priority
            if vid and vid not in found and (allowed or extra):
                found[vid] = {
                    "id": vid,
                    "title": snippet["title"],
                    "channel": snippet["channelTitle"],
                    "allowlisted": allowed,
                }
        if sum(v["allowlisted"] for v in found.values()) >= 2:
            break  # enough from trusted channels: skip the second (100-unit) search
    if not found:
        return {"videos": []}
    details = http.get_json(
        VIDEOS,
        {"part": "contentDetails,statistics", "id": ",".join(list(found)[:50]), "key": api_key},
    )
    name_words = set(normalize(topic.name).split())
    videos = []
    for item in details.get("items", []):
        video = found.get(item["id"])
        if video is None:
            continue
        length = seconds(item["contentDetails"]["duration"])
        if not MIN_SECONDS <= length <= MAX_SECONDS:
            continue
        title_words = set(normalize(video["title"]).split())
        title_match = bool(name_words) and name_words <= title_words
        if not video["allowlisted"] and not title_match:
            continue  # from the wider Education search: only if it's plainly about the topic
        videos.append(
            {
                **video,
                "seconds": length,
                "views": int(item.get("statistics", {}).get("viewCount", 0)),
                "title_match": title_match,
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "embed": f"https://www.youtube-nocookie.com/embed/{item['id']}",
            }
        )
    videos.sort(
        key=lambda v: (
            not v["allowlisted"],
            priority.get(normalize(v["channel"]), len(priority)),
            not v["title_match"],
            -v["views"],
        )
    )
    return {"videos": videos[:KEEP]}
