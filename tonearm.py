# -*- coding: utf-8 -*-
"""黑胶唱臂皮肤：6 支“好看优先”的造型（不追名器，追质感）。

- **形状**：直臂 / S 形臂（优雅的双弯）；管身是「暗边 → 主体 → 亮面 → 高光」
  四层描边，弯管上也有圆柱感；
- **材质**：碳纤维（宝碟风：近黑管 + 冷色高光 + 银唱头架）、香槟金、
  镜面铬、午夜蓝、象牙白 + 玫瑰金、胡桃木 + 黄铜；
- **细节**：加大的唱头架（顶面高光 + 两颗螺丝）、带光晕的钻石针尖、
  滚花配重、带高光点的轴承座、甩出的信号线。

选择规则（和彩胶一致，见 `skins.py`）：

- 用户为某首歌挑过 → **记住这首歌的选择**，下次放这首歌还是它；
- 没挑过 → 用全局当前选择（`config.json` 的 `tonearm_skin`）；
- 都是 `auto` → 默认 `carbon`（碳纤维）。

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
# 皮肤表
# --------------------------------------------------------------------------- #
SKINS = [
    {
        "id": "carbon", "name": "碳纤维",
        "desc": "近黑碳管 + 冷色高光 + 银唱头架（宝碟风），默认款",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#0a0b0d", "tube_body": "#191b1f",
        "tube_gloss": "#46525f", "tube_spec": "#dfe6ee",
        "shell_col": ("#eaeef3", "#aeb5be", "#4b5158"),
        "cart": ("#2a2d32", "#0e1012"), "accent": "#d8dde3",
        "cw_col": ("#4b5058", "#23262b", "#0d0e10"),
        "pivot_col": ("#eef1f5", "#8b929b", "#2f3339"),
    },
    {
        "id": "champagne", "name": "香槟金",
        "desc": "暖金管身 + 奶油色唱头架，灯光下最贵气的一支",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#7a5f2c", "tube_body": "#cfa95f",
        "tube_gloss": "#f4e3b4", "tube_spec": "#fff8e3",
        "shell_col": ("#f6ecd8", "#d9c08a", "#8a6a33"),
        "cart": ("#f2e8d2", "#cbb37f"), "accent": "#f4e3b4",
        "cw_col": ("#e8cf95", "#b49251", "#6a5222"),
        "pivot_col": ("#f6e6c2", "#c9a75f", "#77602f"),
    },
    {
        "id": "mirror", "name": "镜面铬 · S 形",
        "desc": "S 形镜面铬管，反光一路拉通，复古优雅",
        "shape": "s", "bend": 0.048,
        "tube_edge": "#2a2e34", "tube_body": "#c9d0d9",
        "tube_gloss": "#f8fbfe", "tube_spec": "#ffffff",
        "shell_col": ("#eef1f5", "#a9b0b9", "#484e55"),
        "cart": ("#dfe4ea", "#8a9199"), "accent": "#eef1f5",
        "cw_col": ("#eef2f7", "#8d939c", "#31353b"),
        "pivot_col": ("#eef2f7", "#8d939c", "#31353b"),
    },
    {
        "id": "midnight", "name": "午夜蓝",
        "desc": "深蓝金属管 + 蓝唱头，冷调夜色的感觉",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#0a1022", "tube_body": "#1d2b4f",
        "tube_gloss": "#4d6fae", "tube_spec": "#c3d4f4",
        "shell_col": ("#dfe6f2", "#93a3c0", "#3c4a68"),
        "cart": ("#2f4b8f", "#16264f"), "accent": "#c3d4f4",
        "cw_col": ("#3c4a6e", "#1a2340", "#0a0e1d"),
        "pivot_col": ("#dfe6f2", "#7f8ba6", "#2b3348"),
    },
    {
        "id": "ivory", "name": "象牙白 · 玫瑰金",
        "desc": "奶白管身 + 玫瑰金配件，干净的高级感",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#b9b0a2", "tube_body": "#f0e9dc",
        "tube_gloss": "#ffffff", "tube_spec": "#fffdf7",
        "shell_col": ("#fbf7f0", "#ddd2c0", "#a2967f"),
        "cart": ("#f6efe2", "#d3c6ad"), "accent": "#d8a48f",
        "cw_col": ("#f6f0e4", "#cbbfae", "#8d8270"),
        "pivot_col": ("#f0c9b6", "#c98d72", "#8a5540"),
    },
    {
        "id": "walnut", "name": "胡桃木 · 黄铜",
        "desc": "漆面木纹管 + 黄铜配件，发烧友的小情调",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#33200f", "tube_body": "#6f4522",
        "tube_gloss": "#a8763f", "tube_spec": "#e3bd8a",
        "shell_col": ("#e8cd9a", "#c39a55", "#7d5c26"),
        "cart": ("#f0e6cf", "#c9b184"), "accent": "#e3bd8a",
        "cw_col": ("#e2c58c", "#b08a48", "#6b5222"),
        "pivot_col": ("#e8cd9a", "#b9924c", "#6f5423"),
    },
]

BY_ID = {s["id"]: s for s in SKINS}
DEFAULT_ID = "carbon"


def by_id(skin_id):
    """按 id 取皮肤；没有就返回 None。"""
    return BY_ID.get(str(skin_id or ""))


def pick(cfg):
    """全局选择：config 里固定过的就用它，否则默认碳纤维。"""
    return by_id((cfg or {}).get("tonearm_skin")) or BY_ID[DEFAULT_ID]


def next_of(skin):
    """换下一支（托盘 / `N` 键）。"""
    i = SKINS.index(skin) if skin in SKINS else 0
    return SKINS[(i + 1) % len(SKINS)]


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
def draw_static(p, px, py, R, skin):
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
def draw(p, R, L, skin):
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
