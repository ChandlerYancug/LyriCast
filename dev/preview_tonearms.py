# -*- coding: utf-8 -*-
"""把每一支唱臂皮肤渲染成一张对比图（开发用，不弹窗口）。

输出：dev/tonearms_preview.png（2 行 × 4 列，一格一支臂）
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from utf8mode import ensure_utf8  # noqa: E402  （中文 Windows 默认 GBK）
ensure_utf8()

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QPainter,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication  # noqa: E402

import tonearm  # noqa: E402

app = QApplication([])

CW, CH = 470, 330
COLS = 4
ROWS = (len(tonearm.SKINS) + COLS - 1) // COLS
R = 118.0


def draw_cell(p, x0, y0, skin):
    p.save()
    p.translate(x0, y0)

    # 卡片底
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 21, 25))
    p.drawRoundedRect(QRectF(5, 5, CW - 10, CH - 10), 16, 16)

    # 左下角露出的一段唱片（黑胶底 + 沟槽 + 高光）
    cx, cy = CW * 0.30, CH * 0.98
    disc = QRectF(cx - R, cy - R, 2 * R, 2 * R)
    g = QRadialGradient(cx - R * 0.3, cy - R * 0.4, R * 1.1)
    g.setColorAt(0.0, QColor(58, 60, 66))
    g.setColorAt(0.6, QColor(30, 31, 35))
    g.setColorAt(1.0, QColor(16, 17, 20))
    p.setBrush(g)
    p.drawEllipse(disc)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QColor(255, 255, 255, 26))
    for k in range(7):
        rr = R * (0.66 + 0.05 * k)
        p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))

    # 唱臂：枢轴在右上，唱针落在盘面外圈（与正式界面同一套算法）
    hit = QPointF(cx + R * 0.75, cy - R * 0.30)
    px, py = CW * 0.80, CH * 0.20
    dx, dy = hit.x() - px, hit.y() - py
    L = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx))

    tonearm.draw_static(p, px, py, R, skin)
    p.save()
    p.translate(px, py)
    p.rotate(ang)
    tonearm.draw(p, R, L, skin)
    p.restore()

    # 名字 / 说明
    p.setPen(QColor(238, 240, 245))
    f = QFont("Microsoft YaHei UI", 11)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(18, 14, CW - 36, 24), Qt.AlignmentFlag.AlignLeft,
               skin["name"])
    p.setPen(QColor(178, 182, 190))
    f2 = QFont("Microsoft YaHei UI", 8)
    p.setFont(f2)
    p.drawText(QRectF(18, 38, CW - 36, 34),
               Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
               skin["desc"])
    p.restore()


def main():
    img = QImage(CW * COLS, CH * ROWS, QImage.Format.Format_ARGB32)
    img.fill(QColor(12, 12, 15))
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    for i, skin in enumerate(tonearm.SKINS):
        draw_cell(p, (i % COLS) * CW, (i // COLS) * CH, skin)
    p.end()
    out = os.path.join(BASE, "dev", "tonearms_preview.png")
    img.save(out)
    print("saved %s (%d×%d, %d skins)" % (out, img.width(), img.height(),
                                          len(tonearm.SKINS)))


if __name__ == "__main__":
    main()
