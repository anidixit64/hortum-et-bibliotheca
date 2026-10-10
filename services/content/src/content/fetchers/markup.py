"""Just enough wikitext handling to read citations: templates, links, formatting."""

import html
import re

_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_EXTERNAL = re.compile(r"\[https?://\S+\s+([^\]]*)\]")
_TAG = re.compile(r"<[^>]+>")
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S)
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


def templates(text: str, name: str) -> list[str]:
    """The bodies of every ``{{name ...}}`` template, nested braces and all."""
    out = []
    pattern = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*\|", re.I)
    for match in pattern.finditer(text):
        depth, i = 2, match.end()
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth, i = depth + 2, i + 2
            elif text.startswith("}}", i):
                depth, i = depth - 2, i + 2
            else:
                i += 1
        out.append(text[match.end() : i - 2])
    return out


def params(body: str) -> dict[str, str]:
    """``last=Bell |first=David |title=...`` -> dict, splitting only at top-level pipes."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        if body.startswith(("{{", "[["), i):
            depth += 1
        elif body.startswith(("}}", "]]"), i):
            depth -= 1
        elif ch == "|" and depth <= 0:
            parts.append(body[start:i])
            start = i + 1
    parts.append(body[start:])
    out = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep:
            out[key.strip().lower()] = plain(value)
    return out


def plain(text: str) -> str:
    """Wikitext -> plain text: links to their labels, no formatting, tags or refs."""
    text = _REF.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _EXTERNAL.sub(r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = _TAG.sub("", text).replace("'''", "").replace("''", "")
    return " ".join(html.unescape(text).split()).strip(" ,;")


def year(text: str) -> int | None:
    match = _YEAR.search(text or "")
    return int(match.group(1)) if match else None
