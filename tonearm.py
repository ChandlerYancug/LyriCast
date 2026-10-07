# -*- coding: utf-8 -*-
"""黑胶唱臂：一支朴素好看的近黑直臂（不再提供换肤，越简单越耐看）。

- 造型：直臂 + 锥形管身（枢轴粗、唱头端细）；管身是「暗边 → 主体 → 亮面 →
  高光」四层描边，像真的金属管；
- 细节：唱头架、带偏角的唱头 / 钻石针尖（一圈柔光）、滚花配重、
  带高光点的轴承座、甩出的信号线。

绘制入口 `draw()`：坐标已由调用方 translate/rotate 到
「枢轴 = 原点、+x 指向唱针」的局部坐标系里。
"""

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
def _stroke(p, path, color, width):
    pen = QPen(QBrush(QColor(color)), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _taper_stroke(p, path, color, w0, w1, samples=16):
    """锥形描边：从 w0 渐变到 w1（枢轴粗、唱头端细，像真臂的锥管）。"""
    pts = [path.pointAtPercent(i / float(samples))
           for i in range(samples + 1)]
    pen = QPen(QBrush(QColor(color)), max(1.0, w0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    for i in range(samples):
        t = (i + 0.5) / float(samples)
        pen.setWidthF(max(1.0, w0 + (w1 - w0) * t))
        p.setPen(pen)
        p.drawLine(pts[i], pts[i + 1])


def _tube_path(L, shape, bend):
    """唱臂管的路径（局部坐标：枢轴为原点，+x 指向唱针）。

    管尾（-x）只伸到翼枢后方一点，被配重/轴承座盖住 —— 不会从配重里穿出去。
    """
    path = QPainterPath()
    x0, x1 = -0.115 * L, 0.87 * L
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
    w0, w1 = R * 0.037, R * 0.026        # 锥管：枢轴粗 → 唱头端细
    wm = (w0 + w1) / 2.0
    path = _tube_path(L, skin.get("shape", "straight"),
                      float(skin.get("bend") or 0.0))

    # 盘面上的柔影
    p.save()
    p.translate(0.0, R * 0.05)
    _taper_stroke(p, path, QColor(0, 0, 0, 72), w0 * 1.30, w1 * 1.30)
    p.restore()

    # 管身：暗边 → 主体 → 亮面 → 高光（四层，弯管上也有圆柱感）
    _taper_stroke(p, path, skin["tube_edge"], w0, w1)
    _taper_stroke(p, path, skin["tube_body"], w0 * 0.62, w1 * 0.62)
    p.save()
    p.translate(0.0, -wm * 0.13)
    _taper_stroke(p, path, skin["tube_gloss"], w0 * 0.34, w1 * 0.34)
    p.restore()
    p.save()
    p.translate(0.0, -wm * 0.21)
    _taper_stroke(p, path, skin["tube_spec"], w0 * 0.13, w1 * 0.13)
    p.restore()

    _draw_counterweight(p, R, skin)
    _draw_head(p, R, L, skin)
    _draw_pivot(p, R, skin)


def _draw_head(p, R, L, skin):
    """唱头架 + 唱头 + 唱针（带 offset angle，像真臂的偏角）。"""
    p.save()
    p.translate(L * 0.845, 0.0)
    p.rotate(22.0)
    shell = skin["shell_col"]
    cart = skin["cart"]
    acc = QColor(skin.get("accent", "#d8dde3"))

    # 唱头架：加大 + 顶面高光 + 底部暗沿（前缘略收，像真唱头架的叶形头）
    hw, hh = R * 0.190, R * 0.066
    g = QLinearGradient(0.0, -hh / 2.0, 0.0, hh / 2.0)
    g.setColorAt(0.0, QColor(shell[0]))
    g.setColorAt(0.42, QColor(shell[1]))
    g.setColorAt(1.0, QColor(shell[2]))
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(-R * 0.018, -hh / 2.0, hw, hh),
                         hh * 0.34, hh * 0.34)
    p.setPen(QPen(QColor(0, 0, 0, 115), 1.0))
    p.setBrush(QBrush(g))
    p.drawPath(shape)
    # 顶面高光带
    gloss = QLinearGradient(0.0, -hh * 0.46, 0.0, -hh * 0.02)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 130))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(gloss))
    p.drawRoundedRect(QRectF(-R * 0.014, -hh * 0.44, hw - R * 0.020,
                             hh * 0.40), hh * 0.20, hh * 0.20)

    # 指拔（后上方的金属小握杆）
    p.setPen(QPen(QBrush(acc), R * 0.010))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-R * 0.052, -R * 0.034, R * 0.070, R * 0.058),
              -35 * 16, 130 * 16)

    # 两颗安装螺丝
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(acc)
    p.drawEllipse(QPointF(hw * 0.30, 0.0), R * 0.009, R * 0.009)
    p.drawEllipse(QPointF(hw * 0.66, 0.0), R * 0.009, R * 0.009)

    # 唱头体（前半段）+ 一道品牌色带
    cw, ch = R * 0.112, R * 0.052
    cg = QLinearGradient(0.0, 0.0, 0.0, ch)
    cg.setColorAt(0.0, QColor(cart[0]))
    cg.setColorAt(1.0, QColor(cart[1]))
    p.setPen(QPen(QColor(0, 0, 0, 130), 1.0))
    p.setBrush(QBrush(cg))
    p.drawRoundedRect(QRectF(hw - cw - R * 0.006, R * 0.006, cw, ch),
                      ch * 0.40, ch * 0.40)
    p.setPen(QPen(QBrush(acc), max(1.0, R * 0.006)))
    p.drawLine(QPointF(hw - cw + R * 0.010, R * 0.010),
               QPointF(hw - cw + R * 0.010, R * 0.006 + ch - R * 0.004))

    # 唱针：悬臂 + 钻石针尖（带一圈柔光）
    p.setPen(QPen(QColor(222, 226, 232, 240), R * 0.009))
    p.drawLine(QPointF(hw - R * 0.014, R * 0.006),
               QPointF(hw + R * 0.030, R * 0.022))
    tip = QPointF(hw + R * 0.030, R * 0.022)
    halo = QRadialGradient(tip, R * 0.034)
    halo.setColorAt(0.0, QColor(255, 255, 255, 130))
    halo.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(tip, R * 0.034, R * 0.034)
    p.setBrush(QColor(255, 255, 255, 250))
    p.drawEllipse(QPointF(tip.x() - R * 0.002, tip.y() - R * 0.002),
                  R * 0.0085, R * 0.0085)
    p.restore()


def _draw_counterweight(p, R, skin):
    """配重：半藏在轴承座后方；带投影 + 顶部轮廊高光，像金属圆柱。"""
    cols = skin["cw_col"]
    # 投影
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 90))
    p.drawEllipse(QRectF(-R * 0.214, -R * 0.037, R * 0.132, R * 0.092))
    # 柱体
    g = QLinearGradient(0.0, -R * 0.045, 0.0, R * 0.045)
    g.setColorAt(0.0, QColor(cols[0]))
    g.setColorAt(0.38, QColor(cols[1]))
    g.setColorAt(1.0, QColor(cols[2]))
    rect = QRectF(-R * 0.212, -R * 0.045, R * 0.130, R * 0.090)
    p.setPen(QPen(QColor(0, 0, 0, 130), 1.2))
    p.setBrush(QBrush(g))
    p.drawEllipse(rect)
    # 顶部轮廊高光（左上弧）
    p.setPen(QPen(QBrush(QColor(255, 255, 255, 120)), max(1.0, R * 0.007)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-R * 0.206, -R * 0.041, R * 0.118, R * 0.082),
              140 * 16, 80 * 16)
    # 滚花
    p.setPen(QPen(QColor(0, 0, 0, 85), max(1.0, R * 0.006)))
    for k in range(3):
        x = -R * 0.196 + k * R * 0.017
        p.drawLine(QPointF(x, -R * 0.029), QPointF(x, R * 0.029))
    # 尾栓
    p.setPen(QPen(QBrush(QColor(cols[1])), R * 0.010))
    p.drawLine(QPointF(-R * 0.214, 0.0), QPointF(-R * 0.240, 0.0))


def _draw_pivot(p, R, skin):
    """轴承座：投影 + 金属座 + 轮廊高光 + 轴承环（画在配重之上，盖住交界）。"""
    cols = skin["pivot_col"]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 95))
    p.drawEllipse(QPointF(0.0, R * 0.014), R * 0.088, R * 0.088)
    g = QRadialGradient(-R * 0.022, -R * 0.024, R * 0.092)
    g.setColorAt(0.0, QColor(cols[0]))
    g.setColorAt(0.62, QColor(cols[1]))
    g.setColorAt(1.0, QColor(cols[2]))
    p.setPen(QPen(QColor(0, 0, 0, 135), 1.2))
    p.setBrush(QBrush(g))
    p.drawEllipse(QRectF(-R * 0.075, -R * 0.075, R * 0.150, R * 0.150))
    # 轮廊高光（左上弧）
    p.setPen(QPen(QBrush(QColor(255, 255, 255, 130)), max(1.0, R * 0.007)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-R * 0.070, -R * 0.070, R * 0.140, R * 0.140),
              135 * 16, 85 * 16)
    # 轴承环
    p.setPen(QPen(QColor(14, 15, 18, 215), R * 0.011))
    p.drawEllipse(QRectF(-R * 0.032, -R * 0.032, R * 0.064, R * 0.064))
    # 高光点
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 150))
    p.drawEllipse(QPointF(-R * 0.042, -R * 0.046), R * 0.008, R * 0.008)
