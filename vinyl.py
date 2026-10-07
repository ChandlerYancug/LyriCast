# -*- coding: utf-8 -*-
"""黑胶唱片材质（彩胶）：十多种“真彩胶”质感，不是简单换色。

每种材质除了底色，还带自己的——**花纹类型**（大理石 / 泼墨 / 星云 /
闪粉 / 对开 / 镭射……）、**透明度**（透胶能透出背景）、**沟槽表现**
（浅色片靠阴影、深色片靠反光）和**光泽强度**，按真实彩胶的观感来。

- 默认：按**专辑封面主色**自动挑一张（`for_cover_color`），挑完就记进这首歌的
  记忆（`skins.py`），下次放这首还是它；
- 用户手动换过（`M` 键 / 托盘）→ 记住用户的选择（也只影响这一首）；
- 花纹用固定种子的伪随机生成：同一款材质每次都长一样，不会闪。
- 盘面分三层渲染（见 `render_plate`）：底盘 / 花纹层 / 表层。**花纹层随盘
  旋转，沟槽和反光不转** —— 同心沟槽转了看不出，而反光是打在盘面上的光，
  不该跟着唱片转。三层都缓存，只在尺寸 / 屏幕缩放 / 材质变化时重画。
"""

import colorsys
import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)

GROOVE_FROM = 0.63               # 沟槽起始半径 / R（封面外侧留一圈留白）
OUTER = 0.985                    # 沟槽外缘 / R


# --------------------------------------------------------------------------- #
# 材质表：至少十种，花纹 / 透明感 / 光泽各不相同
# --------------------------------------------------------------------------- #
MATERIALS = [
    {
        "id": "black", "name": "经典黑胶",
        "base": ("#26262b", "#111114"), "alpha": 255, "pattern": "solid",
        "sheen": 30, "rim": 40,
    },
    {
        "id": "white", "name": "白胶",
        "base": ("#f4f2ee", "#d7d3cc"), "alpha": 255, "pattern": "solid",
        "groove_dark": True, "sheen": 54, "rim": 62, "edge": 44,
    },
    {
        "id": "clear", "name": "水晶透明胶",
        "base": ("#e6eef5", "#8b95a3"), "alpha": 102, "pattern": "solid",
        "sheen": 88, "rim": 120, "edge": 26,
    },
    {
        "id": "clear-red", "name": "透明红胶",
        "base": ("#e0503c", "#8e2018"), "alpha": 158, "pattern": "solid",
        "sheen": 62, "rim": 88, "edge": 34,
    },
    {
        "id": "clear-sea", "name": "海玻璃胶",
        "base": ("#8fdccd", "#2f8f85"), "alpha": 148, "pattern": "solid",
        "groove_dark": True, "sheen": 64, "rim": 92, "edge": 32,
    },
    {
        "id": "amber", "name": "琥珀胶",
        "base": ("#e6a63f", "#8a5a12"), "alpha": 205, "pattern": "solid",
        "groove_dark": True, "sheen": 46, "rim": 60, "edge": 46,
    },
    {
        "id": "red", "name": "正红胶",
        "base": ("#c02a20", "#7c1512"), "alpha": 255, "pattern": "solid",
        "sheen": 32, "rim": 44,
    },
    {
        "id": "green", "name": "森林绿胶",
        "base": ("#237848", "#0e3f28"), "alpha": 255, "pattern": "solid",
        "sheen": 32, "rim": 46,
    },
    {
        "id": "purple", "name": "霓紫胶",
        "base": ("#7a4bc0", "#3a1f6b"), "alpha": 255, "pattern": "solid",
        "sheen": 38, "rim": 52,
    },
    {
        "id": "galaxy", "name": "星云胶",
        "base": ("#1a1626", "#0b0913"), "alpha": 255, "pattern": "galaxy",
        "colors": ["#a48cf0", "#e2dcff", "#5a49a0"],
        "sheen": 34, "rim": 54,
    },
    {
        "id": "marble-red", "name": "红白大理石胶",
        "base": ("#efe9e1", "#d8d0c6"), "alpha": 255, "pattern": "marble",
        "colors": ["#c62a1e", "#2c2c34", "#e8a396"],
        "groove_dark": True, "sheen": 50, "rim": 58, "edge": 46,
    },
    {
        "id": "splatter", "name": "泼墨胶",
        "base": ("#f1efeb", "#cfcac2"), "alpha": 255, "pattern": "splatter",
        "colors": ["#e0342a", "#f0a92b", "#2b6fd0", "#3aa35a", "#8a3fd0"],
        "groove_dark": True, "sheen": 46, "rim": 56, "edge": 44,
    },
    {
        "id": "glitter", "name": "闪粉胶",
        "base": ("#1d3a30", "#0c1d18"), "alpha": 255, "pattern": "glitter",
        "colors": ["#ffffff", "#ffe9a8", "#bff0d8"],
        "sheen": 44, "rim": 56,
    },
    {
        "id": "hologram", "name": "镭射胶",
        "base": ("#9aa1ab", "#6a707a"), "alpha": 255, "pattern": "holo",
        "sheen": 76, "rim": 82, "edge": 44,
    },
    {
        "id": "split", "name": "对开双色胶",
        "base": ("#d23a2a", "#2b5ce0"), "alpha": 255, "pattern": "split",
        "colors": ["#e13b2b", "#2b5ce0"],
        "sheen": 40, "rim": 54,
    },
    {
        "id": "smoke", "name": "烟熏胶",
        "base": ("#6d6f78", "#33353d"), "alpha": 176, "pattern": "smoke",
        "colors": ["#22242a", "#9aa0ab"],
        "sheen": 52, "rim": 66, "edge": 36,
    },
]

BY_ID = {m["id"]: m for m in MATERIALS}


def by_id(mat_id):
    """按 id 取材质；没有就返回 None。"""
    return BY_ID.get(str(mat_id or ""))


def pick(cfg=None):
    """没定彩胶前的起始色：默认「经典黑胶」。

    彩胶不再在 config 里固定 —— 没记住的歌等封面到了按主色自动配
    （`for_cover_color`），手动换过的按歌记忆（见 `skins.py`）。
    参数 cfg 仅为兼容调用处保留。
    """
    return BY_ID[MATERIALS[0]["id"]]


def has_pattern(mat):
    """该材质有没有“有方向感”的花纹（决定要不要跟着盘转）。"""
    return mat.get("pattern", "solid") != "solid"


def next_of(mat):
    """按 M 键手动轮换到下一款。"""
    i = MATERIALS.index(mat) if mat in MATERIALS else 0
    return MATERIALS[(i + 1) % len(MATERIALS)]


# --------------------------------------------------------------------------- #
# 按封面配色（自动模式）
# --------------------------------------------------------------------------- #
def cover_rgb(img, size=24):
    """封面代表色：缩到小块后取“最鲜艳的四成像素”的平均色。

    直接平均会被大片灰底把颜色冲淡；先按“色彩量 = 饱和度 × 明度”
    排序取彩色部分，既有重点又稳定（确定性，同一张图每次一样）。
    """
    im = img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
    cols = []
    for y in range(im.height()):
        for x in range(im.width()):
            c = im.pixelColor(x, y)
            if c.alpha() < 128:
                continue
            r, g, b = c.red(), c.green(), c.blue()
            mx = max(r, g, b)
            sat = 0.0 if mx == 0 else (mx - min(r, g, b)) / float(mx)
            cols.append((sat * mx, r, g, b))
    if not cols:
        return (0, 0, 0)
    cols.sort(key=lambda t: t[0], reverse=True)
    top = cols[:max(1, (len(cols) * 2) // 5)]
    n = float(len(top))
    return (int(sum(t[1] for t in top) / n + 0.5),
            int(sum(t[2] for t in top) / n + 0.5),
            int(sum(t[3] for t in top) / n + 0.5))


def for_cover_color(rgb):
    """按封面色挑一款彩胶：从素色系里挑，花纹款留给手动换。"""
    r, g, b = [min(255, max(0, int(v))) / 255.0 for v in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hue = h * 360.0
    if s < 0.14:                                  # 灰调：黑 / 烟熏 / 白
        if v < 0.30:
            return BY_ID["black"]
        if v < 0.62:
            return BY_ID["smoke"]
        return BY_ID["white"]
    if hue < 20 or hue >= 344:                    # 红 / 粉
        if s < 0.45:
            return BY_ID["clear-red"]
        return BY_ID["red"]
    if hue < 75:                                  # 橙 / 黄 → 琥珀
        return BY_ID["amber"]
    if hue < 165:                                 # 绿
        if s < 0.50:
            return BY_ID["clear-sea"]
        return BY_ID["green"]
    if hue < 200:                                 # 青
        return BY_ID["clear-sea"]
    if hue < 262:                                 # 蓝：暗＝星云、淡＝水晶、其它＝霓紫
        if v < 0.35:
            return BY_ID["galaxy"]
        if s < 0.30:
            return BY_ID["clear"]
        return BY_ID["purple"]
    if hue < 300:                                 # 紫
        if v < 0.40:
            return BY_ID["galaxy"]
        return BY_ID["purple"]
    if s < 0.45 or v > 0.85:                      # 玫红 / 品红
        return BY_ID["clear-red"]
    return BY_ID["purple"]


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def _lum(hexstr):
    c = QColor(hexstr)
    return (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255.0


def _wedge(r1, r2, a0, aw, steps=12):
    """扇环路径（射线方向的楔形，用来画星云条纹）。"""
    pts = []
    for k in range(steps + 1):
        a = a0 - aw / 2.0 + aw * k / steps
        pts.append(QPointF(math.cos(a) * r2, math.sin(a) * r2))
    for k in range(steps, -1, -1):
        a = a0 - aw / 2.0 + aw * k / steps
        pts.append(QPointF(math.cos(a) * r1, math.sin(a) * r1))
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def _marble(q, R, cols, rng, n=20, soft=False):
    """大理石 / 烟熏：拉长的软色浆块，像倒色时流动的纹路。"""
    for i in range(n):
        col = QColor(cols[i % len(cols)])
        a = rng.uniform(60, 130) if soft else rng.uniform(150, 232)
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.92 * R      # 按面积均分，铺满整盘
        rr = rng.uniform(0.16, 0.34) * R
        col.setAlpha(int(a))
        q.save()
        q.translate(math.cos(ang) * rad, math.sin(ang) * rad)
        q.rotate(rng.uniform(0.0, 360.0))
        q.scale(rng.uniform(1.4, 2.9), 1.0)          # 拉长 → 像流动的色浆
        g = QRadialGradient(0, 0, rr)
        g.setColorAt(0.0, col)
        mid = QColor(col)
        mid.setAlpha(int(col.alpha() * 0.5))
        g.setColorAt(0.55, mid)
        end = QColor(col)
        end.setAlpha(0)
        g.setColorAt(1.0, end)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QBrush(g))
        q.drawEllipse(QRectF(-rr, -rr, rr * 2.0, rr * 2.0))
        q.restore()


def _splatter(q, R, cols, rng, n=95, m=150):
    """泼墨：不透明的色点（真泼墨胶的边界是清楚的），大小参差。"""
    k = R / 400.0
    q.setPen(Qt.PenStyle.NoPen)
    for i in range(n):
        col = QColor(cols[rng.randrange(len(cols))])
        col.setAlpha(rng.randint(170, 255))
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.95 * R
        rr = rng.uniform(1.6, 7.5) * k * rng.choice([1.0, 1.0, 1.0, 2.4])
        q.setBrush(col)
        q.drawEllipse(QPointF(math.cos(ang) * rad, math.sin(ang) * rad),
                      rr, rr)
    for i in range(m):                                # 溅开的细点
        col = QColor(cols[rng.randrange(len(cols))])
        col.setAlpha(rng.randint(110, 220))
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.95 * R
        rr = rng.uniform(0.6, 1.7) * k
        q.setBrush(col)
        q.drawEllipse(QPointF(math.cos(ang) * rad, math.sin(ang) * rad),
                      rr, rr)


def _galaxy(q, R, cols, rng, n=13):
    """星云：压片流动方向的射线条纹（角向柔边）+ 星点。"""
    q.setPen(Qt.PenStyle.NoPen)
    for i in range(n):
        col = QColor(cols[i % len(cols)])
        a0 = rng.uniform(0.0, math.tau)
        aw = math.radians(rng.uniform(5.0, 18.0))
        r1 = rng.uniform(0.08, 0.3) * R
        r2 = rng.uniform(0.7, 1.0) * R
        a_max = rng.randint(120, 190)
        # 三层同心叠画：外宽淡、内窄亮 → 角向自然柔边（否则像风车）
        for wf, af in ((1.0, 0.42), (0.62, 0.72), (0.3, 1.0)):
            g = QLinearGradient(math.cos(a0) * r1, math.sin(a0) * r1,
                                math.cos(a0) * r2, math.sin(a0) * r2)
            c0 = QColor(col)
            c0.setAlpha(int(a_max * af))
            c1 = QColor(col)
            c1.setAlpha(0)
            g.setColorAt(0.0, c1)
            g.setColorAt(0.4, c0)
            g.setColorAt(1.0, c1)
            q.setBrush(QBrush(g))
            q.drawPath(_wedge(r1, r2, a0, aw * wf))
    k = R / 400.0
    for i in range(420):                              # 星点
        col = QColor(cols[rng.randrange(len(cols))])
        col.setAlpha(rng.randint(40, 190))
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.98 * R
        rr = rng.uniform(0.5, 1.4) * k
        q.setBrush(col)
        q.drawEllipse(QPointF(math.cos(ang) * rad, math.sin(ang) * rad),
                      rr, rr)


def _glitter(q, R, cols, rng, n=680):
    """闪粉：密集细闪 + 少量大颗粒。"""
    k = R / 400.0
    q.setPen(Qt.PenStyle.NoPen)
    for i in range(n):
        col = QColor(cols[rng.randrange(len(cols))])
        col.setAlpha(rng.randint(90, 205))
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.97 * R
        rr = rng.uniform(0.45, 1.1) * k
        q.setBrush(col)
        q.drawEllipse(QPointF(math.cos(ang) * rad, math.sin(ang) * rad),
                      rr, rr)
    for i in range(60):                               # 大颗粒：更亮
        col = QColor(cols[rng.randrange(len(cols))])
        col.setAlpha(rng.randint(190, 255))
        ang = rng.uniform(0.0, math.tau)
        rad = math.sqrt(rng.random()) * 0.95 * R
        rr = rng.uniform(1.6, 2.8) * k
        q.setBrush(col)
        q.drawEllipse(QPointF(math.cos(ang) * rad, math.sin(ang) * rad),
                      rr, rr)


def _split(q, R, cols):
    """对开：两半不同颜色（真压片的 split），接缝处有一点渗色。"""
    a = QColor(cols[0])
    b = QColor(cols[1] if len(cols) > 1 else cols[0])
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(a)
    q.drawEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))
    q.save()
    q.setClipRect(QRectF(0.0, -R, R, 2.0 * R), Qt.ClipOperation.IntersectClip)
    q.setBrush(b)
    q.drawEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))
    q.restore()
    # 接缝：一道细暗线 + 两侧轻微渗色，避免“贴纸感”
    rng = random.Random("split-seam")
    q.setPen(QPen(QColor(0, 0, 0, 46), R * 0.012))
    q.drawLine(QPointF(0.0, -R), QPointF(0.0, R))
    q.setPen(Qt.PenStyle.NoPen)
    for i in range(26):
        y = rng.uniform(-R, R)
        side = 1.0 if rng.random() < 0.5 else -1.0
        col = QColor(a if side > 0 else b)
        col.setAlpha(rng.randint(50, 120))
        rr = rng.uniform(0.02, 0.09) * R
        q.setBrush(col)
        q.drawEllipse(QPointF(side * rng.uniform(0.0, 0.05) * R, y), rr, rr)


def _holo(q, R):
    """镭射：几道不同方向的彩虹衍射叠在金属底上。"""
    spectrum = ["#ff5d5d", "#ffb45d", "#f6ea5d", "#5fd97a", "#5db9ff",
                "#b06bff"]
    q.setPen(Qt.PenStyle.NoPen)
    for k in range(6):
        ang = math.radians(k * 30.0 + 12.0)
        g = QLinearGradient(-math.cos(ang) * R, -math.sin(ang) * R,
                            math.cos(ang) * R, math.sin(ang) * R)
        for i, cstr in enumerate(spectrum):
            col = QColor(cstr)
            col.setAlpha(46)
            g.setColorAt(i / (len(spectrum) - 1.0), col)
        q.setBrush(QBrush(g))
        q.drawEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))


def _pattern(q, R, mat):
    kind = mat.get("pattern", "solid")
    cols = mat.get("colors") or []
    if kind == "solid" or (not cols and kind != "holo"):
        return
    rng = random.Random(mat["id"])          # 固定种子：同一款花纹不变
    if kind == "marble":
        _marble(q, R, cols, rng)
    elif kind == "smoke":
        _marble(q, R, cols, rng, n=20, soft=True)
    elif kind == "splatter":
        _splatter(q, R, cols, rng)
    elif kind == "galaxy":
        _galaxy(q, R, cols, rng)
    elif kind == "glitter":
        _glitter(q, R, cols, rng)
    elif kind == "split":
        _split(q, R, cols)
    elif kind == "holo":
        _holo(q, R)


def _grooves(q, R, mat, base_alpha, dark):
    """沟槽：深色片靠反光（亮线），浅色片靠阴影（暗线）+ 一丁点反光。

    注意：drawEllipse 会用**当前画刷填充**，所以这里必须先换成
    NoBrush，否则沟槽环会把整个盘面重填一遗（花纹就没了）。
    """
    strength = float(mat.get("groove", 1.0))
    q.setBrush(Qt.BrushStyle.NoBrush)
    r0 = R * GROOVE_FROM
    outer = R * OUTER
    n = 110                                   # 真唱片的沟槽远不止几十道：
    for i in range(n):                        # 密到一定程度才读成“纹面”
        t = (i / (n - 1.0)) ** 0.96
        rr = r0 + (outer - r0) * t
        a0 = (12 if dark else 17) + int(8 * (0.5 + 0.5 * math.sin(i * 2.4)))
        a = int(a0 * strength)
        a = int(a * (0.85 + 0.3 * base_alpha / 255.0))
        a = max(0, min(255, a))
        col = QColor(0, 0, 0, a) if dark else QColor(255, 255, 255, a)
        q.setPen(QPen(col, 1.0))
        q.drawEllipse(QRectF(-rr, -rr, 2.0 * rr, 2.0 * rr))
    if dark:                                  # 浅色片：隔几圈补一道细反光
        for i in range(0, n, 4):
            t = (i / (n - 1.0)) ** 0.96
            rr = r0 + (outer - r0) * t
            q.setPen(QPen(QColor(255, 255, 255, 9), 1.0))
            q.drawEllipse(QRectF(-rr, -rr, 2.0 * rr, 2.0 * rr))


def render_plate(R, dpr, mat):
    """渲染唱片，返回三层 (底盘, 花纹层, 表层)。

    分开是为了旋转：

    * **底盘**   —— 底色渐变 + 外缘提亮（旋转看不出来，不转）
    * **花纹层** —— 泼墨 / 大理石 / 星云 / 闪粉 / 对开 / 镭射
      （**跟着盘转**；纯色款没有花纹，返回 None）
    * **表层**   —— 沟槽 + 导入槽 + 外缘环 + 斜反射（不转：沟槽是同心圆，
      反光是打在盘面上的光，都不该跟着唱片转）
    """
    R = float(R)
    base_alpha = int(mat.get("alpha", 255))
    dark = mat.get("groove_dark")
    if dark is None:
        dark = _lum(mat["base"][0]) * (base_alpha / 255.0) > 0.45
    edge_alpha = int(mat.get("edge", 92 if not dark else 48))
    sheen_alpha = int(mat.get("sheen", 30))
    rim_alpha = int(mat.get("rim", 40))
    size = int((2.0 * R + 6.0) * dpr)

    def new_painter():
        im = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        im.fill(Qt.GlobalColor.transparent)
        q = QPainter(im)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.scale(dpr, dpr)
        q.translate(R + 3.0, R + 3.0)
        return im, q

    # ---- 底盘 ---------------------------------------------------------- #
    disc = QPainterPath()
    disc.addEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))
    img_base, q = new_painter()
    c0 = QColor(mat["base"][0])
    c1 = QColor(mat["base"][1])
    c0.setAlpha(base_alpha)
    c1.setAlpha(base_alpha)
    mid = QColor(
        int((c0.red() + c1.red()) / 2), int((c0.green() + c1.green()) / 2),
        int((c0.blue() + c1.blue()) / 2), base_alpha)
    grad = QRadialGradient(0, 0, R)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(0.72, mid)
    grad.setColorAt(0.97, c1)
    grad.setColorAt(1.0, c1.lighter(135))        # 外缘提亮（透胶的“吃光”边）
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(QBrush(grad))
    q.drawPath(disc)
    q.end()

    # ---- 花纹层（随盘旋转） -------------------------------------------- #
    img_pat = None
    if has_pattern(mat):
        img_pat, q = new_painter()
        q.setClipPath(disc)
        _pattern(q, R, mat)
        q.end()

    # ---- 表层（不转） -------------------------------------------------- #
    img_over, q = new_painter()
    _grooves(q, R, mat, base_alpha, dark)
    r0 = R * GROOVE_FROM
    outer = R * OUTER
    q.setBrush(Qt.BrushStyle.NoBrush)             # 描边环不能填充盘面
    q.setPen(QPen(QColor(255, 255, 255, int(30 * (rim_alpha / 44.0))), 1.2))
    q.drawEllipse(QRectF(-r0, -r0, 2.0 * r0, 2.0 * r0))
    q.setPen(QPen(QColor(255, 255, 255, rim_alpha), 1.4))
    q.drawEllipse(QRectF(-outer, -outer, 2.0 * outer, 2.0 * outer))
    if edge_alpha > 0:                            # 盘边：深色片是黑边
        q.setPen(QPen(QColor(0, 0, 0, edge_alpha), 2.0))
        q.drawEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))

    hl = QLinearGradient(-R * 0.85, -R * 0.85, R * 0.85, R * 0.85)
    hl.setColorAt(0.0, QColor(255, 255, 255, sheen_alpha))
    hl.setColorAt(0.34, QColor(255, 255, 255, 0))
    hl.setColorAt(0.66, QColor(255, 255, 255, 0))
    hl.setColorAt(1.0, QColor(255, 255, 255, int(sheen_alpha * 0.55)))
    q.setBrush(QBrush(hl))
    q.setPen(Qt.PenStyle.NoPen)
    q.drawEllipse(QRectF(-R, -R, 2.0 * R, 2.0 * R))
    q.end()

    return (QPixmap.fromImage(img_base),
            QPixmap.fromImage(img_pat) if img_pat is not None else None,
            QPixmap.fromImage(img_over))
