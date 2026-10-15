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
ILLUSTRATIONS = 2
MAX_SEARCHES = 4
MAX_SEARCH_WORDS = 8
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


def _image_record(title: str, ii: dict[str, Any], *, main: bool) -> dict[str, Any] | None:
    """One Commons file as the page stores it, or nothing when it is too small to show."""
    if not str(ii.get("mime", "")).startswith("image/") or ii.get("width", 0) < MIN_WIDTH:
        return None
    meta = {k: v.get("value", "") for k, v in ii.get("extmetadata", {}).items()}
    return {
        "file": title,
        "url": ii.get("thumburl") or ii["url"],
        "width": ii.get("thumbwidth") or ii["width"],
        "height": ii.get("thumbheight") or ii["height"],
        "page": ii.get("descriptionurl"),
        "caption": _text(meta.get("ImageDescription")),
        "artist": _text(meta.get("Artist"), 120),
        "license": meta.get("LicenseShortName") or meta.get("UsageTerms") or "see file page",
        "license_url": meta.get("LicenseUrl") or None,
        "attribution_required": meta.get("AttributionRequired") == "true",
        "is_main": main,
    }


def _file_title(pageimage: str | None) -> str | None:
    """A Wikipedia pageimage name as a File title, skipping logos and icons."""
    if not pageimage:
        return None
    title = f"File:{pageimage.replace('_', ' ')}"
    if _CHROME.search(title) or title.lower().endswith(".svg"):
        return None
    return title


def _pages_for(names: list[str], payload: dict[str, Any]) -> list[dict[str, Any] | None]:
    """Pages in ``names`` order, following Wikipedia's normalization and redirects."""
    query = payload.get("query") or {}
    normalized = {item["from"]: item["to"] for item in query.get("normalized") or []}
    redirects = {item["from"]: item["to"] for item in query.get("redirects") or []}
    by_title = {page.get("title"): page for page in query.get("pages") or []}

    def resolve(name: str) -> str:
        title = normalized.get(name, name)
        seen: set[str] = set()
        while title in redirects and title not in seen:
            seen.add(title)
            title = redirects[title]
        return title

    return [by_title.get(resolve(name)) for name in names]


def _describe(http: PoliteClient, files: list[str]) -> dict[str, dict[str, Any]]:
    """Image records keyed by File title."""
    if not files:
        return {}
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
    out: dict[str, dict[str, Any]] = {}
    for title in files:
        page = by_title.get(title.replace("_", " ")) or by_title.get(title)
        if not page:
            continue
        record = _image_record(title, page["imageinfo"][0], main=False)
        if record:
            out[title] = record
    return out


def illustrations(names: list[str], http: PoliteClient) -> list[dict[str, Any]]:
    """Up to two images of the named examples, spread across the list.

    An exact Wikipedia title is preferred. A short name with no article is searched.
    Logos, icons, and tiny files are left out.
    """
    cleaned: list[str] = []
    for raw in names:
        name = " ".join(str(raw).replace("|", " ").split())[:120]
        if name and name not in cleaned:
            cleaned.append(name)
    cleaned = cleaned[:8]
    if not cleaned:
        return []
    pages = _pages_for(
        cleaned,
        http.get_json(
            API,
            {
                "action": "query",
                "titles": "|".join(cleaned),
                "redirects": 1,
                "prop": "pageimages",
                "piprop": "name",
                "format": "json",
                "formatversion": 2,
            },
        ),
    )
    found: dict[str, str] = {}
    seen: set[str] = set()
    missing: list[str] = []
    for name, page in zip(cleaned, pages, strict=True):
        title = _file_title(None if page is None or page.get("missing") else page.get("pageimage"))
        if title and title not in seen:
            seen.add(title)
            found[name] = title
        elif title is None:
            missing.append(name)
    searches = 0
    if len(found) < ILLUSTRATIONS:
        for name in missing:
            if len(found) >= ILLUSTRATIONS or searches >= MAX_SEARCHES:
                break
            if len(name.split()) > MAX_SEARCH_WORDS:
                continue
            searches += 1
            searched = http.get_json(
                API,
                {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": name,
                    "gsrlimit": 1,
                    "gsrnamespace": 0,
                    "prop": "pageimages",
                    "piprop": "name",
                    "format": "json",
                    "formatversion": 2,
                },
            )
            hits = (searched.get("query") or {}).get("pages") or []
            title = _file_title(hits[0].get("pageimage") if hits else None)
            if title and title not in seen:
                seen.add(title)
                found[name] = title
    ordered = [(name, found[name]) for name in cleaned if name in found]
    described = _describe(http, [title for _, title in ordered])
    kept = [(name, described[title]) for name, title in ordered if title in described]
    if len(kept) > ILLUSTRATIONS:
        last = len(kept) - 1
        kept = [kept[round(i * last / (ILLUSTRATIONS - 1))] for i in range(ILLUSTRATIONS)]
    return [{"name": name, "image": image} for name, image in kept]


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
        record = _image_record(
            title,
            p["imageinfo"][0],
            main=title == f"File:{str(page.get('pageimage')).replace('_', ' ')}",
        )
        if record:
            images.append(record)
        if len(images) == MAX_IMAGES:
            break
    return {"images": images}
