import io

import numpy as np
from PIL import Image

from content import theme


def test_oklab_round_trip() -> None:
    for color in ("#2f6f5e", "#b5651d", "#ffffff", "#000000", "#123456"):
        assert (
            theme.rgb_to_hex(theme.oklab_to_rgb(theme.rgb_to_oklab(theme.hex_to_rgb(color))))
            == color
        )


def test_fix_contrast_keeps_hue_and_meets_the_ratio() -> None:
    fixed = theme.fix_contrast("#7fc4ad", "#ffffff", 4.5)  # a pale green on white: too light
    assert theme.contrast(fixed, "#ffffff") >= 4.5
    hue = lambda c: np.degrees(np.arctan2(*theme.rgb_to_oklab(theme.hex_to_rgb(c))[[2, 1]]))  # noqa: E731
    assert abs(hue(fixed) - hue("#7fc4ad")) < 12
    assert theme.contrast(theme.fix_contrast("#333333", "#15171a", 7), "#15171a") >= 7


def test_palette_finds_the_dominant_colors() -> None:
    picture = Image.new("RGB", (60, 60), (200, 30, 30))
    picture.paste((20, 60, 200), (0, 0, 20, 60))  # a third blue
    data = io.BytesIO()
    picture.save(data, "PNG")
    colors = theme.palette(data.getvalue(), k=3)
    assert colors[0]["hex"] == "#c81e1e" and abs(colors[0]["share"] - 2 / 3) < 0.02
    assert colors[1]["hex"] == "#143cc8"


def test_problem_and_finish() -> None:
    light = {t: "#f7f6f2" for t in theme.TOKENS} | {"text": "#cccccc", "muted": "#dddddd",
                                                    "accent": "#7fc4ad"}  # fmt: skip
    dark = {t: "#15171a" for t in theme.TOKENS} | {"text": "#444444", "muted": "#333333",
                                                   "accent": "#2f6f5e"}  # fmt: skip
    data = {"light": light, "dark": dark, "font": "classical-serif"}
    assert theme.problem(data) is None
    assert "hex" in str(theme.problem({**data, "light": {**light, "bg": "white"}}))
    assert "lighter" in str(theme.problem({**data, "light": dark, "dark": light}))
    done = theme.finish(data)
    for mode in ("light", "dark"):
        colors = done[mode]
        assert theme.contrast(colors["text"], colors["surface"]) >= 7
        assert theme.contrast(colors["muted"], colors["bg"]) >= 4.5
        assert theme.contrast(colors["accent"], colors["surface"]) >= 4.5
