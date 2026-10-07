# -*- coding: utf-8 -*-
"""黑胶唱臂：一支朴素好看的近黑直臂（不再提供换肤，越简单越耐看）。

- 造型：直臂 + 锥形管身（枢轴粗、唱头端细），管身用垂直于管轴的金属渐变
  一次填充，像真的圆管；
- 细节：俯视的唱头架 / 唱头（带一点偏角）、锥管末端的钻石针尖（一圈柔光）、
  滚花配重、轴承座、甩出的信号线。

绘制入口 `draw()`：坐标已由调用方 translate/rotate 到
「枢轴 = 原点、+x 指向唱针」的局部坐标系里。
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainterPath,
    QPen,
    QRadialGradient,
)


# --------------------------------------------------------------------------- #
# 唱臂外观（唯一一支：近黑管 + 冷色高光 + 银唱头架，干净朴素）
# --------------------------------------------------------------------------- #
SKIN = {
    "id": "carbon", "name": "碳纤维",
    "desc": "近黑碳管 + 冷色高光 + 银唱头架，干净朴素",
    "shape": "straight", "bend": 0.0,
    "tube_edge": "#0a0b0d", "tube_body": "#191b1f",
    "tube_gloss": "#46525f", "tube_spec": "#dfe6ee",
    "shell_col": ("#eaeef3", "#aeb5be", "#4b5158"),
    "cart": ("#2a2d32", "#0e1012"), "accent": "#d8dde3",
    "cw_col": ("#4b5058", "#23262b", "#0d0e10"),
    "pivot_col": ("#eef1f5", "#8b929b", "#2f3339"),
}


# --------------------------------------------------------------------------- #
# 绘制小工具
# --------------------------------------------------------------------------- #
def _taper_shape(path, w0, w1, samples=48):
    """把中心线变成“锥形管”的轮廓多边形（枢轴粗、唱头端细）。

    以前是分段描圆头短线，长度一大就出现一串“珠状”齿边；
    现在采样中心线、按法线两侧偏移一次成面，边缘干净。
    """
    pts = [path.pointAtPercent(i / float(samples))
           for i in range(samples + 1)]
    n = len(pts)
    left, right = [], []
    for i, pt in enumerate(pts):
        a = pts[max(0, i - 1)]
        b = pts[min(n - 1, i + 1)]
        tx, ty = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / ln, tx / ln
        hw = (w0 + (w1 - w0) * (i / float(samples))) / 2.0
        left.append(QPointF(pt.x() + nx * hw, pt.y() + ny * hw))
        right.append(QPointF(pt.x() - nx * hw, pt.y() - ny * hw))
    poly = QPainterPath()
    poly.moveTo(left[0])
    for q in left[1:]:
        poly.lineTo(q)
    for q in reversed(right):
        poly.lineTo(q)
    poly.closeSubpath()
    return poly


def _tube_path(L, shape, bend):
    """唱臂管的路径（局部坐标：枢轴为原点，+x 指向唱针）。

    管尾（-x）只伸到枢轴后方一点，被配重/轴承座盖住；
    管头收在唱头架里（不穿出来）。
    """
    path = QPainterPath()
    x0, x1 = -0.115 * L, 0.78 * L
    span = x1 - x0
    path.moveTo(x0, 0.0)
    if shape == "s":
        b = bend * L
        path.cubicTo(QPointF(x0 + span * 0.28, -b * 1.6),
                     QPointF(x0 + span * 0.46, -b * 1.7),
                     QPointF(x0 + span * 0.55, 0.0))
        path.cubicTo(QPointF(x0 + span * 0.64, b * 1.7),
                     QPointF(x0 + span * 0.84, b * 1.6),
                     QPointF(x1, 0.0))
    elif shape == "j":
        b = bend * L
        path.quadTo(QPointF(x0 + span * 0.55, b * 2.0), QPointF(x1, 0.0))
    else:
        path.lineTo(x1, 0.0)
    return path


# --------------------------------------------------------------------------- #
# 静态部分（不随唱臂转动）：信号线
# --------------------------------------------------------------------------- #
def draw_static(p, px, py, R):
    """枢轴处伸出的信号线：一小段弧线拐向右上，末端淡出。"""
    p.save()
    p.translate(px, py)
    path = QPainterPath(QPointF(-R * 0.02, -R * 0.06))
    path.cubicTo(QPointF(R * 0.10, -R * 0.22),
                 QPointF(R * 0.36, -R * 0.28),
                 QPointF(R * 0.64, -R * 0.26))
    g = QLinearGradient(0.0, 0.0, R * 0.64, -R * 0.26)
    g.setColorAt(0.0, QColor(20, 22, 26, 240))
    g.setColorAt(0.7, QColor(20, 22, 26, 150))
    g.setColorAt(1.0, QColor(20, 22, 26, 0))
    pen = QPen(QBrush(g), max(1.8, R * 0.017))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


# --------------------------------------------------------------------------- #
# 主绘制：枢轴 = 原点，+x 指向唱针
# --------------------------------------------------------------------------- #
def draw(p, R, L, skin=None):
    skin = skin or SKIN
    w0, w1 = R * 0.052, R * 0.038        # 锥管：枢轴粗 → 唱头端细
    path = _tube_path(L, skin.get("shape", "straight"),
                      float(skin.get("bend") or 0.0))
    shape = _taper_shape(path, w0, w1)

    # 盘面上的柔影（光来自左上，影子投在右下；管轴局部 -y 正好是右下方向）
    p.save()
    p.translate(0.0, -R * 0.045)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 62))
    p.drawPath(_taper_shape(path, w0 * 1.12, w1 * 1.12))
    p.restore()

    # 管身：垂直于管轴的金属渐变（上暗边 → 高光 → 下暗边），一眼看出是圆管
    g = QLinearGradient(0.0, -w0 / 2.0, 0.0, w0 / 2.0)
    g.setColorAt(0.00, QColor(skin["tube_edge"]))
    g.setColorAt(0.30, QColor(skin["tube_body"]))
    g.setColorAt(0.46, QColor(skin["tube_gloss"]))
    g.setColorAt(0.57, QColor(skin["tube_spec"]))
    g.setColorAt(0.70, QColor(skin["tube_body"]))
    g.setColorAt(1.00, QColor(skin["tube_edge"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawPath(shape)

    _draw_counterweight(p, R, skin)
    _draw_head(p, R, L, skin)
    _draw_pivot(p, R, skin)


def _draw_head(p, R, L, skin):
    """唱头架 + 唱头 + 唱针（**俯视**：沿臂轴向前伸，前端留一点偏角）。

    以前是“侧视”的方块挂在管子上，和俯视的管身拼在一起很别扭；
    现在按俯视画：凤头沿臂轴、唱头从架子里探出、针尖恰好落在 L 上。
    """
    shell = skin["shell_col"]
    cart = skin["cart"]
    acc = QColor(skin.get("accent", "#d8dde3"))

    hs_l, hs_w = R * 0.104, R * 0.052    # 唱头架：长 × 宽（约 2:1，像真头）
    ct_l, ct_w = R * 0.088, R * 0.050    # 唱头：长 × 宽
    head_l = R * 0.198                   # 架根 → 针尖（轴向）

    p.save()
    p.translate(L - head_l, 0.0)
    p.rotate(16.0)                       # 唱头架偏角（像真臂）

    # 唱头架：沿臂轴的小长块（银灰，上沿亮、下沿暗）
    g = QLinearGradient(0.0, -hs_w / 2.0, 0.0, hs_w / 2.0)
    g.setColorAt(0.0, QColor(shell[0]))
    g.setColorAt(0.40, QColor(shell[1]))
    g.setColorAt(1.0, QColor(shell[2]))
    p.setPen(QPen(QColor(0, 0, 0, 118), 1.0))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(-R * 0.008, -hs_w / 2.0, hs_l, hs_w),
                      hs_w * 0.40, hs_w * 0.40)
    # 顶面高光带
    gloss = QLinearGradient(0.0, -hs_w * 0.46, 0.0, -hs_w * 0.04)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 118))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(gloss))
    p.drawRoundedRect(QRectF(R * 0.006, -hs_w * 0.44, hs_l * 0.84, hs_w * 0.34),
                      hs_w * 0.17, hs_w * 0.17)

    # 两颗安装螺丝（俯视看下去是暗色小圆点）
    p.setBrush(QColor(58, 63, 70))
    p.drawEllipse(QPointF(hs_l * 0.33, 0.0), R * 0.007, R * 0.007)
    p.drawEllipse(QPointF(hs_l * 0.67, 0.0), R * 0.007, R * 0.007)

    # 唱头：从唱头架前端探出的小长块 + 一道细品牌线
    cart_x = hs_l - R * 0.018
    cg = QLinearGradient(0.0, -ct_w / 2.0, 0.0, ct_w / 2.0)
    cg.setColorAt(0.0, QColor(cart[0]))
    cg.setColorAt(1.0, QColor(cart[1]))
    p.setPen(QPen(QColor(0, 0, 0, 132), 1.0))
    p.setBrush(QBrush(cg))
    p.drawRoundedRect(QRectF(cart_x, -ct_w / 2.0, ct_l, ct_w),
                      ct_w * 0.36, ct_w * 0.36)
    p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), 170),
                  max(1.0, R * 0.004)))
    xb = cart_x + ct_l * 0.62
    p.drawLine(QPointF(xb, -ct_w * 0.26), QPointF(xb, ct_w * 0.26))

    # 唱针：悬臂 + 钻石针尖（柔光小晕）
    arm_x = cart_x + ct_l
    p.setPen(QPen(QColor(210, 216, 224, 225), R * 0.0075))
    p.drawLine(QPointF(arm_x, 0.0), QPointF(arm_x + R * 0.018, 0.0))
    tip = QPointF(arm_x + R * 0.026, 0.0)
    halo = QRadialGradient(tip, R * 0.024)
    halo.setColorAt(0.0, QColor(255, 255, 255, 100))
    halo.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(tip, R * 0.024, R * 0.024)
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawEllipse(tip, R * 0.0072, R * 0.0072)
    p.restore()


def _draw_counterweight(p, R, skin):
    """配重：枢轴后方的一段金属圆柱（滚花 + 端盖 + 尾栓），压在枢轴下面。"""
    cols = skin["cw_col"]
    w, h = R * 0.190, R * 0.096          # 长 × 粗
    x0 = -R * 0.245                       # 尾端（负 x = 离唱片更远）
    # 投影
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 84))
    p.drawRoundedRect(QRectF(x0 + R * 0.006, -h / 2.0 + R * 0.022,
                             w, h), h * 0.46, h * 0.46)
    # 柱体
    g = QLinearGradient(0.0, -h / 2.0, 0.0, h / 2.0)
    g.setColorAt(0.0, QColor(cols[0]))
    g.setColorAt(0.45, QColor(cols[1]))
    g.setColorAt(1.0, QColor(cols[2]))
    p.setPen(QPen(QColor(0, 0, 0, 132), 1.0))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(x0, -h / 2.0, w, h), h * 0.46, h * 0.46)
    # 滚花：几道竖纹
    p.setPen(QPen(QColor(0, 0, 0, 70), max(1.0, R * 0.005)))
    for k in range(4):
        x = x0 + w * (0.20 + 0.15 * k)
        p.drawLine(QPointF(x, -h * 0.30), QPointF(x, h * 0.30))
    # 尾端端盖（亮一点，像金属端面）
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(cols[1]))
    p.drawRoundedRect(QRectF(x0 + R * 0.004, -h * 0.40, R * 0.024, h * 0.80),
                      h * 0.36, h * 0.36)
    # 顶部高光窄带（沿上沿一条浅亮线，像金属圆柱受光）
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 30))
    p.drawRoundedRect(QRectF(x0 + R * 0.016, -h * 0.42, w - R * 0.032, h * 0.15),
                      h * 0.075, h * 0.075)


def _draw_pivot(p, R, skin):
    """轴承座：投影 + 金属顶盖 + 内圈 + 轮廊高光（画在配重之上，盖住交界）。"""
    cols = skin["pivot_col"]
    r = R * 0.060
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 92))
    p.drawEllipse(QPointF(0.0, R * 0.012), r * 1.30, r * 1.30)
    g = QRadialGradient(-r * 0.38, -r * 0.38, r * 1.85)
    g.setColorAt(0.0, QColor(cols[0]))
    g.setColorAt(0.58, QColor(cols[1]))
    g.setColorAt(1.0, QColor(cols[2]))
    p.setPen(QPen(QColor(0, 0, 0, 138), 1.1))
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(0.0, 0.0), r, r)
    # 内圈（轴承杯）与中心轴帽
    p.setPen(QPen(QColor(15, 16, 19, 195), max(1.0, R * 0.009)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0.0, 0.0), r * 0.46, r * 0.46)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(cols[0]))
    p.drawEllipse(QPointF(0.0, 0.0), r * 0.15, r * 0.15)
    # 轮廊高光（左上弧）
    p.setPen(QPen(QBrush(QColor(255, 255, 255, 118)), max(1.0, R * 0.006)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-r * 0.90, -r * 0.90, r * 1.80, r * 1.80),
              132 * 16, 78 * 16)
