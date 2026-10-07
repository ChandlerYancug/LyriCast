# -*- coding: utf-8 -*-
"""回归测试：彩胶“按专辑封面主色自动配”（vinyl.tone_family / for_cover_color）。

- 色调定“色系”，族里挑；确定性（同一首歌永远同款）；
- 同一张封面、不同的歌会在色系里换花样（同专辑切歌也看得出唱片换了）；
- 封面取色要抓“最鲜艳的那部分”，不被大片灰底冲淡。

跑法（项目根目录）：
    python tests/test_vinyl_color.py
    pytest tests/test_vinyl_color.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402

from vinyl import BY_ID, _TONE_FAMILIES, cover_rgb, for_cover_color, tone_family  # noqa: E402


def test_tone_family_cases():
    cases = (
        ((235, 60, 50), "red"),            # 正红
        ((240, 170, 180), "pink"),         # 淡粉
        ((18, 18, 20), "dark"),            # 很暗
        ((110, 112, 120), "gray"),         # 中性灰
        ((242, 240, 236), "light"),        # 亮白
        ((230, 166, 63), "warm"),          # 橙黄
        ((35, 120, 72), "green"),          # 深绿
        ((143, 220, 205), "sea"),          # 薄荷 / 青
        ((180, 215, 240), "light"),        # 淡蓝
        ((30, 25, 50), "dark"),            # 暗蓝紫
        ((120, 75, 190), "violet"),        # 紫
    )
    for rgb, want in cases:
        got = tone_family(rgb)
        assert got == want, (rgb, got, want)


def test_family_members_are_real_materials():
    for fam, ids in _TONE_FAMILIES.items():
        assert ids, fam
        for mid in ids:
            assert mid in BY_ID, (fam, mid)


def test_pick_stays_in_family_and_varies_by_song():
    seeds = ["Song %d|Artist" % i for i in range(24)]
    for rgb in ((235, 60, 50), (30, 25, 50), (230, 166, 63), (143, 220, 205)):
        fam = tone_family(rgb)
        ids = {for_cover_color(rgb, s)["id"] for s in seeds}
        assert ids <= set(_TONE_FAMILIES[fam]), (rgb, fam, ids)
        assert len(ids) >= 2, ("同一封面没能换出花样", rgb, ids)


def test_pick_is_deterministic_per_song():
    rgb = (200, 40, 40)
    for seed in ("A|B", "Some Song|Someone", ""):
        assert (for_cover_color(rgb, seed)["id"]
                == for_cover_color(rgb, seed)["id"])


def test_tone_mapping_clamps_bad_values():
    assert for_cover_color((-20, 300, 999))["id"]
    assert for_cover_color((0, 0, 0))["id"] in _TONE_FAMILIES["dark"]


def test_cover_rgb_picks_the_colorful_part():
    img = QImage(16, 16, QImage.Format.Format_ARGB32)
    img.fill(QColor(205, 205, 205))                 # 大片灰底
    p = QPainter(img)
    p.fillRect(0, 0, 7, 7, QColor(225, 40, 40))     # 一小块红
    p.end()
    r, g, b = cover_rgb(img)
    assert r > 150 and r > g + 50 and r > b + 50, (r, g, b)


def test_cover_rgb_transparent_image():
    img = QImage(4, 4, QImage.Format.Format_ARGB32)
    img.fill(0)
    assert cover_rgb(img) == (0, 0, 0)


TESTS = (
    test_tone_family_cases,
    test_family_members_are_real_materials,
    test_pick_stays_in_family_and_varies_by_song,
    test_pick_is_deterministic_per_song,
    test_tone_mapping_clamps_bad_values,
    test_cover_rgb_picks_the_colorful_part,
    test_cover_rgb_transparent_image,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
