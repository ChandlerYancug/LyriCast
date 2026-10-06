# -*- coding: utf-8 -*-
"""开发用：翻译折行 / 歌词边缘不裁切的渲染检查。

三组检查（输出 dev/transwrap_check.png / transwrap_converge_check.png /
left_ink_check.png，并在控制台打印关键数值）：
  1. 短/中/超长翻译的折行与缩放；
  2. 折行时“四周汇聚”入场的中间帧；
  3. “just …” 这类首字母带负 bearing 的行，左缘墨迹不再被裁
     （\u201c修复前\u201d 对照请把 _ink_pad 清零，见 left_ink_check 的注释）。
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from utf8mode import ensure_utf8  # noqa: E402  （中文 Windows 默认 GBK）
ensure_utf8()

from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from fullscreen import FullscreenView, TEXT_X

app = QApplication([])
for n in sorted(os.listdir(os.path.join(BASE, "fonts"))):
    if n.lower().endswith((".otf", ".ttf")):
        QFontDatabase.addApplicationFont(os.path.join(BASE, "fonts", n))
with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
    cfg = json.load(f)

ZH_MID = "这是一句比较长的中文翻译大概三十多个字来测试折行效果"
ZH_LONG = ("这是一句特别长的翻译用来确认它会不会在右边被硬切掉一截"
           "如果不折行的话它一定会超出歌词区的宽度然后被裁切框切掉"
           "所以现在应该折成两行显示才对")
cases = [
    ("短翻译（不折行）", (0.0, "prev", "上一句"),
     (3.0, "And I left my scarf there", "我的围巾留在那儿"),
     (9.0, "next", "下一句")),
    ("中长翻译（折两行）", (0.0, "prev", "上一句"),
     (3.0, "And I left my scarf there at your sister's house", ZH_MID),
     (9.0, "next", "下一句")),
    ("超长翻译（两行还不够）", (0.0, "prev", "上一句"),
     (3.0, "And I left my scarf there at your sister's house", ZH_LONG),
     (9.0, "next", "下一句")),
]


def new_view(lines, w=1600, h=900, x0=None):
    v = FullscreenView(cfg)
    v.resize(w, h)
    v.title, v.artist = "", ""
    v.set_lyrics({"synced": True, "lines": list(lines),
                  "ends": [ln[0] + 2.6 for ln in lines]})
    for fn in sorted(glob.glob(os.path.join(BASE, "cache", "art", "*.img"))):
        if os.path.getsize(fn) > 30000:
            with open(fn, "rb") as fh:
                v.set_album_art_bytes(fh.read())
            v._bg_ts -= 1.0
            break
    v._vinyl_fade_ts -= 1.0
    return v


def shot(v):
    img = QImage(v.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    v.render(img)
    return img


# ---- 1. 折行 / 缩放 ---- #
tiles = []
for tag, a, b, c in cases:
    v = new_view((a, b, c))
    v.set_position(8.6, True, precise=True)     # 填充快走完，翻译全部显现
    v._playing = False
    for _ in range(20):
        v._tick()
    pt_t, rows = v._trans_layout(("trans", v._cur_index), b[2],
                                 v._base_pt * 0.60, v.width() * 0.46)
    print("%-20s 字号 %.1fpt（基准 %.1f）→ %d 行: %s"
          % (tag, pt_t, v._base_pt * 0.60, len(rows), " ｜ ".join(rows)))
    tiles.append((tag, shot(v).copy(780, int(v.height() * 0.28), 810, 340)))

out = QImage(810, 340 * len(tiles), QImage.Format.Format_ARGB32)
out.fill(QColor(0, 0, 0))
p = QPainter(out)
p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
for i, (tag, tile) in enumerate(tiles):
    p.drawImage(0, i * 340, tile)
    p.setPen(QColor(255, 214, 120))
    f = p.font()
    f.setPointSizeF(12)
    p.setFont(f)
    p.drawText(8, i * 340 + 330, tag)
p.end()
out.save(os.path.join(BASE, "dev", "transwrap_check.png"))
print("saved dev/transwrap_check.png")

# ---- 2. 折行 + 汇聚中间帧 ---- #
v = new_view((cases[1][1], cases[1][2], cases[1][3]))
shots = []
for t in (3.8, 4.6, 5.6, 8.6):
    v.set_position(t, True, precise=True)
    v._playing = False
    for _ in range(12):
        v._tick()
    shots.append((t, v._frac, shot(v).copy(780, int(v.height() * 0.28),
                                           810, 320)))
out = QImage(810, 320 * len(shots), QImage.Format.Format_ARGB32)
out.fill(QColor(0, 0, 0))
p = QPainter(out)
for i, (t, fr, tile) in enumerate(shots):
    p.drawImage(0, i * 320, tile)
    p.setPen(QColor(255, 214, 120))
    f = p.font()
    f.setPointSizeF(12)
    p.setFont(f)
    p.drawText(8, i * 320 + 310, "t=%.1fs  填充 %.0f%%" % (t, fr * 100))
p.end()
out.save(os.path.join(BASE, "dev", "transwrap_converge_check.png"))
print("saved dev/transwrap_converge_check.png")

# ---- 3. 首字母负 bearing：左缘不裁 + 两行翻译不压下一句 ---- #
W, H = 1600, 900
area_l = W * TEXT_X
lines = [(0.0, "prev", ""),
         (3.0, "just know that i want you to stay", "只是想让你留下来"),
         (9.0, "next", "")]
v = new_view(lines)
v.set_position(8.5, True, precise=True)
v._playing = False
for _ in range(30):
    v._tick()
img = shot(v)
rows = 0
for y in range(int(H * 0.30), int(H * 0.60)):
    for x in range(int(area_l) - 8, int(area_l) - 0):
        c = img.pixelColor(x, y)
        if c.red() + c.green() + c.blue() > 90:
            rows += 1
            break
print("left ink pad=%s  左缘外墨迹行数=%d（修复前为 0）"
      % (tuple(round(x, 2) for x in v._ink_pad), rows))

lines2 = [(0.0, "prev", "上一句"),
          (3.0, "And I left my scarf there at your sister's house", ZH_MID),
          (9.0, "next line here", "下一句也有一行翻译")]
v2 = new_view(lines2)
v2.set_position(8.6, True, precise=True)
v2._playing = False
for _ in range(30):
    v2._tick()
n0 = v2._cur_index
t0, b0 = v2._line_extents(n0)
t1, b1 = v2._line_extents(n0 + 1)
gap_px = (v2._line_y[n0 + 1] - t1) - (v2._line_y[n0] + b0)
print("翻译行数=%d  当前行下缘到下一句上缘间距=%.1f px（>0 即不重叠）"
      % (v2._n_trans[n0], gap_px))

combo = QImage(1600, 600, QImage.Format.Format_ARGB32)
combo.fill(QColor(0, 0, 0))
y0 = int(H * 0.43) - 170                  # 焦点行附近（有无裁切都看这一带）
p = QPainter(combo)
p.drawImage(0, 0, shot(v).copy(0, y0, 1600, 300))          # 上半：just 行
p.drawImage(0, 300, shot(v2).copy(0, y0, 1600, 300))       # 下半：折行布局
p.end()
combo.save(os.path.join(BASE, "dev", "left_ink_check.png"))
print("saved dev/left_ink_check.png")

# ---- 4. 两条绘制路径零漂移：逐字路径（全字已归位）vs 整行路径 ---- #
# 回归点：中英混排时，以前逐字用各自字体的 AlignTop（英文偏上）、整行用共用
# baseline，动画结束的瞬间英文会往下跳一下。现在两边都锚在同一条 baseline 上，
# 同一帧用两种路径渲染应当几乎逐像素一致。
MIXED = "我的围巾 Ed Sheeran 留那里"


def path_drift():
    """同一句、两种绘制路径：
    * 显著性差异行（≥ 8 个像素差 > 25）—— 亚像素相位造成的笔划边缘 AA 不算；
    * 中英文两段的墨迹上缘差 —— 这才是“英文名字上下跳”的直接指标。
    """
    imgs = []
    band = None
    for frac in (0.75, 0.95):        # 0.75 = 逐字路径（< 0.78，所有字都飞完后）
        vv = new_view(((0.0, "prev", "上一句"),
                       (3.0, "And I left my scarf there", MIXED),
                       (9.0, "next", "下一句")))
        vv.set_position(8.6, True, precise=True)
        vv._playing = False
        for _ in range(30):
            vv._tick()
        # 渲染 80 帧、播放时间轴往前推：让每个字依次起飞并全部归位
        for k in range(80):
            vv._frac = frac
            vv._elapsed = 1.0 + k / 60.0
            shot(vv)
        if band is None:
            segs = vv._segs_cache[vv._cur_index]
            y_t = (vv._focus_cy() - vv._row_h * len(segs) / 2.0
                   + vv._row_h * len(segs))
            band = (int(y_t) + 6,     # 让开主句的字尾（主句填充值两边不同）
                    int(y_t + 2 * vv._trans_h) + 24)
        imgs.append(shot(vv))

    x_lo = int(1600 * TEXT_X) - 10
    x_hi = int(1600 * 0.98)
    sig_rows = 0
    for y in range(band[0], band[1]):
        n = 0
        for x in range(x_lo, x_hi):
            ca = imgs[0].pixelColor(x, y)
            cb = imgs[1].pixelColor(x, y)
            if (abs(ca.red() - cb.red()) > 25
                    or abs(ca.green() - cb.green()) > 25):
                n += 1
        if n >= 15:      # 阈值高于笔画边缘的亚像素 AA 差异（通常 ≤ 6/行）
            sig_rows += 1

    def ink_top(img, x0, x1):
        for y in range(band[0], band[1]):
            for x in range(x0, x1):
                c = img.pixelColor(x, y)
                if c.red() + c.green() + c.blue() > 240:
                    return y
        return -1

    cjk_top = (ink_top(imgs[0], x_lo + 10, x_lo + 115),
               ink_top(imgs[1], x_lo + 10, x_lo + 115))
    lat_top = (ink_top(imgs[0], x_lo + 150, x_lo + 260),
               ink_top(imgs[1], x_lo + 150, x_lo + 260))
    return sig_rows, cjk_top, lat_top


sig, cjk_top, lat_top = path_drift()
print("两条绘制路径：显著差异行=%d（0 = 不跳；亚像素 AA 不计）  "
      "中文墨迹上缘差=%d px，英文墨迹上缘差=%d px（都应 ≈ 0）"
      % (sig, abs(cjk_top[0] - cjk_top[1]), abs(lat_top[0] - lat_top[1])))

# ---- 5. 同帧重渲（同一路径）应当零差异：确认动画本身不依赖调用次数 ---- #
MIXED_ROW = "这是一句比较长的中文翻译大概三十多个字来测试折行效果"


def repaint_diff(frac, elapsed):
    def render():
        vv = new_view((cases[1][1],
                       (cases[1][2][0], cases[1][2][1], MIXED_ROW),
                       cases[1][3]))
        vv.set_position(8.6, True, precise=True)
        vv._playing = False
        for _ in range(30):
            vv._tick()
        vv._frac = frac
        vv._elapsed = elapsed
        return shot(vv)
    a, b = render(), render()
    band = int(900 * 0.43) + 60
    n = 0
    for y in range(band - 20, band + 140):
        for x in range(int(1600 * 0.52) - 10, int(1600 * 0.98)):
            ca = a.pixelColor(x, y)
            cb = b.pixelColor(x, y)
            if (abs(ca.red() - cb.red()) > 8
                    or abs(ca.green() - cb.green()) > 8):
                n += 1
                break
    return n


print("汇聚中重渲差异行 = %d（0 = 确定性、可重复）" % repaint_diff(0.45, 1.2))
