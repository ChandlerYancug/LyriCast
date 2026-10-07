# -*- coding: utf-8 -*-
"""生成 README 用的截图与演示动图（开发用）：docs/images/{player,bar,demo}。

- 用缓存里的真实歌词 + 真实封面渲染，比构造数据好看也更真实；
- GIF 按真实时间推进（弹簧/黑胶旋转都是时间驱动的），10 fps、640×360，
  帧间共用同一套调色板，避免闪烁；
- 不弹任何窗口（离屏渲染）。

跑法（项目根目录）：python dev/make_shots.py
"""

import glob
import io
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from utf8mode import ensure_utf8  # noqa: E402  （中文 Windows 默认 GBK）
ensure_utf8()

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QImage
from PyQt6.QtWidgets import QApplication

from fullscreen import FullscreenView
from overlay import LyricOverlay

OUT_DIR = os.path.join(BASE, "docs", "images")
GIF_SIZE = (640, 360)
GIF_FPS = 10
GIF_SECONDS = 4.5

app = QApplication([])
for n in sorted(os.listdir(os.path.join(BASE, "fonts"))):
    if n.lower().endswith((".otf", ".ttf", ".ttc")):
        QFontDatabase.addApplicationFont(os.path.join(BASE, "fonts", n))
with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
    cfg = json.load(f)
# README 的预览用固定的、上镜的一套（不跟着用户自己的 config 变）；
# 彩胶则展示新默认：按封面主色自动配（这里拿到什么都随封面，不做干预）
cfg = dict(cfg)


def real_lyrics():
    """挑一条“有翻译 + 有逐词”的真实缓存歌词。"""
    best, score = None, 0
    for fn in sorted(glob.glob(os.path.join(BASE, "cache", "lyrics", "*.json"))):
        try:
            with open(fn, "r", encoding="utf-8") as f:
                res = (json.load(f) or {}).get("result") or {}
        except Exception:
            continue
        lines = res.get("lines") or []
        if not res.get("synced") or len(lines) < 20:
            continue
        ntr = sum(1 for ln in lines if len(ln) > 2 and ln[2])
        nw = sum(1 for w in (res.get("words") or []) if w)
        if ntr > score and nw > 5:
            best, score = res, ntr
    return best


def real_art():
    for fn in sorted(glob.glob(os.path.join(BASE, "cache", "art", "*.img"))):
        try:
            if os.path.getsize(fn) < 30000:
                continue
            with open(fn, "rb") as f:
                return f.read()
        except OSError:
            continue
    return None


def make_view(res, art, size=(1600, 900), title="LyriCast"):
    v = FullscreenView(cfg)
    v.resize(*size)
    v.title, v.artist = title, ""
    v.set_lyrics(res)
    if art:
        v.set_album_art_bytes(art)
        v._bg_ts -= 1.0
    v._vinyl_fade_ts -= 1.0
    return v


def shot(widget):
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    widget.render(img)
    return img


def png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    res = real_lyrics()
    art = real_art()
    if not res:
        print("没有可用的缓存歌词（先在真实环境放几首歌再跑）")
        return

    lines = res["lines"]
    # 挑一句“有翻译、下一句在 3~6.5 秒后”的行做主角（动图能完整覆盖它）
    def _ok(i):
        return (i >= 2 and i + 1 < len(lines) and len(lines[i]) > 2
                and lines[i][2]
                and 3.0 <= lines[i + 1][0] - lines[i][0] <= 6.5)
    idx = next((i for i in range(len(lines)) if _ok(i)), None)
    if idx is None:
        idx = next((i for i, ln in enumerate(lines)
                    if i >= 2 and len(ln) > 2 and ln[2]), 0)

    # ---- 1. 播放器截图（定格在翻译汇聚中/刚汇聚完）----
    v = make_view(res, art)
    v.set_position(float(lines[idx][0]) + 1.5, True, precise=True)
    v._playing = False
    for _ in range(40):
        v._tick()
    img = shot(v)
    img.save(os.path.join(OUT_DIR, "player.png"))
    print("saved docs/images/player.png  (%d×%d)" % (img.width(), img.height()))

    # ---- 2. 悬浮歌词条截图 ----
    ov = LyricOverlay(cfg)
    ov.resize(900, 300)
    ov.title, ov.artist = "LyriCast", ""       # 不假托真实曲名
    ov.set_lyrics(res)
    ov.set_position(float(lines[idx][0]) + 1.8, True, precise=True)
    ov._playing = False
    for _ in range(40):
        ov._tick()
    bar = shot(ov)
    bar.save(os.path.join(OUT_DIR, "bar.png"))
    print("saved docs/images/bar.png  (%d×%d)" % (bar.width(), bar.height()))

    # ---- 3. 演示动图：从这句开唱到下一句（含逐字填充 + 汇聚 + 滚动）----
    span = min(GIF_SECONDS, lines[idx + 1][0] - lines[idx][0] + 0.4)
    t0 = max(0.0, float(lines[idx][0]) - 0.3)
    v2 = make_view(res, art, size=(960, 540))
    v2._bar_target = 0.0                 # 控制条别出来抢戏
    v2.set_position(t0, True, precise=True)   # playing=True：时间轴走真实时间
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow 才能生成 GIF（pip install pillow）")
        return
    frames, palette_src = [], None
    step = 1.0 / GIF_FPS
    n_frames = int(span * GIF_FPS)
    for i in range(n_frames):
        time.sleep(step)
        v2._tick()
        img = shot(v2).scaled(GIF_SIZE[0], GIF_SIZE[1],
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        pil = Image.open(io.BytesIO(png_bytes(img))).convert("RGB")
        if palette_src is None:
            palette_src = pil.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
            frame = palette_src
        else:
            frame = pil.quantize(palette=palette_src, dither=Image.Dither.NONE)
        frames.append(frame)
    gif_path = os.path.join(OUT_DIR, "demo.gif")
    frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / GIF_FPS), loop=0, optimize=True)
    print("saved %s  (%d 帧, %.1f MB)"
          % (os.path.relpath(gif_path, BASE), len(frames),
             os.path.getsize(gif_path) / 1e6))


if __name__ == "__main__":
    main()
