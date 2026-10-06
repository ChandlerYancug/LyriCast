# -*- coding: utf-8 -*-
"""把每一种彩胶材质渲染成一张对比图（开发用，不弹窗口）。

输出：dev/materials_preview.png（4 列网格，一格一款材质）
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PyQt6.QtWidgets import QApplication

import vinyl
from fullscreen import FullscreenView

app = QApplication([])
for n in sorted(os.listdir(os.path.join(BASE, "fonts"))):
    if n.lower().endswith((".otf", ".ttf")):
        QFontDatabase.addApplicationFont(os.path.join(BASE, "fonts", n))
with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
    cfg = dict(json.load(f))

cfg["vinyl_material"] = "auto"
res, tgt = None, 0
for fn in sorted(glob.glob(os.path.join(BASE, "cache", "lyrics", "*.json"))):
    try:
        r = (json.load(open(fn, encoding="utf-8")) or {}).get("result") or {}
    except Exception:
        continue
    if r.get("synced") and len(r.get("lines") or []) > 20:
        res = r
        tgt = 5
        break

arts = []
for fn in sorted(glob.glob(os.path.join(BASE, "cache", "art", "*.img"))):
    try:
        if os.path.getsize(fn) > 60000:
            with open(fn, "rb") as fh:
                data = fh.read()
            if not QImage.fromData(data).isNull():
                arts.append(data)
        if len(arts) >= 2:
            break
    except OSError:
        continue
print("art count", len(arts), "lyrics", bool(res))

v = FullscreenView(cfg)
v.resize(1600, 900)
v.title, v.artist = "彩胶材质预览", "vinyl materials"
if res:
    v.set_lyrics(res)
if arts:
    v.set_album_art_bytes(arts[0])
    v._bg_ts -= 1.0

cell = 430
cols = 4
rows = (len(vinyl.MATERIALS) + cols - 1) // cols
out = QImage(cell * cols, cell * rows, QImage.Format.Format_ARGB32)
out.fill(QColor(12, 12, 14))
op = QPainter(out)
op.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

w, h = v.width(), v.height()
R = max(60.0, min(h * 0.37, w * 0.27))
cx, cy = w * 0.24, h * 0.45
crop_x = int(cx - R * 1.42)
crop_y = int(cy - R * 1.18)
crop_w = crop_h = int(R * 2.84)

for i, mat in enumerate(vinyl.MATERIALS):
    v._vinyl_mat = mat
    v._plate_key = None
    v.set_position(float(res["lines"][tgt][0]) + 0.4 if res else 5.0,
                   True, precise=True)
    v._playing = False
    if len(arts) > 1 and mat["id"] in ("splatter", "hologram", "clear"):
        v.set_album_art_bytes(arts[1])
        v._bg_ts -= 1.0
    elif arts:
        v.set_album_art_bytes(arts[0])
        v._bg_ts -= 1.0
    # 换封面会触发“切歌换盘”过渡，这里直接跳过，不然拍到的是新旧盘混合帧
    v._plate_prev = None
    v._vinyl_fade_ts -= 1.0
    for _ in range(6):
        v._tick()
    img = QImage(v.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    v.render(img)
    tile = img.copy(crop_x, crop_y, crop_w, crop_h)
    x = (i % cols) * cell
    y = (i // cols) * cell
    op.drawImage(QRectF(x + 8, y + 8, cell - 16, cell - 16), tile,
                 QRectF(tile.rect()))
    op.setPen(QColor(255, 255, 255, 210))
    f = op.font()
    f.setPointSizeF(15.0)
    op.setFont(f)
    op.drawText(x + 26, y + cell - 22, "%d  %s" % (i + 1, mat["name"]))
op.end()
out.save(os.path.join(BASE, "dev", "materials_preview.png"))
print("saved dev/materials_preview.png", out.width(), out.height())
