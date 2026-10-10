"""The Wikipedia article's text: lead and main sections, for reading and (Phase 6) grounding."""

import re
from typing import Any

from content.fetchers import Topic, Unavailable
from content.http import PoliteClient

VERSION = 1
API = "https://en.wikipedia.org/w/api.php"
MAX_CHARS = 24_000  # ~6k tokens
SKIP_SECTIONS = {
    "see also",
    "references",
    "external links",
    "notes",
    "further reading",
    "bibliography",
    "sources",
    "citations",
    "works cited",
    "footnotes",
    "gallery",
    "notes and references",
}
_HEADING = re.compile(r"^(={2,})\s*(.+?)\s*\1\s*$", re.M)


def sections(extract: str) -> tuple[str, list[dict[str, Any]]]:
    """Plain-text extract with ``== Heading ==`` lines -> lead and top-level sections."""
    parts = _HEADING.split(extract)
    lead, out = parts[0].strip(), []
    for i in range(1, len(parts) - 2, 3):
        level, heading, body = len(parts[i]), parts[i + 1], parts[i + 2].strip()
        if level == 2:
            out.append({"heading": heading, "text": body})
        elif out:
            out[-1]["text"] = f"{out[-1]['text']}\n\n{heading}\n{body}".strip()
    return lead, [s for s in out if s["heading"].lower() not in SKIP_SECTIONS and s["text"]]


def fetch(topic: Topic, http: PoliteClient) -> dict[str, Any]:
    if not topic.wikipedia_title:
        raise Unavailable("no Wikipedia article for this topic")
    data = http.get_json(
        API,
        {
            "action": "query",
            "prop": "extracts|info",
            "explaintext": 1,
            "exsectionformat": "wiki",
            "inprop": "url",
            "redirects": 1,
            "titles": topic.wikipedia_title,
            "format": "json",
            "formatversion": 2,
        },
    )
    page = data["query"]["pages"][0]
    if page.get("missing") or not page.get("extract"):
        raise Unavailable(f"no article text for {topic.wikipedia_title!r}")
    lead, body = sections(page["extract"])
    kept, used = [], len(lead)
    for section in body:
        if used >= MAX_CHARS:
            break
        text = section["text"][: MAX_CHARS - used]
        kept.append({"heading": section["heading"], "text": text})
        used += len(text)
    return {
        "title": page["title"],
        "url": page.get("fullurl") or f"https://en.wikipedia.org/wiki/{page['title']}",
        "lead": lead,
        "sections": kept,
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": f"Text from the Wikipedia article “{page['title']}”, by its contributors.",
    }
