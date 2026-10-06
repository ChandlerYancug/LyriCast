# -*- coding: utf-8 -*-
"""回归测试：翻译“汇聚”入场必须是**时间驱动**的（不再跟着填充卡顿）。

背景：主句填充来自逐词时间轴（timing._frac_from_words），词与词的间隙里
填充值会**冻结**。早先版本把翻译的飞行也挂在填充上，于是整行看起来是
“飞一半停住、下一词开始再跳一下”。现在出发时刻仍挂在填充上（与演唱同步），
但飞行本身走播放时间轴 —— 本测试用一段“会停顿的填充”验证：
填充冻结期间，字的位移仍在平滑推进，且逐帧步长有界（没有跳变）。

跑法（项目根目录）：
    python tests/test_trans_converge.py
    pytest tests/test_trans_converge.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPointF, QRectF  # noqa: E402
from PyQt6.QtGui import QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from fullscreen import FullscreenView  # noqa: E402

TRANSLATION = "我的围巾遗落在你那里"
MAIN_LINE = "And I left my scarf there at your sister house"


_APP = None


def _ensure_app():
    """保持 QApplication 的全局引用（只写表达式会被垃圾回收）。"""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class FakePainter(object):
    """只记录 drawText 的“画布”：验证坐标用，不真的画。

    兼容两种调用：框对齐 drawText(QRectF, flags, text) 和
    基线定位 drawText(QPointF, text)；统一记成 (文本, x, y)。
    """

    def __init__(self):
        self.boxes = []          # [(char, x, y), ...]

    # -- 被调用到的方法 -------------------------------------------------- #
    def setFont(self, _f):
        pass

    def setPen(self, *_a):
        pass

    def save(self):
        pass

    def restore(self):
        pass

    def drawText(self, at, *rest):
        text = rest[-1]
        if isinstance(at, QRectF):
            self.boxes.append((text, at.left(), at.top()))
        elif isinstance(at, QPointF):
            self.boxes.append((text, at.x(), at.y()))


def _make_view():
    v = FullscreenView({})
    v.resize(1600, 900)
    v.set_lyrics({"synced": True,
                  "lines": [(0.0, MAIN_LINE, TRANSLATION)],
                  "ends": [8.0]})
    v._ensure_layout()
    return v


def _char_left(boxes, ch):
    """取某个字最后一笔画的框左缘（幽灵描边在前，正文最后画）。"""
    got = [x for (t, x, _y) in boxes if t == ch]
    assert got, "这一帧没有画出 %r" % ch
    return got[-1]


def test_motion_continues_while_fill_is_frozen():
    _ensure_app()
    for n in sorted(os.listdir(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fonts"))):
        if n.lower().endswith((".otf", ".ttf", ".ttc")):
            QFontDatabase.addApplicationFont(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "fonts", n))

    v = _make_view()
    area = v._lyric_area()
    pt_t, rows = v._trans_layout(("trans", 0), TRANSLATION,
                                 v._base_pt * 0.60, area.width())
    font = v._font(pt_t, heavy=True)
    y_top = v._focus_cy() - 10.0

    # 模拟“词刚起唱就拖长 + 词间停顿”：第一个字刚起飞，填充就冻结 0.5 秒
    # （填充驱动的旧实现会在这里完全停住；时间驱动应该继续飞）
    timeline = []
    t = 0.0
    while t < 1.6:
        if t < 0.10:
            frac = 0.055                        # 刚越过第一个字的出发阈值
        elif t < 0.60:
            frac = 0.055                        # ← 填充冻结（词间空隙）
        else:
            frac = 0.055 + (t - 0.60) * 0.60    # 继续推进
        timeline.append((t, min(0.95, frac)))
        t += 1.0 / 60.0

    first_ch = TRANSLATION[0]
    positions = []
    for el, frac in timeline:
        v._frac = frac
        v._elapsed = el
        p = FakePainter()
        v._draw_trans_converge(p, area, font, y_top, v._row_h, rows)
        positions.append((el, _char_left(p.boxes, first_ch)))

    # 1) 填充冻结期间（0.10~0.60s），第一个字仍在移动（时间驱动）
    #    （旧实现把飞行挂在填充上，这里会是 0.00 px）
    frozen = [x for (el, x) in positions if 0.10 <= el <= 0.60]
    moved = max(frozen) - min(frozen)
    assert moved > 4.0, "填充冻结时字没有继续飞: %.2f px" % moved
    # 且方向不回摆（只向前滑入）
    for a, b in zip(frozen, frozen[1:]):
        assert b <= a + 0.01, "冻结期间出现回摆: %.2f -> %.2f" % (a, b)

    # 2) 全程逐帧步长有界（没有“跳一下”）：缓出 + 0.55s，应当 < 6px/帧
    steps = [abs(b - a) for (_el, a), (_e2, b) in zip(positions, positions[1:])]
    assert max(steps) < 6.0, "出现跳变，最大帧步长 %.2f px" % max(steps)

    # 3) 最终归位：最后一帧的字都在目标位置（误差 < 0.5px）
    v._frac = 1.0
    v._elapsed = 3.0
    p = FakePainter()
    still = v._draw_trans_converge(p, area, font, y_top, v._row_h, rows)
    assert still is False, "填充走完、字也飞完后应切回整行绘制"
    print("  汇聚平滑性通过: 冻结期间位移 %.1f px, 最大帧步长 %.2f px"
          % (moved, max(steps)))


def test_mixed_text_shares_baseline():
    """中英混排（人名/专有名词）在逐字路径里必须和整行用同一条 baseline。

    回归点：逐字绘制若各用各字体的 AlignTop，拉丁字体 ascent 比中文字体小，
    英文会“偏上”；整行绘制时中英又共用一条 baseline，动画结束的瞬间英文
    会往下跳一下。现在两边都锚在 _trans_ascent() 量出的整行 baseline 上。
    """
    _ensure_app()
    mixed = "我的围巾 Ed Sheeran 留"
    v = _make_view()
    v.set_lyrics({"synced": True,
                  "lines": [(0.0, MAIN_LINE, mixed)],
                  "ends": [8.0]})
    v._ensure_layout()
    area = v._lyric_area()
    pt_t, rows = v._trans_layout(("trans", 0), mixed,
                                 v._base_pt * 0.60, area.width())
    assert len(rows) == 1, "这个用例应该是一行：%r" % (rows,)
    font = v._font(pt_t, heavy=True)
    y_top = v._focus_cy() - 10.0
    expect = y_top + v._trans_ascent(font, rows[0])

    # 驱动一遍：填充推进到 0.76（全部字的阈值都越过），再等所有字飞完
    t = 0.0
    while t < 2.0:
        v._frac = min(0.76, t * 0.9)
        v._elapsed = t
        v._draw_trans_converge(FakePainter(), area, font, y_top,
                               v._row_h, rows)
        t += 1.0 / 60.0
    # 最后一帧：每个字的正文笔画（幽灵描边在前）都应在同一 baseline 上
    v._frac = 0.76
    v._elapsed = 2.0
    p = FakePainter()
    v._draw_trans_converge(p, area, font, y_top, v._row_h, rows)
    solid = {}
    for ch, _x, y in p.boxes:
        solid[ch] = y          # 后画的（正文）覆盖先画的（幽灵）
    offs = {ch: abs(y - expect) for ch, y in solid.items()}
    worst = max(offs.items(), key=lambda kv: kv[1])
    assert worst[1] < 0.6, "字不在同一条 baseline 上: %r（期望 %.1f，差 %.1f）" \
        % (worst, expect, worst[1])
    # 英文单词确实画出来了（防止将来误删）
    for ch in "EdSheeran":
        assert ch in solid, "英文字符 %r 没画出来" % ch
    print("  中英混排 baseline 一致: %d 个字，最大偏差 %.2f px"
          % (len(solid), worst[1]))


if __name__ == "__main__":
    test_motion_continues_while_fill_is_frozen()
    test_mixed_text_shares_baseline()
    print("ALL PASSED")
