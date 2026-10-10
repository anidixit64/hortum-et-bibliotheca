"""Images from the Wikipedia article, each with its license and credit."""

import html
import re
from typing import Any

from content.fetchers import Topic, Unavailable
from content.http import PoliteClient

VERSION = 1
API = "https://en.wikipedia.org/w/api.php"
MAX_IMAGES = 10
MIN_WIDTH = 300
# Interface and project images: icons, logos, flags of convenience, stub badges.
_CHROME = re.compile(
    r"icon|logo|symbol|flag of|commons-|wiki(?:quote|source|data|species|books|news|versity)|"
    r"padlock|question book|ambox|portal|stub|edit-|disambig|crystal clear|nuvola|"
    r"folder hexagonal|increase2|decrease|steady|red pog|blue pog",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")


def _text(value: str | None, limit: int = 300) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", value or "")).split())[:limit]


def candidates(page_images: list[str], main: str | None) -> list[str]:
    """File titles worth looking at: the main image first, no interface chrome or SVG icons."""
    files = [f"File:{main.replace('_', ' ')}"] if main else []
    for title in page_images:
        if title not in files and not _CHROME.search(title) and not title.lower().endswith(".svg"):
            files.append(title)
    return files[:20]


def fetch(topic: Topic, http: PoliteClient) -> dict[str, Any]:
    if not topic.wikipedia_title:
        raise Unavailable("no Wikipedia article for this topic")
    page = http.get_json(
        API,
        {
            "action": "query",
            "prop": "pageimages|images",
            "piprop": "name",
            "imlimit": 50,
            "redirects": 1,
            "titles": topic.wikipedia_title,
            "format": "json",
            "formatversion": 2,
        },
    )["query"]["pages"][0]
    files = candidates([i["title"] for i in page.get("images", [])], page.get("pageimage"))
    if not files:
        return {"images": []}
    info = http.get_json(
        API,
        {
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 800,
            "titles": "|".join(files),
            "format": "json",
            "formatversion": 2,
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|"
            "AttributionRequired|UsageTerms",
        },
    )["query"]["pages"]
    by_title = {p["title"]: p for p in info if p.get("imageinfo")}
    images = []
    for title in files:
        p = by_title.get(title.replace("_", " ")) or by_title.get(title)
        if not p:
            continue
        ii = p["imageinfo"][0]
        if not str(ii.get("mime", "")).startswith("image/") or ii.get("width", 0) < MIN_WIDTH:
            continue
        meta = {k: v.get("value", "") for k, v in ii.get("extmetadata", {}).items()}
        images.append(
            {
                "file": title,
                "url": ii.get("thumburl") or ii["url"],
                "width": ii.get("thumbwidth") or ii["width"],
                "height": ii.get("thumbheight") or ii["height"],
                "page": ii.get("descriptionurl"),
                "caption": _text(meta.get("ImageDescription")),
                "artist": _text(meta.get("Artist"), 120),
                "license": meta.get("LicenseShortName")
                or meta.get("UsageTerms")
                or "see file page",
                "license_url": meta.get("LicenseUrl"),
                "attribution_required": meta.get("AttributionRequired") == "true",
                "is_main": title == f"File:{str(page.get('pageimage')).replace('_', ' ')}",
            }
        )
        if len(images) == MAX_IMAGES:
            break
    return {"images": images}
