"""Topic colors: a palette pulled from the header image, colors chosen by a model, and
contrast enforced in code.

Code extracts the image's dominant colors (k-means in OKLab, a space where distances match
how different colors look). The model chooses light and dark color sets that suit the
topic and blend with the header image, plus a font pairing from a fixed list. Code then
makes every text color readable (WCAG AA) by changing only its lightness, so the hue and
saturation the model chose survive.
"""

import io
import re
from typing import Any

import numpy as np
from PIL import Image

THEME_VERSION = 5
TOKENS = ("bg", "surface", "text", "muted", "accent", "accent2", "accent_soft", "header_tint")
FONT_PAIRINGS = {
    "classical-serif": "Old-style serif (Palatino, Iowan): history, classics, literature",
    "modern-sans": "Clean sans-serif (system UI): science, technology, current events",
    "humanist": "Humanist sans (Optima, Gill Sans): philosophy, social science, religion",
    "elegant-serif": "High-contrast serif (Didot, Bodoni): fine arts, fashion, opera",
    "geometric": "Geometric sans (Futura, Avenir): architecture, design, modern art",
    "slab": "Slab serif (Rockwell): American history, industry, sports",
    "typewriter": "Typewriter (American Typewriter, Courier): modern literature, journalism",
}
# The site's own colors (web/src/index.css): a topic's theme must look different from them.
DEFAULT_ACCENT = {"light": "#2f6f5e", "dark": "#7fc4ad"}
MIN_BG_CHROMA = 0.012  # OKLab chroma: below this a background reads as plain grey
MIN_ACCENT_DISTANCE = 0.08  # OKLab distance from the default accent
# Minimum contrast ratios (WCAG AA): body text, secondary text, links and accents.
CONTRAST = {"text": 7.0, "muted": 4.5, "accent": 4.5}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# --- color math ---------------------------------------------------------------------------


def hex_to_rgb(color: str) -> np.ndarray:
    return np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)], dtype=float) / 255


def rgb_to_hex(rgb: np.ndarray) -> str:
    r, g, b = (np.clip(rgb, 0, 1) * 255).round().astype(int)
    return f"#{r:02x}{g:02x}{b:02x}"


def to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def from_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])  # fmt: skip
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])  # fmt: skip


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    lms = to_linear(rgb) @ _M1.T
    lab: np.ndarray = np.cbrt(lms) @ _M2.T
    return lab


def oklab_to_rgb(lab: np.ndarray) -> np.ndarray:
    lms = (lab @ np.linalg.inv(_M2).T) ** 3
    return from_linear(lms @ np.linalg.inv(_M1).T)


def chroma(color: str) -> float:
    _, a, b = rgb_to_oklab(hex_to_rgb(color))
    return float(np.hypot(a, b))


def distance(x: str, y: str) -> float:
    return float(np.linalg.norm(rgb_to_oklab(hex_to_rgb(x)) - rgb_to_oklab(hex_to_rgb(y))))


def luminance(color: str) -> float:
    r, g, b = to_linear(hex_to_rgb(color))
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def fix_contrast(fg: str, bg: str, minimum: float) -> str:
    """``fg`` with its OKLab lightness moved away from ``bg`` until the contrast is met;
    hue and saturation stay (chroma shrinks only if the color leaves the sRGB gamut)."""
    if contrast(fg, bg) >= minimum:
        return fg
    lab = rgb_to_oklab(hex_to_rgb(fg))
    darker = luminance(bg) > 0.18  # light background: darken the text
    for step in range(1, 101):
        trial = lab.copy()
        trial[0] = np.clip(lab[0] + (-1 if darker else 1) * step * 0.01, 0, 1)
        for shrink in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0):
            candidate = trial * np.array([1, shrink, shrink])
            rgb = oklab_to_rgb(candidate)
            if np.all((rgb >= -0.002) & (rgb <= 1.002)):
                color = rgb_to_hex(rgb)
                if contrast(color, bg) >= minimum:
                    return color
                break
    return "#000000" if darker else "#ffffff"


# --- palette from an image --------------------------------------------------------------


def palette(image: bytes, k: int = 6, seed: int = 7) -> list[dict[str, Any]]:
    """The image's dominant colors, largest share first: [{"hex", "share"}]."""
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    picture.thumbnail((96, 96))
    pixels = np.asarray(picture, dtype=float).reshape(-1, 3) / 255
    lab = rgb_to_oklab(pixels)
    rng = np.random.default_rng(seed)
    centers = lab[rng.choice(len(lab), size=min(k, len(lab)), replace=False)]
    for _ in range(20):
        labels = np.argmin(((lab[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        for i in range(len(centers)):
            if np.any(labels == i):
                centers[i] = lab[labels == i].mean(axis=0)
    counts = np.bincount(labels, minlength=len(centers))
    order = np.argsort(-counts)
    return [
        {
            "hex": rgb_to_hex(oklab_to_rgb(centers[i])),
            "share": round(float(counts[i] / len(lab)), 3),
        }
        for i in order
        if counts[i]
    ]


# --- the request and its checks ---------------------------------------------------------

SYSTEM = """You are a museum exhibit designer choosing the color palette for a single \
gallery room. Every surface in the room — walls, display cases, label cards, accent \
lighting — must feel like the topic. A visitor walking in should sense the subject before \
reading a word. Be bold and specific: a palette should feel like one particular thing, \
not a safe middle ground. First envision 2-3 colors that embody the atmosphere, aesthetic \
and era of the topic, and 2-3 colors that accent and highlight aspects the topic is known \
for. For a polar topic, stark whites and deep icy purples with aurora green and pink; for \
the Aztec Empire, jade, terracotta, obsidian, gold and turquoise; for a Romantic poet, \
stormy indigos, candlelight gold and ink-black. Then map those into a coherent page \
scheme. Text stays easy to read."""

PROMPT = """Topic: {name} (category: {category})
Opening of the page: {hook}
Header image: {caption}
Dominant colors of the header image (hex, share of the image): {palette}
{related_colors}
First think of 5-6 colors that REPRESENT this topic — what a designer would put in a \
mood board. Then map them into two color sets, "light" and "dark", each with these hex \
colors:
- bg: page background, clearly tinted with the topic's character (light: a pale version \
of a topic color; dark: a deep, rich version), never plain grey, white or black
- surface: card background, slightly lifted from bg, with the same tint
- text: body text (near-neutral, very readable on surface)
- muted: secondary text
- accent: links and highlights drawn from the topic's palette — the most evocative color
- accent2: a second color from the topic palette that complements accent
- accent_soft: a pale (light) or deep (dark) tint of accent for highlighted boxes
- header_tint: the color the header image fades into (close to bg)
Then pick "font" from: {fonts}
Then write "blurb": two sentences explaining why you picked these colors — what aspect \
of the topic each color evokes.
The site's default scheme is grey with a teal-green accent ({default}); this page must \
look distinctly different from it. The colors should feel like the topic — someone seeing \
only the colors should guess the subject. Avoid plain grey schemes and garish neon."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "light": {"type": "object", "properties": {t: {"type": "string"} for t in TOKENS},
                  "required": list(TOKENS)},
        "dark": {"type": "object", "properties": {t: {"type": "string"} for t in TOKENS},
                 "required": list(TOKENS)},
        "font": {"type": "string", "enum": list(FONT_PAIRINGS)},
        "blurb": {"type": "string"},
    },
    "required": ["light", "dark", "font", "blurb"],
}  # fmt: skip


def problem(data: dict[str, Any]) -> str | None:
    for mode in ("light", "dark"):
        colors = data.get(mode) or {}
        bad = [t for t in TOKENS if not _HEX.match(str(colors.get(t, "")))]
        if bad:
            return f"{mode} colors {bad} aren't #rrggbb hex"
    if data.get("font") not in FONT_PAIRINGS:
        return "font must be one of the listed pairings"
    if luminance(data["light"]["bg"]) < luminance(data["dark"]["bg"]):
        return "the light set's background must be lighter than the dark set's"
    for mode in ("light", "dark"):
        if chroma(data[mode]["bg"]) < MIN_BG_CHROMA:
            return f"the {mode} bg {data[mode]['bg']} is plain grey: give it a visible tint"
        if distance(data[mode]["accent"], DEFAULT_ACCENT[mode]) < MIN_ACCENT_DISTANCE:
            return (
                f"the {mode} accent is too close to the site's default teal "
                f"{DEFAULT_ACCENT[mode]}: choose a different hue"
            )
    return None


def enforce(colors: dict[str, str]) -> dict[str, str]:
    """Readable text on both backgrounds: text, muted and accent fixed against the darker
    or lighter of bg and surface, whichever is harder."""
    out = {k: v.lower() for k, v in colors.items()}
    for token, minimum in CONTRAST.items():
        for ground in ("surface", "bg"):
            out[token] = fix_contrast(out[token], out[ground], minimum)
    return out


def finish(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "light": enforce(data["light"]),
        "dark": enforce(data["dark"]),
        "font": data["font"],
    }
    if data.get("blurb"):
        out["blurb"] = str(data["blurb"]).strip()
    return out
