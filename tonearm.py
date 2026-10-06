# -*- coding: utf-8 -*-
"""黑胶唱臂皮肤：8 支致敬真实经典唱臂的造型（形状 / 材质 / 唱头配色）。

和 `vinyl.py`（彩胶材质）同一套玩法：
- **形状**：S 形（SME 3009 / SL-1200 那种双弯管）、J 形（单弯）、直臂；
- **管身**：铬（镜面银）、黑镁阳极、哑光黑、枪灰——每种都是"暗边 + 亮面 +
  一道居中高光"三层描边，弯管上也保持圆柱感；
- **唱头架**：classic（开孔铝架）/ dj（黑架 + 指拔）/ integrated（唱头直装，
  无独立架子）/ cone（Ortofon Concorde 那种锥形一体头）；
- **唱头**：银、白（Shure M44-7）、绿（AT95E）、蓝（2M Blue / Concorde）、黑；
- **配重**：铬柱 / 黑柱 / 黑柱加铬环；**轴承座**：青铜 / 铬 / 黑。

- 选中规则与彩胶一致：`config.json` 的 `tonearm_skin` 固定一款，`auto`（默认）
  则按「歌名 + 歌手」做种子 —— 每首歌固定一支，换歌才换（像换了一张唱片）；
- 托盘菜单「换一支唱臂」会**写进配置**（固定下来），「唱臂：跟随每首歌」恢复 auto；
- 绘制入口 `draw()` 只负责"样子"：坐标已由调用方 translate/rotate 到
  「枢轴 = 原点、+x 指向唱针」的局部坐标系里。
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)


# --------------------------------------------------------------------------- #
# 皮肤表
# --------------------------------------------------------------------------- #
SKINS = [
    {
        "id": "sme3009", "name": "SME 3009 · 铬",
        "desc": "60 年代英国经典：S 形铬管 + 开孔铝唱头架 + 青铜轴承座",
        "shape": "s", "bend": 0.050,
        "tube_edge": "#3a3f46", "tube_body": "#c9d0d9", "tube_hi": "#f8fbfe",
        "shell": "classic", "shell_col": ("#eef1f5", "#a9b0b9", "#484e55"),
        "cart": ("#dfe4ea", "#8a9199"), "accent": "#c9a063",
        "cw": "chrome", "pivot": "bronze", "lift": True, "dial": False,
    },
    {
        "id": "sme-v", "name": "SME V · 黑镁",
        "desc": "直臂黑镁管，唱头直装、无独立唱头架，冷峻现代",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#0e1013", "tube_body": "#454a51", "tube_hi": "#b6bfc8",
        "shell": "integrated", "shell_col": ("#3a3e44", "#191b1f", "#0a0b0d"),
        "cart": ("#31353b", "#15171a"), "accent": "#c8cdd4",
        "cw": "black", "pivot": "chrome", "lift": False, "dial": False,
    },
    {
        "id": "rega", "name": "Rega RB · 哑黑",
        "desc": "一体成型哑光黑直臂，极简英式，配黑柱配重",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#141518", "tube_body": "#3b3f44", "tube_hi": "#9aa0a8",
        "shell": "integrated", "shell_col": ("#2c2f33", "#141518", "#08090a"),
        "cart": ("#2c2f33", "#131417"), "accent": "#9aa1a9",
        "cw": "black", "pivot": "black", "lift": False, "dial": False,
    },
    {
        "id": "sl1200", "name": "SL-1200 · DJ",
        "desc": "Technics 经典银 S 臂 + 黑唱头架 / 白唱头（Shure 风）",
        "shape": "s", "bend": 0.045,
        "tube_edge": "#2f3237", "tube_body": "#c6ccd4", "tube_hi": "#f5f8fb",
        "shell": "dj", "shell_col": ("#3d4147", "#17191c", "#08090b"),
        "cart": ("#f2f4f7", "#b7bdc5"), "accent": "#d0d5db",
        "cw": "chrome", "pivot": "chrome", "lift": True, "dial": True,
    },
    {
        "id": "at95", "name": "AT95E · 绿头",
        "desc": "Audio-Technica 银色直臂 + 经典绿唱头（AT95E 的味道）",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#33373d", "tube_body": "#cdd3db", "tube_hi": "#f7fafd",
        "shell": "classic", "shell_col": ("#edf0f4", "#a8afb8", "#464c53"),
        "cart": ("#5cb96a", "#2e7d3f"), "accent": "#c9ced6",
        "cw": "chrome", "pivot": "black", "lift": True, "dial": False,
    },
    {
        "id": "2m-blue", "name": "2M Blue · 蓝头",
        "desc": "Ortofon 2M Blue：枪灰直管 + 蓝色唱头，北欧简约",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#17191d", "tube_body": "#4a4e55", "tube_hi": "#b7bfc8",
        "shell": "integrated", "shell_col": ("#42464d", "#1d1f23", "#0b0c0e"),
        "cart": ("#3a6fd8", "#1d3f8f"), "accent": "#cfd4da",
        "cw": "black", "pivot": "black", "lift": False, "dial": False,
    },
    {
        "id": "concorde", "name": "Concorde · DJ",
        "desc": "Ortofon Concorde 锥形一体唱头：银管 + 蓝锥头 + 银环",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#33373d", "tube_body": "#cfd5dd", "tube_hi": "#f6f9fc",
        "shell": "cone", "shell_col": ("#4a78d8", "#22429a", "#0e1f52"),
        "cart": ("#3f6fd0", "#1e3f96"), "accent": "#e8ecf1",
        "cw": "chrome", "pivot": "chrome", "lift": True, "dial": False,
    },
    {
        "id": "ekos", "name": "Ekos · 钛灰",
        "desc": "Linn Ekos 气质：黑管 + 烟熏唱头架 + 铬环配重",
        "shape": "straight", "bend": 0.0,
        "tube_edge": "#0e1013", "tube_body": "#30343a", "tube_hi": "#a3abb4",
        "shell": "classic", "shell_col": ("#4a4f57", "#22252a", "#0b0c0e"),
        "cart": ("#23262b", "#0e0f11"), "accent": "#c7ccd3",
        "cw": "ring", "pivot": "black", "lift": False, "dial": True,
    },
]

BY_ID = {s["id"]: s for s in SKINS}


def pick(cfg, key):
    """挑一支唱臂：config 指定优先，否则按 key 哈希定（同一首歌固定一支）。"""
    want = str((cfg or {}).get("tonearm_skin", "auto") or "auto")
    if want in BY_ID:
        return BY_ID[want]
    if not key:
        return SKINS[0]
    return SKINS[_seed(key) % len(SKINS)]


def _seed(key):
    """稳定哈希（内置 hash 带随机盐，跨进程会变，不能用）。"""
    h = 2166136261
    for ch in ("tonearm|auto|" + key).encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


def next_of(skin):
    """换下一支。"""
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


def _tube_path(L, shape, bend):
    """唱臂管的路径（局部坐标：枢轴为原点）。"""
    path = QPainterPath()
    x0, x1 = -0.22 * L, 0.86 * L
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
        path.quadTo(QPointF(x0 + span * 0.55, b * 2.4), QPointF(x1, 0.0))
    else:
        path.lineTo(x1, 0.0)
    return path


def _radial(cols, cx, cy, r):
    g = QRadialGradient(cx, cy, r)
    g.setColorAt(0.0, QColor(cols[0]))
    g.setColorAt(0.62, QColor(cols[1]))
    g.setColorAt(1.0, QColor(cols[2]))
    return g


# --------------------------------------------------------------------------- #
# 静态部分（不随唱臂转动）：信号线
# --------------------------------------------------------------------------- #
def draw_static(p, px, py, R, skin):
    """枢轴处伸出的信号线：一小段弧线拐向右上，末端淡出。"""
    p.save()
    p.translate(px, py)
    path = QPainterPath(QPointF(-R * 0.02, -R * 0.05))
    path.cubicTo(QPointF(R * 0.06, -R * 0.30),
                 QPointF(R * 0.30, -R * 0.42),
                 QPointF(R * 0.52, -R * 0.46))
    g = QLinearGradient(0.0, 0.0, R * 0.52, -R * 0.46)
    g.setColorAt(0.0, QColor(22, 24, 28, 235))
    g.setColorAt(0.75, QColor(22, 24, 28, 150))
    g.setColorAt(1.0, QColor(22, 24, 28, 0))
    pen = QPen(QBrush(g), max(1.6, R * 0.016))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


# --------------------------------------------------------------------------- #
# 主绘制：枢轴 = 原点，+x 指向唱针
# --------------------------------------------------------------------------- #
def draw(p, R, L, skin):
    tube_w = R * 0.026
    path = _tube_path(L, skin.get("shape", "straight"), float(skin.get("bend") or 0.0))

    # 盘面上的柔影（整体下移一点）
    p.save()
    p.translate(0.0, R * 0.045)
    _stroke(p, path, QColor(0, 0, 0, 66), tube_w * 1.30)
    p.restore()

    # 管身：暗边 -> 亮面 -> 居中高光，弯管上也保持圆柱感
    _stroke(p, path, skin["tube_edge"], tube_w)
    _stroke(p, path, skin["tube_body"], tube_w * 0.58)
    p.save()
    p.translate(0.0, -tube_w * 0.17)
    _stroke(p, path, skin["tube_hi"], tube_w * 0.24)
    p.restore()

    _draw_counterweight(p, R, skin)
    _draw_pivot(p, R, skin)
    _draw_head(p, R, L, skin)


def _draw_head(p, R, L, skin):
    """唱头架 / 唱头 / 唱针（带 offset angle，像真臂的偏角）。"""
    p.save()
    p.translate(L * 0.845, 0.0)
    p.rotate(22.0)
    kind = skin.get("shell", "classic")
    shell_cols = skin.get("shell_col", ("#e8ecf1", "#9aa1aa", "#42474e"))
    cart = skin.get("cart", ("#d5dae1", "#7c828b"))
    accent = QColor(skin.get("accent", "#c9ced6"))

    if kind == "cone":
        # Ortofon Concorde：锥形一体唱头（前宽后窄），加一道银环
        w0, w1, ln = R * 0.044, R * 0.070, R * 0.200
        g = QLinearGradient(0.0, -w1, 0.0, w1)
        g.setColorAt(0.0, QColor(shell_cols[0]))
        g.setColorAt(0.38, QColor(cart[0]))
        g.setColorAt(0.72, QColor(cart[1]))
        g.setColorAt(1.0, QColor(shell_cols[2]))
        poly = QPolygonF([QPointF(-R * 0.010, -w0 / 2.0),
                          QPointF(ln - R * 0.026, -w1 / 2.0),
                          QPointF(ln, -w1 * 0.28),
                          QPointF(ln, w1 * 0.28),
                          QPointF(ln - R * 0.026, w1 / 2.0),
                          QPointF(-R * 0.010, w0 / 2.0)])
        path = QPainterPath()
        path.addPolygon(poly)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1.0))
        p.setBrush(QBrush(g))
        p.drawPath(path)
        p.setPen(QPen(QBrush(accent), R * 0.014))
        p.drawLine(QPointF(ln - R * 0.052, -w1 * 0.40),
                   QPointF(ln - R * 0.052, w1 * 0.40))
        tipx = ln
    else:
        # 唱头架（classic / dj）；integrated 直接画唱头体
        if kind == "integrated":
            hw, hh = R * 0.150, R * 0.062
            hg = QLinearGradient(0.0, -hh, 0.0, hh)
            hg.setColorAt(0.0, QColor(shell_cols[0]))
            hg.setColorAt(0.45, QColor(cart[0]))
            hg.setColorAt(1.0, QColor(shell_cols[2]))
            path = QPainterPath()
            path.addRoundedRect(QRectF(-R * 0.016, -hh / 2.0, hw, hh),
                                hh * 0.30, hh * 0.30)
            p.setPen(QPen(QColor(0, 0, 0, 110), 1.0))
            p.setBrush(QBrush(hg))
            p.drawPath(path)
            _screws(p, R, hw, hh, accent)
        else:
            hw, hh = R * 0.150, R * 0.056
            hg = QLinearGradient(0.0, -hh, 0.0, hh)
            hg.setColorAt(0.0, QColor(shell_cols[0]))
            hg.setColorAt(0.45, QColor(shell_cols[1]))
            hg.setColorAt(1.0, QColor(shell_cols[2]))
            path = QPainterPath()
            path.addRoundedRect(QRectF(-R * 0.016, -hh / 2.0, hw, hh),
                                hh * 0.30, hh * 0.30)
            p.setPen(QPen(QColor(0, 0, 0, 110), 1.0))
            p.setBrush(QBrush(hg))
            p.drawPath(path)
            if kind == "dj":
                # DJ 架：顶面一条银边 + 指拔
                p.setPen(QPen(QBrush(accent), R * 0.008))
                p.drawLine(QPointF(-R * 0.008, -hh * 0.34),
                           QPointF(hw - R * 0.024, -hh * 0.34))
                p.setPen(QPen(QBrush(accent), R * 0.011))
                p.drawArc(QRectF(hw - R * 0.052, -R * 0.030, R * 0.055,
                                 R * 0.060), -60 * 16, 150 * 16)
            else:
                # 开孔铝架：两个减重孔
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 120))
                p.drawEllipse(QPointF(R * 0.036, 0.0), R * 0.011, R * 0.011)
                p.drawEllipse(QPointF(R * 0.082, 0.0), R * 0.011, R * 0.011)
        # 唱头体（架前下方的一条）
        cw, ch = R * 0.088, R * 0.040
        cg = QLinearGradient(0.0, -ch, 0.0, ch)
        cg.setColorAt(0.0, QColor(cart[0]))
        cg.setColorAt(1.0, QColor(cart[1]))
        p.setPen(QPen(QColor(0, 0, 0, 130), 1.0))
        p.setBrush(QBrush(cg))
        p.drawRoundedRect(QRectF(hw - cw - R * 0.004, R * 0.008, cw, ch),
                          ch * 0.35, ch * 0.35)
        tipx = hw
    # 指拔（classic / dj / cone 的皮肤里有）
    if skin.get("lift") and kind in ("classic", "dj"):
        p.setPen(QPen(QBrush(accent), R * 0.008))
        p.drawArc(QRectF(-R * 0.036, -R * 0.030, R * 0.055, R * 0.058),
                  -40 * 16, 140 * 16)

    # 唱针：悬臂 + 针尖反光
    p.setPen(QPen(QColor(214, 218, 224, 235), R * 0.0085))
    p.drawLine(QPointF(tipx - R * 0.008, 0.0),
               QPointF(tipx + R * 0.030, R * 0.018))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(246, 249, 253, 245))
    p.drawEllipse(QPointF(tipx + R * 0.030, R * 0.018), R * 0.010, R * 0.010)
    p.setBrush(QColor(255, 255, 255, 120))
    p.drawEllipse(QPointF(tipx + R * 0.027, R * 0.014), R * 0.004, R * 0.004)
    p.restore()


def _screws(p, R, hw, hh, accent):
    """唱头安装螺丝（两颗小点）。"""
    p.setPen(Qt.PenStyle.NoPen)
    c = QColor(accent)
    c.setAlpha(220)
    p.setBrush(c)
    p.drawEllipse(QPointF(hw - R * 0.038, -hh * 0.22), R * 0.008, R * 0.008)
    p.drawEllipse(QPointF(hw - R * 0.038, hh * 0.22), R * 0.008, R * 0.008)


def _draw_counterweight(p, R, skin):
    """配重（枢轴后方）：铬柱 / 黑柱 / 黑柱加铬环。"""
    kind = skin.get("cw", "chrome")
    rect = QRectF(-R * 0.300, -R * 0.052, R * 0.150, R * 0.104)
    if kind == "chrome":
        g = _radial(("#e7ecf2", "#7d838c", "#2a2d33"),
                    -R * 0.28, -R * 0.02, R * 0.11)
    else:
        g = QLinearGradient(0.0, -R * 0.052, 0.0, R * 0.052)
        g.setColorAt(0.0, QColor("#5a5f66" if kind == "ring" else "#3f434a"))
        g.setColorAt(0.4, QColor("#26292e"))
        g.setColorAt(1.0, QColor("#0e1012"))
    p.setPen(QPen(QColor(0, 0, 0, 120), 1.2))
    p.setBrush(QBrush(g))
    p.drawEllipse(rect)
    if kind == "ring":
        p.setPen(QPen(QBrush(QColor("#c9cfd6")), R * 0.012))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(-R * 0.272, -R * 0.048),
                   QPointF(-R * 0.272, R * 0.048))
    # 尾栓
    p.setPen(QPen(QBrush(QColor("#7d838c")), R * 0.010))
    p.drawLine(QPointF(-R * 0.316, 0.0), QPointF(-R * 0.352, 0.0))


def _draw_pivot(p, R, skin):
    """轴承座：青铜 / 铬 / 黑，外加一个防滑小刻度（部分皮肤）。"""
    kind = skin.get("pivot", "chrome")
    if kind == "bronze":
        g = _radial(("#f0d5a6", "#a8783c", "#3f2a12"), -R * 0.020, -R * 0.020, R * 0.09)
    elif kind == "chrome":
        g = _radial(("#e9eef4", "#7b818a", "#2c3036"), -R * 0.020, -R * 0.020, R * 0.09)
    else:
        g = _radial(("#55595f", "#232629", "#0b0c0e"), -R * 0.020, -R * 0.020, R * 0.09)
    p.setPen(QPen(QColor(0, 0, 0, 120), 1.2))
    p.setBrush(QBrush(g))
    p.drawEllipse(QRectF(-R * 0.072, -R * 0.072, R * 0.144, R * 0.144))
    p.setPen(QPen(QColor(18, 20, 23, 210), R * 0.013))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(-R * 0.031, -R * 0.031, R * 0.062, R * 0.062))
    if skin.get("dial"):
        p.setPen(QPen(QBrush(QColor(skin.get("accent", "#c9ced6"))), R * 0.009))
        p.drawArc(QRectF(-R * 0.098, -R * 0.098, R * 0.196, R * 0.196),
                  -80 * 16, 90 * 16)
