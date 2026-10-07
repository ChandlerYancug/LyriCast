# -*- coding: utf-8 -*-
"""回归测试：彩胶“按专辑封面主色自动配”（vinyl.for_cover_color / cover_rgb）。

- 走素色系、确定性（同一颜色永远同一款）；
- 封面取色要抓“最鲜艳的那部分”，不被大片灰底冲淡。

跑法（项目根目录）：
    python tests/test_vinyl_color.py
    pytest tests/test_vinyl_color.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402

from vinyl import for_cover_color, cover_rgb  # noqa: E402


def test_tone_mapping_cases():
    cases = (
        ((235, 60, 50), "red"),            # 正红封面 → 正红胶
        ((240, 170, 180), "clear-red"),    # 淡粉 → 透明红
        ((18, 18, 20), "black"),           # 很暗 → 经典黑胶
        ((110, 112, 120), "smoke"),        # 中性灰 → 烟熏
        ((242, 240, 236), "white"),        # 亮白 → 白胶
        ((230, 166, 63), "amber"),         # 橙黄 → 琥珀
        ((35, 120, 72), "green"),          # 深绿 → 森林绿
        ((143, 220, 205), "clear-sea"),    # 薄荷/青 → 海玻璃
        ((180, 215, 240), "clear"),        # 淡蓝 → 水晶
        ((30, 25, 50), "galaxy"),          # 暗蓝紫 → 星云
        ((120, 75, 190), "purple"),        # 紫 → 霓紫
    )
    for rgb, want in cases:
        got = for_cover_color(rgb)["id"]
        assert got == want, (rgb, got, want)


def test_tone_mapping_is_deterministic():
    for rgb in ((200, 40, 40), (10, 10, 10), (90, 200, 160)):
        assert for_cover_color(rgb)["id"] == for_cover_color(rgb)["id"]


def test_tone_mapping_clamps_bad_values():
    assert for_cover_color((-20, 300, 999))["id"]
    assert for_cover_color((0, 0, 0))["id"] == "black"


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
    test_tone_mapping_cases,
    test_tone_mapping_is_deterministic,
    test_tone_mapping_clamps_bad_values,
    test_cover_rgb_picks_the_colorful_part,
    test_cover_rgb_transparent_image,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
