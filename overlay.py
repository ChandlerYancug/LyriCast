# -*- coding: utf-8 -*-
"""悬浮歌词条：半透明置顶小窗，逐行同步 + 平滑动画。

动画思路（不需要重型动画框架，60fps 自绘即可）：
  * 位置每收到一次音箱上报就重置，帧间用 elapsed * 播放速率 插值 -> 行内进度连续
  * 当前行索引变化时，滚动位置用指数缓动逼近 -> 类似"弹簧"的顺滑滚屏
  * 当前行做"左->右填充"的高亮（模仿 Apple Music 的行内进度）
  * 非当前行按距离衰减透明度并轻微缩小，配合上下渐变遮罩形成层次
"""

import math
import time
from bisect import bisect_right

import timing

from PyQt6.QtCore import QByteArray, QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import QMenu, QWidget

from speakers.http import APP_NAME

DEFAULT_FONT = "SF Pro Display"   # 拉丁（随包）
DEFAULT_CJK = "Noto Sans SC"       # 中文回退（思源黑体 / Noto CJK）


def font_chain(fam, cjk):
    """家族链：拉丁在前、中文在后，Qt 会逐字符往后回退。

    随包的 OFL 字体（Inter / Noto Sans S Chinese，见 fonts/README.md）排在
    用户指定字体之后、系统字体之前 —— 陌生环境里没装任何字体也能开箱即用。
    """
    out = [fam, fam + " Black", fam + " Heavy", fam + " Bold",
           fam + " Medium"]
    # 随包拉丁：Inter（观感接近 SF Pro）
    out += ["Inter Black", "Inter Heavy", "Inter Bold", "Inter Medium",
            "Inter"]
    if cjk and cjk != fam:
        out += [cjk + " Black", cjk + " Heavy", cjk + " Bold",
                cjk + " Medium", cjk]
    # 随包中文：思源黑体简体子集（Noto Sans CJK / Source Han Sans，OFL）
    out += ["Noto Sans S Chinese Black", "Noto Sans S Chinese Bold",
            "Noto Sans S Chinese", "Segoe UI", "Microsoft YaHei UI"]
    seen, res = set(), []
    for f in out:
        if f and f not in seen:
            seen.add(f)
            res.append(f)
    return res


class LyricOverlay(QWidget):
    request_relyrics = pyqtSignal()
    request_fullscreen = pyqtSignal()
    request_dump = pyqtSignal()
    request_quit = pyqtSignal()

    def __init__(self, cfg):
        super().__init__(None)
        self.cfg = cfg

        # ---- 外观参数 ----
        self.font_family = cfg.get("font_family", DEFAULT_FONT)
        self._fams = font_chain(str(self.font_family),
                                str(cfg.get("cjk_font", DEFAULT_CJK)
                                    or DEFAULT_CJK))
        self.base_pt = float(cfg.get("font_size", 26))
        # 字号随窗口高度按比例缩放（拖动边框改大小时，字也跟着变）
        self._font_ratio = self.base_pt / max(1.0, float(cfg.get("window_height", 300)))
        self.opacity = float(cfg.get("opacity", 0.96))
        self.window_mode = cfg.get("window_mode", "normal")   # normal | floating
        self.always_on_top = bool(cfg.get("always_on_top", False))
        self.click_through = bool(cfg.get("click_through", False))
        self.show_track_info = bool(cfg.get("show_track_info", True))
        self.show_translation = bool(cfg.get("show_translation", True))
        self.use_album_art = bool(cfg.get("bg_album_art", True))
        self.offset = float(cfg.get("lyrics_offset_sec", 0.0))

        # ---- 数据状态 ----
        self.title = ""
        self.artist = ""
        self.status_text = "正在连接音箱…"
        self._lines = []          # [(t, text, trans)]
        self._times = []
        self._plain = []
        self._ends = []           # 每行结束时间（Apple 源才有）
        self._rel_words = []      # 每行逐词相对时间（Apple 逐词源才有）
        self._synced = False
        self._has_trans = False

        self._pos_base = 0.0
        self._pos_ts = time.monotonic()
        self._pos = 0.0
        self._playing = False

        self._cur_index = 0
        self._scroll = 0.0
        self._frac = 0.0
        self._pulse = 0.0
        self._last_index = -1

        self._bg = None
        self._art_bytes = None
        self._drag = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle(APP_NAME)

        self._apply_flags()
        self.resize(int(cfg.get("window_width", 900)), int(cfg.get("window_height", 300)))
        self._restore_position()
        self._recalc_metrics()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)          # ~60fps

    # ------------------------------------------------------------------ #
    # 外观 / 窗口
    # ------------------------------------------------------------------ #
    def _f(self, pt):
        """按家族链造字体（拉丁 = SF Pro，中文回退 = cjk_font）。"""
        f = QFont()
        f.setFamilies(self._fams)
        f.setPointSizeF(pt)
        return f

    def _apply_flags(self):
        if self.window_mode == "floating":
            # 无边框悬浮条：不进任务栏、可置顶、可鼠标穿透
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            if self.click_through:
                flags |= Qt.WindowType.WindowTransparentForInput
        else:
            # 普通窗口：有标题栏、可缩放、进任务栏，和其它程序一样
            flags = Qt.WindowType.Window
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(APP_NAME)

    def _restore_position(self):
        pos = self.cfg.get("window_position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
        else:
            screen = self.screen()
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.bottom() - self.height() - 80,
            )

    def save_position(self):
        self.cfg["window_position"] = [self.x(), self.y()]

    def _recalc_metrics(self):
        f = self._f(self.base_pt)
        fm = QFontMetricsF(f)
        self.line_gap = fm.height() * (2.0 if self._has_trans else 1.55)

    # ------------------------------------------------------------------ #
    # 外部数据入口
    # ------------------------------------------------------------------ #
    def set_status(self, text):
        self.status_text = text
        self.update()

    def set_track(self, info):
        self.title = info.get("title", "") or ""
        self.artist = info.get("artist", "") or ""
        self.status_text = ""
        self._lines, self._times, self._plain = [], [], []
        self._ends = []
        self._rel_words = []
        self._synced = False
        self._has_trans = False
        self._cur_index = 0
        self._scroll = 0.0
        self._frac = 0.0
        self._recalc_metrics()
        self.update()

    def set_lyrics(self, res):
        if not res:
            self._lines, self._times, self._plain = [], [], []
            self._ends = []
            self._rel_words = []
            self._synced = False
            self.status_text = "暂无歌词"
        elif res.get("synced"):
            self._lines = res.get("lines") or []
            self._times = [row[0] for row in self._lines]
            self._ends = list(res.get("ends") or [])
            self._rel_words = timing.relative_words(res.get("words"),
                                                    self._times)
            self._synced = bool(self._lines)
            self._plain = []
            self._has_trans = self.show_translation and any(r[2] for r in self._lines)
            self._cur_index = 0
            self._scroll = 0.0
        else:
            self._plain = res.get("plain") or []
            self._lines, self._times = [], []
            self._ends = []
            self._rel_words = []
            self._synced = False
            self.status_text = ""
        self._recalc_metrics()
        self.update()

    def set_position(self, seconds, playing, precise=False):
        now = time.monotonic()
        sec = float(seconds or 0.0)
        if precise:
            # 边沿时钟实测校准过的位置：直接采信
            self._pos_base = sec
            self._pos_ts = now
            self._playing = bool(playing)
            return
        mid = sec + timing.REL_MID       # 兜底：整秒读数 + 采样相位补偿
        if playing and self._playing:
            cur = self._pos_base + (now - self._pos_ts)
            err = cur - mid              # 我们超前为正
            if abs(err) >= timing.SYNC_SNAP:
                self._pos_base = mid     # seek / 切歌：直接对齐
                self._pos_ts = now
            elif abs(err) >= timing.SYNC_PULL:
                self._pos_base = cur - err * timing.SYNC_RATE  # 分步收敛
                self._pos_ts = now
            # 小误差：不动（迟滞），避免整秒读数抖动引起画面跳变
        else:
            self._pos_base = mid
            self._pos_ts = now
        self._playing = bool(playing)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = max(1.0, float(self.height()))
        new_pt = min(90.0, max(10.0, self._font_ratio * h))
        if abs(new_pt - self.base_pt) > 0.15:
            self.base_pt = new_pt
            self.cfg["font_size"] = round(new_pt, 2)
        self._recalc_metrics()
        if self._art_bytes:
            self.set_album_art_bytes(self._art_bytes)
        self.update()

    def set_album_art_bytes(self, data):
        self._art_bytes = data
        if not data or not self.use_album_art:
            self._bg = None
            self.update()
            return
        img = QImage.fromData(QByteArray(data))
        if img.isNull():
            self._bg = None
            self.update()
            return
        w, h = max(1, self.width()), max(1, self.height())
        small = img.scaled(
            max(8, w // 24), max(8, h // 24),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        big = small.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (big.width() - w) // 2)
        y = max(0, (big.height() - h) // 2)
        self._bg = QPixmap.fromImage(big.copy(x, y, w, h))
        self.update()

    # ------------------------------------------------------------------ #
    # 帧循环
    # ------------------------------------------------------------------ #
    def _tick(self):
        now = time.monotonic()
        self.offset = float(self.cfg.get("lyrics_offset_sec", 0.0))
        self._pos = (
            self._pos_base + (now - self._pos_ts) if self._playing else self._pos_base
        )
        pos_eff = self._pos - self.offset

        if self._synced and self._times:
            idx = bisect_right(self._times, pos_eff) - 1
            self._cur_index = max(0, idx)
            if 0 <= idx < len(self._times) - 1:
                span = self._times[idx + 1] - self._times[idx]
                text = self._lines[idx][1] if idx < len(self._lines) else ""
                end = self._ends[idx] if idx < len(self._ends) else None
                end_rel = (end - self._times[idx]) if end else None
                rel = (self._rel_words[idx]
                       if idx < len(self._rel_words) else None)
                frac = timing.fill_frac(text, pos_eff - self._times[idx],
                                        span, end_rel, rel)
            else:
                frac = 0.0
            self._frac = min(1.0, max(0.0, frac))
        else:
            self._cur_index = 0
            self._frac = 0.0

        if self._cur_index != self._last_index:
            self._last_index = self._cur_index
            self._pulse = 1.0
        self._pulse *= 0.88

        target = float(self._cur_index)
        self._scroll += (target - self._scroll) * 0.16
        if abs(target - self._scroll) < 0.002:
            self._scroll = target

        self.update()

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)
        radius = float(self.cfg.get("corner_radius", 18))

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)

        base = QColor(14, 14, 17, int(240 * self.opacity))
        p.fillRect(rect, base)

        if self._bg is not None:
            p.setOpacity(0.42)
            p.drawPixmap(0, 0, w, h, self._bg)
            p.setOpacity(1.0)
            p.fillRect(rect, QColor(8, 8, 11, 150))

        top_reserved = 0.0
        if self.show_track_info and (self.title or self.artist):
            top_reserved = self.base_pt * 2.0
            f = self._f(self.base_pt * 0.60)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(
                QRectF(24, 10, w - 48, top_reserved - 10),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self._track_line(),
            )

        area = QRectF(16, top_reserved, w - 32, h - top_reserved)
        self._draw_content(p, area)
        self._draw_fade(p, area)
        p.end()

    def _track_line(self):
        if self.title and self.artist:
            return "%s  —  %s" % (self.title, self.artist)
        return self.title or self.artist or ""

    def _draw_content(self, p, area):
        if self._synced and self._lines:
            self._draw_synced(p, area)
        elif self._plain:
            self._draw_plain(p, area)
        else:
            f = self._f(self.base_pt * 0.72)
            p.setFont(f)
            p.setPen(QColor(220, 222, 232, 150))
            flags = (
                Qt.AlignmentFlag.AlignCenter.value
                | Qt.TextFlag.TextWordWrap.value
            )
            p.drawText(area, flags, self.status_text or "暂无歌词")

    def _draw_synced(self, p, area):
        center_y = area.center().y()
        gap = self.line_gap
        count = len(self._lines)

        for i in range(count):
            d = i - self._scroll
            if abs(d) > 4.5:
                continue
            alpha = int(255 * math.exp(-((d / 1.55) ** 2)))
            if alpha < 8:
                continue

            scale = 1.0 + 0.13 * math.exp(-((d / 0.95) ** 2))
            if i == self._cur_index:
                scale += 0.03 * self._pulse

            _t, text, trans = self._lines[i]
            font = self._f(self.base_pt * scale)
            font.setWeight(
                QFont.Weight.DemiBold if i == self._cur_index else QFont.Weight.Normal
            )
            p.setFont(font)
            fm = QFontMetricsF(font)
            y = center_y + d * gap
            max_w = area.width()

            # 长句自适应：先缩字，仍超宽就折成两行
            segs, used_pt = self._fit_lines(font, fm, text, max_w)
            th = fm.height()
            total_h = th * len(segs)

            dim = QColor(170, 172, 186, alpha)
            hot = QColor(255, 255, 255, alpha)
            for k, seg in enumerate(segs):
                fk = self._f(used_pt)
                fk.setWeight(
                    QFont.Weight.DemiBold if i == self._cur_index else QFont.Weight.Normal
                )
                p.setFont(fk)
                fmk = QFontMetricsF(fk)
                sw = fmk.horizontalAdvance(seg)
                yy = y - total_h / 2.0 + k * th
                box = QRectF(area.center().x() - sw / 2.0, yy, sw, th)
                p.setPen(dim)
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, seg)
                if i == self._cur_index and self._frac > 0.0:
                    p.save()
                    p.setClipRect(
                        QRectF(box.left(), box.top(), sw * self._frac, th),
                        Qt.ClipOperation.IntersectClip,
                    )
                    p.setPen(hot)
                    p.drawText(box, Qt.AlignmentFlag.AlignCenter, seg)
                    p.restore()

            if trans and self.show_translation and abs(d) < 1.8:
                f2 = self._f(used_pt * 0.60)
                p.setFont(f2)
                p.setPen(QColor(196, 200, 214, int(alpha * 0.62)))
                p.drawText(
                    QRectF(area.left(), y + total_h / 2.0, area.width(), th),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    trans,
                )

    @staticmethod
    def _fit_lines(font, fm, text, max_w):
        """长句自适应：只缩字、不折行（悬浮条是细长条，折行会跟邻行重叠）。"""
        pt = font.pointSizeF()
        w = fm.horizontalAdvance(text)
        if w <= max_w or w <= 0:
            return [text], pt
        shrink = max(0.45, min(1.0, max_w / w))
        return [text], pt * shrink

    def _draw_plain(self, p, area):
        f = self._f(self.base_pt * 0.62)
        p.setFont(f)
        fm = QFontMetricsF(f)
        lh = fm.height() * 1.35
        total = lh * len(self._plain)
        y = area.center().y() - total / 2.0
        for row in self._plain:
            if y > area.bottom():
                break
            if y > area.top() - lh:
                p.setPen(QColor(205, 208, 220, 190))
                p.drawText(
                    QRectF(area.left(), y, area.width(), lh),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    row,
                )
            y += lh

    def _draw_fade(self, p, area):
        gh = max(36.0, area.height() * 0.26)
        g1 = QLinearGradient(0, area.top(), 0, area.top() + gh)
        g1.setColorAt(0.0, QColor(14, 14, 17, 235))
        g1.setColorAt(1.0, QColor(14, 14, 17, 0))
        p.fillRect(QRectF(area.left(), area.top(), area.width(), gh), g1)

        g2 = QLinearGradient(0, area.bottom() - gh, 0, area.bottom())
        g2.setColorAt(0.0, QColor(14, 14, 17, 0))
        g2.setColorAt(1.0, QColor(14, 14, 17, 235))
        p.fillRect(QRectF(area.left(), area.bottom() - gh, area.width(), gh), g2)

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):
        if self.window_mode != "floating":
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.window_mode != "floating":
            return super().mouseMoveEvent(event)
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.save_position()

    def mouseDoubleClickEvent(self, event):
        # 双击歌词条 → 全屏歌词模式
        self.request_fullscreen.emit()


    def contextMenuEvent(self, event):
        m = QMenu(self)
        m.addAction("重新搜索歌词", self.request_relyrics.emit)
        m.addAction("全屏歌词模式（黑胶）　← 双击歌词条也行", self.request_fullscreen.emit)
        m.addAction("导出当前曲目信息（排查用）", self.request_dump.emit)
        m.addSeparator()
        m.addAction("歌词延后 0.5s", lambda: self._nudge_offset(+0.5))
        m.addAction("歌词延后 0.1s", lambda: self._nudge_offset(+0.1))
        m.addAction("歌词提前 0.1s", lambda: self._nudge_offset(-0.1))
        m.addAction("歌词提前 0.5s", lambda: self._nudge_offset(-0.5))
        m.addAction("偏移归零", lambda: self._set_offset(0.0))
        m.addSeparator()
        m.addAction("字号 +", lambda: self._nudge_font(+2))
        m.addAction("字号 -", lambda: self._nudge_font(-2))
        m.addAction("黑胶转速 慢一点", lambda: self._nudge_vinyl(+3.0))
        m.addAction("黑胶转速 快一点", lambda: self._nudge_vinyl(-3.0))
        m.addAction("透明度 +", lambda: self._nudge_opacity(+0.05))
        m.addAction("透明度 -", lambda: self._nudge_opacity(-0.05))
        m.addSeparator()
        mode = m.addAction("悬浮模式（无边框·置顶·可锁定）")
        mode.setCheckable(True)
        mode.setChecked(self.window_mode == "floating")
        mode.triggered.connect(self._toggle_mode)
        m.addAction("重置窗口大小", self._reset_size)
        top = m.addAction("窗口置顶")
        top.setCheckable(True)
        top.setChecked(self.always_on_top)
        top.triggered.connect(self._toggle_top)
        thru = m.addAction("鼠标穿透（锁定）")
        thru.setCheckable(True)
        thru.setChecked(self.click_through)
        thru.triggered.connect(self._toggle_click_through)
        m.addSeparator()
        m.addAction("隐藏窗口", self.hide)
        m.addAction("退出", self.request_quit.emit)
        m.exec(event.globalPos())

    # --- 菜单动作 ------------------------------------------------------- #
    def _nudge_offset(self, delta):
        self._set_offset(self.offset + delta)

    def _nudge_vinyl(self, delta):
        cur = float(self.cfg.get("vinyl_turn_seconds", 12.0))
        self.cfg["vinyl_turn_seconds"] = max(4.0, min(40.0, cur + delta))

    def _set_offset(self, value):
        self.offset = value
        self.cfg["lyrics_offset_sec"] = value

    def _nudge_font(self, delta):
        self.base_pt = min(90.0, max(10.0, self.base_pt + delta))
        self._font_ratio = self.base_pt / max(1.0, float(self.height()))
        self.cfg["font_size"] = self.base_pt
        self._recalc_metrics()
        self.update()

    def _nudge_opacity(self, delta):
        self.opacity = min(1.0, max(0.25, self.opacity + delta))
        self.cfg["opacity"] = self.opacity
        self.update()

    def _toggle_mode(self, checked):
        self.window_mode = "floating" if checked else "normal"
        self.cfg["window_mode"] = self.window_mode
        if self.window_mode == "floating":
            self.always_on_top = True
        else:
            self.always_on_top = False
            self.click_through = False
        self.cfg["always_on_top"] = self.always_on_top
        self.cfg["click_through"] = self.click_through
        self._reapply_window_flags()

    def _reset_size(self):
        self.resize(900, 300)
        self._font_ratio = 26.0 / 300.0

    def _toggle_top(self, checked):
        self.always_on_top = bool(checked)
        self.cfg["always_on_top"] = self.always_on_top
        self._reapply_window_flags()

    def _toggle_click_through(self, checked):
        self.click_through = bool(checked)
        self.cfg["click_through"] = self.click_through
        self._reapply_window_flags()

    def _reapply_window_flags(self):
        pos = QPoint(self.x(), self.y())
        visible = self.isVisible()
        self._apply_flags()
        if visible:
            self.show()
        self.move(pos)
