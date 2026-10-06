# -*- coding: utf-8 -*-
"""生成黑胶播放器效果预览图（开发用，不弹窗口）。

优先用 cache/ 里的真实歌词 + 真实封面渲染（比构造数据更能暴露问题），
取不到就退回内置示例。输出：项目根目录 preview_lyrics_style.png
"""
import glob
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
sys.path.insert(0, BASE)

# 注意：苹方等属于“用户字体”，离屏字体库看不到，这里用真实平台渲染，
# 但从不 show() 窗口，所以不会弹任何东西。
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QFontDatabase, QImage

from fullscreen import FullscreenView

app = QApplication([])
# 注册 fonts/ 里的随包字体（与正式启动一致）
for _n in sorted(os.listdir(os.path.join(BASE, "fonts"))):
    if _n.lower().endswith((".otf", ".ttf")):
        QFontDatabase.addApplicationFont(os.path.join(BASE, "fonts", _n))
with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
    cfg = json.load(f)


def real_lyrics():
    """挑一条最“完整”的真实缓存：行数多、有翻译、有逐词时间。"""
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
        if ntr < 5 or nw < 5:
            continue
        if ntr > score:
            best, score = res, ntr
    return best


def real_art():
    for fn in sorted(glob.glob(os.path.join(BASE, "cache", "art", "*.img"))):
        try:
            if os.path.getsize(fn) < 30000:
                continue
            with open(fn, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if not QImage.fromData(data).isNull():
            return data
    return None


res = real_lyrics()
if res:
    lines = res["lines"]
    tgt = next((i for i, ln in enumerate(lines)
                if i >= 3 and len(ln) > 2 and ln[2]), 0)
    v_title, v_artist = "（真实缓存歌词）", "%d 行 · 含逐词" % len(lines)
else:                       # 兜底：内置示例
    lines = [
        (0.0, "Thought I'd end up with Sean", "我以为会跟 Sean 走到最后"),
        (4.0, "But he wasn't a match", "但他不是对的人"),
        (8.0, "Wrote some songs about Ricky", "写了几首关于 Ricky 的歌"),
        (12.0, "Now I listen and laugh", "现在听着只会笑"),
        (16.0, "Even almost got married", "甚至差点结了婚"),
        (20.0, "And for Pete, I'm so thankful", "对 Pete，我心怀感激"),
        (24.0, "Wish I could say thank you to Malcolm", "希望能对 Malcolm 说声谢谢"),
        (28.0, "Cause he was an angel", "因为他曾是个天使"),
        (32.0, "Plus, I met someone else", "另外，我遇到了别人"),
        (36.0, "We havin' better discussions", "我们聊得更合拍"),
    ]
    res = {"synced": True, "lines": lines,
           "ends": [t + 3.0 for t, _, _ in lines]}
    tgt = 3
    v_title, v_artist = "thank u, next", "Ariana Grande"

v = FullscreenView(cfg)
v.resize(1600, 900)
v.set_track({"title": v_title, "artist": v_artist})   # 顺带定下彩胶材质
v.set_lyrics(res)
art = real_art()
if art:
    v.set_album_art_bytes(art)
    v._bg_ts -= 1.0                      # 跳过 0.5s 交叉过渡
v._vinyl_fade_ts -= 1.0                  # 跳过切歌“换盘”过渡
# 定格在目标行开始后 0.3s：翻译正好在“汇聚”途中
v.set_position(float(lines[tgt][0]) + 0.3, True, precise=True)
v._playing = False
for _ in range(40):
    time.sleep(0.002)
    v._tick()
img = QImage(v.size(), QImage.Format.Format_ARGB32)
img.fill(QColor(0, 0, 0))
v.render(img)
out = os.path.join(BASE, "preview_lyrics_style.png")
img.save(out)
print("saved", out, "dpr=%.2f" % v._dpr)
