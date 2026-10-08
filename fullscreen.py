# -*- coding: utf-8 -*-
"""全屏歌词模式：左侧旋转黑胶 + 右侧大字同步歌词 + 底部播放控制。

- 行距恒定（按"块与块之间的空隙"算，折行也不会忽紧忽松）
- 远处歌词渐进模糊（缓存位图，60fps 不掉帧）
- 滚动带阻尼延迟跟随；大跳（seek）直接瞬移，不做长距离滚动
- 底部控制条：上一曲 / 播放暂停 / 下一曲 / 音量 / 可拖动进度条
- 快捷键：空格 播放暂停；←→ 快退快进；↑↓ 音量；Ctrl+←→ 上下一曲；Esc 退出
"""

import math
import sys
import time
from bisect import bisect_right
from collections import OrderedDict

import skins
import timing
import tonearm
import vinyl

from speakers.http import APP_NAME

try:
    import PIL  # noqa: F401
    _HAS_PIL = True
except ImportError:                     # 没装 Pillow 就退回降采样近似
    _HAS_PIL = False

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontInfo,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextLayout,
)
from PyQt6.QtWidgets import QMenu, QWidget

DEFAULT_FONT = "SF Pro Display"   # 拉丁（随包，最重到 Black）
DEFAULT_CJK = "Noto Sans SC"       # 中文回退（思源黑体 / Noto CJK，有 Black）
VINYL_TURN_SECONDS = 12.0
# 黑胶唱片造型（参考真唱片比例：标签 ≈ 0.33R，沟槽从 ≈ 0.4R 到近盘边）
VINYL_COVER_R = 0.35              # 封面（中心标签）半径 / 唱片半径
VINYL_ARM_PIVOT = (1.05, -1.05)   # 唱臂枢轴（相对盘心，×R；盘外右上）
VINYL_ARM_HIT = (0.75, -0.30)     # 唱针落点（相对盘心，×R；外圈沟槽区）
VINYL_ARM_LIFT = 2.6              # 暂停时唱臂抬起（度，向外摆一点）
VINYL_FADE_SEC = 0.45             # 切歌时“换盘”的交叉淡入时长
BG_ALPHA = 0.78          # 模糊封面背景的不透明度（保持低亮度）
BG_ALPHA_MIN = 0.32      # 亮封面背景的最低不透明度（自适应下限）
BG_LUM_TARGET = 0.20     # 背景有效亮度目标：alpha = target / 平均亮度
BG_FADE_SEC = 0.5        # 换歌时背景交叉过渡时长（AMLL 封面过渡同款 0.5s）
BG_RES = (320, 180)      # 背景底图尺寸（再大纯浪费，靠模糊出色彩）
BG_SIGMA = 12.0          # 背景高斯的 σ（BG_RES 尺度下）
BG_SAT = 1.15            # 背景饱和度增强（暗封面不发灰）
GAP_ROWS = 1.15           # 行与行之间的"空隙"（以行高为单位，恒定不变）
SEEK_STEP = 5.0           # 方向键快进快退秒数
VOL_STEP = 2              # 音量步长
TEXT_X = 0.52             # 歌词区左边（占窗口宽比例）
TEXT_W = 0.46             # 歌词区宽度（右缘只留 2% 边距）
TEXT_TOP = 0.105          # 歌词区顶部（占窗口高比例；给标题留出上边距）
TEXT_H = 0.80             # 歌词区高度（占窗口高比例）

# ---- AMLL（仿 Apple Music）的滚动 / 模糊参数，取自 AMLL 源码 ---- #
SPRING_MASS = 0.9                    # 纵向弹簧质量
SPRING_SLOW = (90.0, 15.0)           # seek / 间奏：慢速、略带回弹
SPRING_END = (140.0, 22.0)           # 曲末
SPRING_K_MIN, SPRING_K_MAX = 170.0, 220.0   # 正常播放（按行间隔映射）
SPRING_DAMP = 2.2                    # damping = 2.2 * sqrt(k)
ROW_DELAY = 0.05                     # 阶梯延迟：每行 +50ms
ROW_DELAY_DECAY = 1.0 / 1.05         # 越过当前行后逐行衰减
MAX_FRAME_DT = 0.1                   # 单帧时间上限（防挂起后过冲）
# 歌词焦点的纵向位置（窗口高度比例）：略偏上，标题下方不空
FOCUS_RATIO = 0.43

# 模糊参数（仿 Apple Music 的景深层次）：AMLL 原值 σ = min(5, 1+距焦点行数)。
# 下标 0..4 对应距离 d = 1,2,3,4,5+ 行的目标高斯 σ（逻辑 px）→ 2/3/4/5/5。
# 已唱过的行等效距离 +1，所以紧邻上方那行的 σ = BLUR_DIST[1]（比下一行更虚）。
# 关键：下一行就给到 σ2，近处不再是“实心灰字”，而是柔和的景深虚影。
BLUR_DIST = (2.0, 3.0, 4.0, 5.0, 5.0)
BLUR_TAU = 0.13                      # 模糊变化的平滑时间常数（≈AMLL 的 0.4s 过渡）
BLUR_TEX = 1.1                       # （Pillow 缺失时的降采样近似）降采样倍数系数
SCALE_ACTIVE = 1.0                   # 活跃行缩放
SCALE_INACTIVE = 0.97                # 非活跃行缩放
SCALE_SPRING = (2.0, 25.0, 100.0)    # (mass, damping, stiffness)
ACTIVE_DIM_ALPHA = 108               # 当前行未唱部分亮度
ACTIVE_HOT_ALPHA = 240               # 当前行已唱部分亮度
WORD_FADE_W = 0.5                    # 填充前沿的软边宽度（× 行高；AMLL wordFadeWidth 默认 0.5）
FLOAT_UP_EM = 0.05                   # 逐词上浮高度（× em；AMLL float 动画：0.05em）
FLOAT_MIN_SEC = 1.0                  # 上浮动画最短时长（AMLL：max(1s, 词时长)）
INACTIVE_OPACITY = 0.20              # 远景行不透明度（对齐 AMLL 的 --dark-mask-alpha：0.2）
INACTIVE_OPACITY_NEAR = 0.36         # 相邻行不透明度（AMLL 恒定 0.2，这里给邻近行留一点可读性）
TRANS_ALPHA = 92                     # 位图（非当前行）内翻译文字 alpha
TRANS_ALPHA = 92                     # （位图路径保留值）翻译文字 alpha
# 翻译字号 / 亮度：对照 YesPlayMusic 的 .translation（font-size 0.925em、
# 活跃翻译 opacity 0.65，靠亮度而不是缩得很小来“退到第二层”）
TRANS_SCALE = 0.60                   # 翻译字号（× 原文字号）
TRANS_ACTIVE_ALPHA = 166             # 当前行翻译亮度（≈ 0.65 不透明度）
# 翻译行不再用矩形框定位（矩形框会按每个字自己的字体度量摆位置：中英混排时
# 拉丁字体 ascent 比中文小，英文会“偏上”，整行绘制时又统一落到共用 baseline ——
# 动画结束瞬间会跳一下）。现在统一用 baseline 绘制，见 _trans_ascent()。
# 翻译“四周汇聚”的节奏：**出发时刻挂在主句填充进度上、飞行本身走播放时间轴**。
# 为什么要分开：主句的填充来自逐词时间轴，词与词的间隙里填充值会冻结 ——
# 如果飞行也挂在填充上，字就会“飞一半停住、下一词开始时再跳一下”。
# 所以：填充越过每个字的阈值 = 该字起飞（与演唱同步），起飞后用固定时长
# 平滑飞完（与主句的逐词上浮同一套时间轴，暂停冻结、seek 重来）。
TRANS_FILL_START = 0.05              # 填充到这儿才开始入场（略等主句起唱）
TRANS_FILL_LAST = 0.72               # 最后一个字的出发阈值（填充到这儿全部已起飞）
TRANS_FILL_DONE = 0.78               # 收尾线：越过它、且最后一个字也飞完，就交回整行绘制
TRANS_MOTION_SEC = 0.55              # 单个字飞入的时长（秒，播放时间轴）
TRANS_CATCHUP_MIN = 0.35            # 中途接手（seek/刚启动）时，最后一个字至少已飞到这个比例
TRANS_IN_SOFT = 1.6                  # 入场时幽灵描边半径（逻辑 px，营造“由虚到实”）

# ---- 间奏点（仿 Apple Music）：两句之间长间奏时的呼吸圆点 ---- #
# 参数取自 AMLL（applemusic-like-lyrics）的 interlude-dots 移植
INTERLUDE_GAP = 7.0                  # 空隙达到该值才判定为间奏（秒）
DOTS_DELAY_MS = 500.0                # 入场延迟（给上一行上滑留缓冲）
DOTS_ENTER_MS = 180.0                # 容器渐入时长
DOTS_STAGGER_MS = 80.0               # 三颗圆点错峰入场
DOTS_FADE_MS = 750.0                 # 单颗圆点入场淡入时长
DOTS_EXIT_PHASE1_MS = 750.0          # 退场：放大蓄力
DOTS_EXIT_PHASE2_MS = 250.0          # 退场：缩小
DOTS_EXIT_MS = DOTS_EXIT_PHASE1_MS + DOTS_EXIT_PHASE2_MS
DOTS_EXIT_FADE_MS = 250.0            # 退场最后一段渐隐
DOTS_TRAIL_MS = 750.0                # 退场时第三颗圆点补亮
DOTS_MIN_BODY_MS = 910.0             # 主体不足此值则不显示（三点都进不来）
DOTS_HOLD_BODY_MS = 3000.0           # 主体过短时降级为恒亮（seek 进间奏时常见）
DOTS_PERIOD_MS = 4000.0              # 呼吸基准周期
DOTS_INACTIVE = 0.2                  # 单点未点亮透明度
DOTS_ACTIVE = 0.9                    # 单点点亮透明度
DOTS_MAX_SCALE = 1.25                # 呼吸最大缩放
DOTS_MIN_SCALE = 0.4                 # 退场收缩最小缩放


def _make_bezier(x1, y1, x2, y2):
    """三次贝塞尔缓动求值器（牛顿法；直接采用 AMLL/CSS 的曲线参数）。"""
    def bez(t, p1, p2):
        u = 1.0 - t
        return 3.0 * u * u * t * p1 + 3.0 * u * t * t * p2 + t * t * t

    def curve(x):
        x = min(1.0, max(0.0, x))
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        t = x
        for _ in range(7):
            err = bez(t, x1, x2) - x
            d = (3.0 * (1.0 - t) ** 2 * x1
                 + 6.0 * (1.0 - t) * t * (x2 - x1)
                 + 3.0 * t * t * (1.0 - x2))
            if abs(d) < 1e-5:
                break
            t = min(1.0, max(0.0, t - err / d))
        return bez(t, y1, y2)

    return curve


_E_LIGHT = _make_bezier(0.56, 0.01, 0.45, 1.0)       # 单点依次点亮
_E_ENTER = _make_bezier(0.59, 0.02, 0.07, 1.0)       # 容器入场
_E_FLOAT = _make_bezier(0.0, 0.0, 0.58, 1.0)         # 逐词上浮（CSS ease-out）
_E_CONVERGE = _make_bezier(0.215, 0.61, 0.355, 1.0)  # 翻译汇聚（easeOutCubic：平滑滑入）
_E_EXIT1 = _make_bezier(0.14, 0.06, 0.25, 1.0)       # 退场：放大蓄力
_E_EXIT2 = _make_bezier(0.29, 0.03, 1.0, 0.38)       # 退场：缩小
_E_EXIT_FADE = _make_bezier(0.43, 0.08, 0.83, 0.31)  # 退场：渐隐


def _gaussian_qimage(img, sigma, sat=1.0):
    """QImage -> Pillow 真高斯 -> QImage（真毛玻璃质感）；

    sat > 1 时顺带提一点饱和度（暗封面做背景时不容易发灰）。

    必须在**预乘 alpha**（RGBA8888_Premultiplied）下模糊：直通模糊会把
    透明区的 RGB=0 也混进来，模糊后的字实际合成亮度变成 c² 而不是 c，
    边缘就出现一圈“描边”。预乘空间里 4 个通道各自高斯 = 数学上正确的模糊。
    """
    from PIL import Image, ImageEnhance, ImageFilter
    img = img.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    try:
        ptr.setsize(img.sizeInBytes())
    except AttributeError:
        pass
    pil = Image.frombuffer("RGBA", (w, h), bytes(ptr), "raw", "RGBA",
                           img.bytesPerLine(), 1)
    if sat != 1.0:
        pil = ImageEnhance.Color(pil).enhance(sat)
    out = pil.filter(ImageFilter.GaussianBlur(sigma))
    data = out.tobytes()
    qimg = QImage(data, w, h, w * 4,
                  QImage.Format.Format_RGBA8888_Premultiplied)
    return qimg.copy()                  # 拷贝一份，不依赖临时 bytes


class _Spring1D:
    """AMLL（pushkine 求解器）的一维弹簧移植：解析解 + 目标延迟队列。

    - 目标变化时用当前位置和速度重建解析解 → 与帧率无关；
    - 静止（solver=None）时 update 直接跳过，不花开销。
    """

    __slots__ = ("m", "k", "c", "pos", "target", "t", "solver", "_queue")

    def __init__(self, pos=0.0, mass=SPRING_MASS):
        self.m = float(mass)
        self.k, self.c = SPRING_SLOW
        self.pos = self.target = float(pos)
        self.t = 0.0
        self.solver = None          # None = 静止
        self._queue = None          # (target, 剩余秒数)

    def _velocity(self):
        if self.solver is None:
            return 0.0
        h = 1e-3
        t = self.t
        return (self.solver(t + h) - self.solver(t - h)) / (2.0 * h)

    def _build(self, frm, v, to):
        delta = to - frm
        if self.c / (2.0 * math.sqrt(self.k * self.m)) >= 1.0:
            # 过阻尼 / 临界：x(t) = to - (delta + t*L) * e^(w*t)
            w = -math.sqrt(self.k / self.m)
            left = -w * delta - v
            return lambda t: to - (delta + t * left) * math.exp(w * t)
        # 欠阻尼
        wd = math.sqrt(max(1e-9, 4.0 * self.m * self.k - self.c ** 2))
        a = wd / (2.0 * self.m)
        b = -self.c / (2.0 * self.m)
        left = (self.c * delta - 2.0 * self.m * v) / wd
        return (lambda t: to - (math.cos(a * t) * delta
                                + math.sin(a * t) * left) * math.exp(b * t))

    def _retarget(self, to):
        v = self._velocity()
        self.target = to
        self.t = 0.0
        self.solver = self._build(self.pos, v, to)

    def set_params(self, k, c):
        self.k, self.c = float(k), float(c)

    def set_position(self, p):
        self.pos = self.target = float(p)
        self.t = 0.0
        self.solver = None
        self._queue = None

    def set_target(self, to, delay=0.0):
        to = float(to)
        if delay > 0.0:
            self._queue = (to, delay)
            return
        if abs(self.target - to) < 0.001:
            return                      # 目标没变：让它继续跑
        self._queue = None
        self._retarget(to)

    def update(self, dt):
        if self._queue is not None:
            to, remain = self._queue
            remain -= dt
            if remain <= 0.0:
                self._queue = None
                self._retarget(to)
            else:
                self._queue = (to, remain)
        if self.solver is None:
            return
        self.t += dt
        self.pos = self.solver(self.t)
        if abs(self.target - self.pos) < 0.02 and abs(self._velocity()) < 8.0:
            self.set_position(self.target)      # 到位吸附


class FullscreenView(QWidget):
    closed = pyqtSignal()
    player_command = pyqtSignal(str, float)     # (动作, 数值)

    def __init__(self, cfg):
        super().__init__(None)
        self.cfg = cfg
        self.font_family = cfg.get("font_family", DEFAULT_FONT)
        self.cjk_font = str(cfg.get("cjk_font", DEFAULT_CJK)
                            or DEFAULT_CJK)
        self.show_translation = bool(cfg.get("show_translation", True))

        # ---- 状态机 ----
        self.title = ""
        self.artist = ""
        self.status_text = "暂无歌词"
        self._lines = []
        self._times = []
        self._plain = []
        self._ends = []             # 每行结束时间（Apple 源才有）
        self._rel_words = []        # 每行逐词相对时间（Apple 逐词源才有）
        self._synced = False
        self._has_trans = False

        self._pos_base = 0.0
        self._pos_ts = time.monotonic()
        self._pos = 0.0
        self._playing = False
        self.duration = 0.0
        self.volume = -1

        self._cur_index = 0
        self._frac = 0.0
        self._last_index = -1
        self._last_pos_eff = 0.0

        # AMLL 风格滚动：每行一根位置弹簧 + 一根缩放弹簧 + 模糊位图缓存
        self._springs = []
        self._scale_springs = []
        self._blur_cache = OrderedDict()
        self._fit_cache = {}         # 每行的“缩到放得下”字号倍率
        self._trans_cache = {}       # 翻译折行/缩放结果
        self._row_heights = []
        self._blur_cur = []         # 每行当前模糊 σ（平滑过渡，仿 AMLL）
        self._alpha_cur = []        # 每行当前不透明度（平滑过渡，仿 AMLL 的 opacity transition）
        self._dpr = 1.0             # 屏幕缩放（位图按物理像素渲染，高 DPI 不糊）

        # 间奏点（仿 Apple Music）：长间奏时的呼吸圆点
        self._interludes = []       # [(起点, 终点, 上一行索引)]
        self._active_iv = None      # 当前间奏的演出计划
        self._iv_focus = False      # 滚动焦点是否在间奏点上
        self._dots_snap = None      # 本帧三点动画快照 (ops, scale, opacity)
        self._dots_spring = _Spring1D()

        # ---- 布局 ----
        self._line_y = []
        self._segs_cache = []
        self._runs_cache = []       # 每行按逐词时间切好的运行段（上浮用）
        self._elapsed = 0.0         # 当前行行内已过时间（逐词上浮用）
        self._lyrics_ver = 0        # 歌词内容的版本号（换歌/换词时 +1）
        self._layout_ver = -1       # 布局是按哪个版本算的（只比行数会漏：
                                    # 两首歌行数相同但内容不同）
        self._row_h = 0.0
        self._base_pt = 32.0
        self._spacing = 40.0
        self._layout_w = -1.0
        self._trans_h = 0.0         # 翻译单行的行高（折行计入块高用）
        self._n_trans = []          # 每行翻译实际折了几行（1..2）
        self._ink_pad = (4.0, 4.0)  # 裁剪框左右放宽量（首/末字母墨迹外挂）
        self._trans_state = {}      # 翻译汇聚动画的运行时状态（起飞时刻、缓存等）

        self._bg = None
        self._bg_alpha = 0.0
        self._bg_prev = None
        self._bg_prev_alpha = 0.0
        self._bg_ts = 0.0
        self._art = None
        self._angle = 0.0
        self._plate_pm = None       # 盘体（底盘/花纹/表层）预渲染位图
        self._plate_key = None
        self._plate_prev = None     # 上一张盘面 / 封面（切歌时交叉过渡用）
        self._art_prev = None
        self._vinyl_fade_ts = 0.0
        self._vinyl_mat = vinyl.pick(cfg)        # 彩胶：全局选择（默认经典黑胶）
        self._vinyl_auto = True     # 本首还没定彩胶 → 封面到了按主色自动配
        self._shadow_pm = None      # 封面色彩的柔影（YesPlayMusic 的 .shadow 做法）
        self._shadow_key = None
        self._arm_off = 0.0         # 唱臂抬起角（暂停时向外摆）
        self.turn_seconds = float(cfg.get("vinyl_turn_seconds", VINYL_TURN_SECONDS))
        self._last_frame = time.monotonic()
        self._shown_at = 0.0
        self._toast_text = ""          # 临时提示（歌词校准等）
        self._toast_until = 0.0

        # ---- 交互 ----
        self._buttons = []          # [(QRectF, action)]
        self._progress = None       # QRectF 进度条区域
        self._dragging = False

        # 控制条自动收放
        self._bar_t = 1.0           # 当前露出程度 0~1
        self._bar_target = 1.0
        self._last_mouse = time.monotonic()
        self.setMouseTracking(True)

        self.setWindowTitle("%s · 黑胶播放器" % APP_NAME)
        self.setStyleSheet("background: #0c0c0f;")
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(12, 12, 15))
        self.setPalette(pal)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def showEvent(self, event):
        super().showEvent(event)
        self._last_frame = time.monotonic()
        if self.isFullScreen():
            self._kill_win_edges()      # 窗口被 Qt 重建过时补一次
        self._shown_at = time.monotonic()
        self._bar_t = 1.0
        self._bar_target = 1.0
        self._last_mouse = time.monotonic() + 1.5   # 刚进来先露一会儿
        self._timer.start(16)
        self.setFocus()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def closeEvent(self, event):
        super().closeEvent(event)
        self.closed.emit()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Escape:
            # 全屏时先退回窗口，窗口状态下才关闭
            if self.isFullScreen():
                self.toggle_fullscreen()
            else:
                self.close()
        elif key in (Qt.Key.Key_F11, Qt.Key.Key_Return):
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Space:
            self.player_command.emit("toggle", 0.0)
        elif key == Qt.Key.Key_Left:
            if ctrl:
                self.player_command.emit("prev", 0.0)
            else:
                self.player_command.emit("seek_rel", -SEEK_STEP)
        elif key == Qt.Key.Key_Right:
            if ctrl:
                self.player_command.emit("next", 0.0)
            else:
                self.player_command.emit("seek_rel", SEEK_STEP)
        elif key == Qt.Key.Key_Up:
            self.player_command.emit("volume", float(VOL_STEP))
        elif key == Qt.Key.Key_Down:
            self.player_command.emit("volume", float(-VOL_STEP))
        elif key == Qt.Key.Key_BracketLeft:      # [ ：歌词提前 0.05s
            self._nudge_offset(-0.05)
        elif key == Qt.Key.Key_BracketRight:     # ] ：歌词延后 0.05s
            self._nudge_offset(+0.05)
        elif key == Qt.Key.Key_M:                # M ：换一种彩胶材质
            self.cycle_material()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    # 数据入口
    # ------------------------------------------------------------------ #
    def cycle_material(self):
        """换一种彩胶：只记进这首歌的记忆（`M` 键 / 托盘菜单）。

        不再改全局配置 —— 全局保持 `auto` 时，没挑过的歌继续按封面主色自动配。
        """
        self._vinyl_swap()
        self._vinyl_mat = vinyl.next_of(self._vinyl_mat)
        self._plate_key = None
        self._vinyl_auto = False            # 手动挑了，本首不再按封面自动配
        skins.remember(self.cfg, self._skin_key(),
                       vinyl=self._vinyl_mat["id"])
        self._toast_text = "唱片材质：%s" % self._vinyl_mat["name"]
        self._toast_until = time.monotonic() + 1.4
        self.update()

    def _skin_key(self):
        return skins.track_key(self.title, self.artist)

    def _vinyl_swap(self):
        """把当前盘面 / 封面存成“上一张”，用于切歌时的交叉过渡（唱臂也会抬一下）。"""
        self._plate_prev = self._plate_pm
        self._art_prev = self._art
        self._vinyl_fade_ts = time.monotonic()
        self._arm_off = max(self._arm_off, VINYL_ARM_LIFT)

    def _vinyl_fade(self):
        """换盘进度：0 = 全是旧盘，1 = 全是新盘（过渡完就把旧盘丢掉）。"""
        if self._plate_prev is None:
            return 1.0
        k = (time.monotonic() - self._vinyl_fade_ts) / VINYL_FADE_SEC
        if k >= 1.0:
            self._plate_prev = None
            self._art_prev = None
            return 1.0
        return max(0.0, k)

    def set_track(self, info):
        self._vinyl_swap()
        self.title = info.get("title", "") or ""
        self.artist = info.get("artist", "") or ""
        # 彩胶：这首歌手动换过就直接用；没换过则等封面到了按主色配 ——
        # 在配好之前先留着上一张的颜色（切歌时不会中间闪一下黑胶）
        memo = skins.recall(self.cfg, self._skin_key())
        mat = vinyl.by_id(memo.get("vinyl"))
        if mat is not None:
            if mat["id"] != self._vinyl_mat["id"]:
                self._vinyl_mat = mat
                self._plate_key = None          # 换材质 → 盘体重画
            self._vinyl_auto = False
        else:
            self._vinyl_auto = True
        self.duration = float(info.get("duration") or 0.0)
        self.status_text = ""           # 搜索期间留白，不再闪“正在搜索歌词…”
        self._lyrics_ver += 1           # 新歌：布局缓存作废
        self._lines, self._times, self._plain = [], [], []
        self._ends = []
        self._rel_words = []
        self._synced = False
        self._interludes = []
        self._active_iv = None
        self._iv_focus = False
        self._dots_snap = None
        self._blur_cur = []
        self._alpha_cur = []
        self._cur_index = 0
        self._last_index = -1
        self._springs = []
        self._scale_springs = []
        self._blur_cache.clear()
        self._trans_state.clear()
        self._layout_w = -1.0
        self.update()

    def set_status(self, text):
        """没歌词时的提示文字（“纯音乐 · 无需歌词”之类）。"""
        self.status_text = text
        self.update()

    def set_lyrics(self, res):
        if not res:
            self._lines, self._times, self._plain = [], [], []
            self._ends = []
            self._rel_words = []
            self._synced = False
            self._interludes = []
            self._active_iv = None
            self._iv_focus = False
            self._dots_snap = None
            self.status_text = "暂无歌词"
        elif res.get("synced"):
            self._lines = res.get("lines") or []
            self._times = [r[0] for r in self._lines]
            self._ends = list(res.get("ends") or [])
            self._rel_words = timing.relative_words(res.get("words"),
                                                    self._times)
            self._synced = bool(self._lines)
            self._interludes = self._calc_interludes()
            self._active_iv = None
            self._iv_focus = False
            self._dots_snap = None
            self._plain = []
            self._has_trans = self.show_translation and any(r[2] for r in self._lines)
            self._cur_index = 0
        else:
            self._plain = res.get("plain") or []
            self._lines, self._times = [], []
            self._ends = []
            self._rel_words = []
            self._synced = False
            self._interludes = []
            self._active_iv = None
            self._iv_focus = False
            self._dots_snap = None
            self.status_text = ""
        self._last_index = -1
        self._springs = []
        self._scale_springs = []
        self._blur_cur = []
        self._alpha_cur = []
        self._blur_cache.clear()
        self._trans_state.clear()
        self._layout_w = -1.0
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

    def set_volume(self, value):
        self.volume = int(value)

    def set_album_art_bytes(self, data):
        self._vinyl_swap()
        if not data:
            self._art = None
            self._bg_push(None)
            self.update()
            return
        img = QImage.fromData(data)
        if img.isNull():
            self._art = None
            self._bg_push(None)
            self.update()
            return
        self._art = QPixmap.fromImage(
            img.scaled(640, 640, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation).copy(0, 0, 640, 640)
        )
        self._bg_push(*self._make_backdrop(img))
        self._apply_cover_tone(img)          # 没挑过的歌：按封面主色配一张彩胶
        self.update()

    def _apply_cover_tone(self, img):
        """按专辑封面主色自动配彩胶；色调定色系、歌名定色系里具体那一款。

        只在“本首还没决定”时生效：手动换过的歌（song_skins 有记忆）不动。
        不写记忆 —— 同一首歌每次配出来都一样（确定性），不需要存。
        """
        if not self._vinyl_auto:
            return
        if not (self.title or self.artist):
            return                           # 曲目信息还没到，等它到了再配
        self._vinyl_auto = False             # 无论换不换色，本首只决定一次
        mat = vinyl.for_cover_color(vinyl.cover_rgb(img), self._skin_key())
        if mat["id"] != self._vinyl_mat["id"]:
            self._vinyl_swap()
            self._vinyl_mat = mat
            self._plate_key = None           # 换材质 → 盘体重画
        self.update()

    def _bg_push(self, bg, alpha=0.0):
        """切换背景（0.5s 线性交叉淡入，和 AMLL 的封面过渡一致）。"""
        self._bg_prev = self._bg
        self._bg_prev_alpha = self._bg_alpha
        self._bg = bg
        self._bg_alpha = float(alpha)
        self._bg_ts = time.monotonic()

    @staticmethod
    def _make_backdrop(img):
        """把封面做成“彩色柔光底”，返回 (QPixmap, 不透明度)。

        缩到中等尺寸 + 大半径高斯（AMLL 方案）；不透明度按模糊后的
        平均亮度自适应：亮封面自动压低，保证整体始终是低亮度柔光。
        """
        tw, th = BG_RES
        src = img.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        x = max(0, (src.width() - tw) // 2)
        y = max(0, (src.height() - th) // 2)
        src = src.copy(x, y, tw, th)
        if _HAS_PIL:
            src = _gaussian_qimage(src, BG_SIGMA, sat=BG_SAT)
        else:                    # 无 Pillow：二次降采样近似大模糊
            small = src.scaled(max(1, tw // 6), max(1, th // 6),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            src = small.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        avg = src.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation
                         ).pixelColor(0, 0)
        lum = (0.2126 * avg.red() + 0.7152 * avg.green()
               + 0.0722 * avg.blue()) / 255.0
        alpha = min(BG_ALPHA, BG_LUM_TARGET / max(lum, 0.05))
        return QPixmap.fromImage(src), max(BG_ALPHA_MIN, alpha)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_w = -1.0
        if not self.isFullScreen():
            self.cfg["player_size"] = [self.width(), self.height()]
        self.update()

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self.isFullScreen() and self.isVisible():
            self.cfg["player_pos"] = [self.x(), self.y()]

    # ------------------------------------------------------------------ #
    # 帧循环
    # ------------------------------------------------------------------ #
    def _tick(self):
        now = time.monotonic()
        dt = min(MAX_FRAME_DT, now - self._last_frame)
        self._last_frame = now

        self.offset = float(self.cfg.get("lyrics_offset_sec", 0.0))
        self._pos = (self._pos_base + (now - self._pos_ts)
                     if self._playing else self._pos_base)
        pos_eff = self._pos - self.offset

        if self._synced and self._times:
            idx = bisect_right(self._times, pos_eff) - 1
            self._cur_index = max(0, idx)
            if 0 <= idx < len(self._times):
                # 最后一行的 span 用行尾/估算兜底（没有下一行时间戳可用）
                if idx < len(self._times) - 1:
                    span = self._times[idx + 1] - self._times[idx]
                else:
                    span = 0.0
                text = self._lines[idx][1] if idx < len(self._lines) else ""
                end = self._ends[idx] if idx < len(self._ends) else None
                end_rel = (end - self._times[idx]) if end else None
                if span <= 0.2:
                    span = (end_rel if end_rel and end_rel > 0.2
                            else max(0.2, timing.est_duration(text) * 1.25))
                rel = (self._rel_words[idx]
                       if idx < len(self._rel_words) else None)
                elapsed = pos_eff - self._times[idx]
                frac = timing.fill_frac(text, elapsed,
                                        span, end_rel, rel)
                self._elapsed = elapsed
            else:
                frac = 0.0
                self._elapsed = 0.0
            self._frac = min(1.0, max(0.0, frac))
        else:
            self._cur_index = 0
            self._frac = 0.0
            self._elapsed = 0.0

        # seek 检测：播放位置瞬间大跳（拖进度条 / 点歌词）
        jumped = abs(pos_eff - self._last_pos_eff) > 1.5
        self._last_pos_eff = pos_eff

        self.turn_seconds = float(self.cfg.get("vinyl_turn_seconds",
                                               VINYL_TURN_SECONDS))
        if self._playing and self.turn_seconds > 0.5:
            self._angle = (self._angle + (360.0 / self.turn_seconds) * dt) % 360.0
        arm_target = 0.0 if self._playing else VINYL_ARM_LIFT
        self._arm_off += (arm_target - self._arm_off) * min(1.0, dt * 5.0)

        self._ensure_layout()
        prev_focus = self._iv_focus
        self._sync_interlude(pos_eff, jumped)
        if (self._cur_index != self._last_index
                or self._iv_focus != prev_focus):
            self._last_index = self._cur_index
            self._retarget_rows(seek=jumped)
        self._update_rows(dt)
        self._dots_snap = (self._eval_dots(pos_eff)
                           if self._iv_focus else None)

        # 控制条：拖进度时强制露出；鼠标静一会自动沉下去
        if self._dragging:
            self._bar_target = 1.0
        elif time.monotonic() - self._last_mouse > 2.5:
            self._bar_target = 0.0
        self._bar_t += (self._bar_target - self._bar_t) * 0.22
        if self._bar_t < 0.002:
            self._bar_t = 0.0
        elif self._bar_t > 0.998:
            self._bar_t = 1.0

        self.update()

    # ------------------------------------------------------------------ #
    # AMLL 风格滚动跟随：每行一根弹簧 + 阶梯延迟
    # ------------------------------------------------------------------ #
    def _rebuild_rows(self, n):
        """行数/布局变化后同步弹簧数量，并直接吸附到位（不做动画）。"""
        if len(self._springs) > n:
            del self._springs[n:]
        if len(self._scale_springs) > n:
            del self._scale_springs[n:]
        sm, sc, sk = SCALE_SPRING
        while len(self._springs) < n:
            self._springs.append(_Spring1D())
        while len(self._scale_springs) < n:
            s = _Spring1D(SCALE_INACTIVE, mass=sm)
            s.set_params(sk, sc)
            self._scale_springs.append(s)
        if len(self._blur_cur) > n:
            del self._blur_cur[n:]
        while len(self._blur_cur) < n:
            self._blur_cur.append(self._blur_target(len(self._blur_cur)))
        if len(self._alpha_cur) > n:
            del self._alpha_cur[n:]
        while len(self._alpha_cur) < n:
            self._alpha_cur.append(self._alpha_target(len(self._alpha_cur)))
        self._blur_cache.clear()
        self._retarget_rows(snap=True)

    def _blur_target(self, i):
        """某行的目标模糊 σ：近处轻、远处化开（查表，已唱过等效距离 +1）。"""
        cur = self._cur_index
        if i == cur:
            return 0.0
        d = int(i - cur) if i > cur else int(cur - i) + 1
        d = max(d, 1)
        d = min(d, len(BLUR_DIST))
        return BLUR_DIST[d - 1]

    def _alpha_target(self, i):
        """某行的目标不透明度（AMLL 亮度体系：近处亮、远处暗，当前行全亮）。"""
        cur = self._cur_index
        if i == cur:
            return 1.0
        d = int(i - cur) if i > cur else int(cur - i) + 1
        d = max(d, 1)
        return (INACTIVE_OPACITY
                + (INACTIVE_OPACITY_NEAR - INACTIVE_OPACITY)
                * (0.55 ** (d - 1)))

    def _em_px(self):
        """当前基准字体的 em（≈ CSS 的 1em，单位：逻辑像素）。"""
        if getattr(self, "_em_pt", None) == self._base_pt:
            return self._em_val
        px = QFontInfo(self._font(self._base_pt)).pixelSize()
        val = float(px) if px > 0 else self._base_pt * 4.0 / 3.0
        self._em_pt = self._base_pt
        self._em_val = val
        return val

    def _line_extents(self, i):
        """某行相对中心线的（上缘, 下缘）距离；下缘包含翻译行（按实际折行数）。"""
        # 注意用**主歌词**的块高算（_row_heights 里带着翻译多占的行高，
        # 那是给行距用的；这里要的是实际绘制内容的上下缘）
        n_seg = (len(self._segs_cache[i]) if 0 <= i < len(self._segs_cache)
                 else 1)
        h = self._row_h * max(1, n_seg)
        top = bottom = h / 2.0
        if 0 <= i < len(self._lines):
            row = self._lines[i]
            trans = row[2] if row and len(row) > 2 else ""
            if trans and self.show_translation:
                n = self._n_trans[i] if 0 <= i < len(self._n_trans) else 1
                bottom += self._trans_h * max(1, n)
        return top, bottom

    def _retarget_rows(self, seek=False, snap=False):
        """重新计算每行的目标位置并交给各自的弹簧（含阶梯延迟）。"""
        n = min(len(self._line_y), len(self._lines))
        if n <= 0:
            return
        if len(self._springs) > n:
            del self._springs[n:]
        if len(self._scale_springs) > n:
            del self._scale_springs[n:]
        sm, sc, sk = SCALE_SPRING
        while len(self._springs) < n:
            self._springs.append(_Spring1D())
        while len(self._scale_springs) < n:
            s = _Spring1D(SCALE_INACTIVE, mass=sm)
            s.set_params(sk, sc)
            self._scale_springs.append(s)
        cur = min(self._cur_index, n - 1)

        # 弹簧参数：正常播放按行间隔映射，seek / 间奏 / 首行用慢速（AMLL）
        times = self._times
        interval = None
        if 0 < cur < len(times):
            interval = times[cur] - times[cur - 1]
        if (seek or self._iv_focus or cur == 0
                or (interval is not None and interval >= 7.0)):
            k, c = SPRING_SLOW
        elif cur >= n - 1:
            k, c = SPRING_END
        else:
            iv = min(max(interval, 0.1), 0.8)
            ratio = max(0.0, 1.0 - (iv - 0.1) / 0.7) ** 0.2
            k = SPRING_K_MIN + ratio * (SPRING_K_MAX - SPRING_K_MIN)
            c = SPRING_DAMP * math.sqrt(k)

        cy = self._focus_cy()
        ivp = self._active_iv if self._iv_focus else None
        if ivp is not None:
            # 间奏点布局（AMLL）：点块中心 = 焦点，点块高 1.3em；
            # 上一行文字底边在 cy-1.05em、下一行顶边在 cy+1.05em
            # （1.05em = 点块半高 0.65em + 行/点各自的 0.4em 内边距），
            # 点就会“紧贴”上一行出现，而不是飘在一整个行距的空白里。
            gap_em = 1.05 * self._em_px()
            a = ivp["anchor"]
            base = self._line_y[cur]
            targets = [cy + (self._line_y[i] - base) for i in range(n)]
            if a >= n:
                a = -1
            if a >= 0:
                _, b_ext = self._line_extents(a)
                targets[a] = cy - gap_em - b_ext
                for i in range(0, a):
                    targets[i] = targets[a] - (self._line_y[a] - self._line_y[i])
            nxt = a + 1
            if nxt < n:
                t_ext, _ = self._line_extents(nxt)
                targets[nxt] = cy + gap_em + t_ext
                for i in range(nxt + 1, n):
                    targets[i] = (targets[nxt]
                                  + (self._line_y[i] - self._line_y[nxt]))
        else:
            base = self._line_y[cur]
            targets = [cy + (self._line_y[i] - base) for i in range(n)]

        # 阶梯延迟：从视口上缘往下逐行累计，越过当前行后逐行衰减
        top = self.height() * TEXT_TOP
        if seek:
            delays = [0.0] * n
        else:
            delays = []
            d, step = 0.0, ROW_DELAY
            for i in range(n):
                h_i = self._row_heights[i] if i < len(self._row_heights) else 0.0
                if targets[i] + h_i / 2.0 >= top:
                    d += step
                    if i >= cur:
                        step *= ROW_DELAY_DECAY
                delays.append(d)

        # 布局重建 / 拖进度条时直接吸附，不播动画
        stick = snap or self._dragging
        for i in range(n):
            sp = self._springs[i]
            sp.set_params(k, c)
            if stick:
                sp.set_position(targets[i])
            else:
                sp.set_target(targets[i], delays[i])
            ss = self._scale_springs[i]
            target_scale = SCALE_ACTIVE if i == cur else SCALE_INACTIVE
            if stick:
                ss.set_position(target_scale)
            else:
                ss.set_target(target_scale)

        # 间奏点：滑到焦点位置（间奏开始时已从下方一行就位）
        if ivp is not None:
            dsp = self._dots_spring
            dsp.set_params(k, c)
            if stick:
                dsp.set_position(cy)
            else:
                dsp.set_target(cy, 0.0 if seek else ROW_DELAY)

    def _update_rows(self, dt):
        for sp in self._springs:
            sp.update(dt)
        for sp in self._scale_springs:
            sp.update(dt)
        self._dots_spring.update(dt)
        # 模糊 / 不透明度平滑过渡（对照 AMLL 的 CSS transition）
        if dt > 0.0 and self._blur_cur:
            k = 1.0 - math.exp(-dt / BLUR_TAU)
            for i in range(len(self._blur_cur)):
                c = self._blur_cur[i]
                self._blur_cur[i] = c + (self._blur_target(i) - c) * k
            for i in range(len(self._alpha_cur)):
                a = self._alpha_cur[i]
                self._alpha_cur[i] = a + (self._alpha_target(i) - a) * k

    # ------------------------------------------------------------------ #
    # 间奏点（仿 Apple Music）：长间奏时的呼吸圆点
    # ------------------------------------------------------------------ #
    def _calc_interludes(self):
        """预计算长间奏区间：[(起点, 终点, 上一行索引)]，空隙 ≥ INTERLUDE_GAP 才收录。"""
        times, ends = self._times, self._ends
        if not self._synced or not times or not ends:
            return []
        n = min(len(times), len(ends))
        out = []
        max_end = 0.0
        for i in range(-1, n - 1):
            if i >= 0:
                max_end = max(max_end, ends[i])
            gap_end = max(max_end, times[i + 1])
            if gap_end - max_end >= INTERLUDE_GAP:
                out.append((max_end, gap_end, i))
        return out

    def _focus_cy(self):
        return self.height() * FOCUS_RATIO

    def _sync_interlude(self, pos_eff, jumped):
        """按当前播放位置更新间奏演出状态（每帧调用）。"""
        found = None
        for st, en, anc in self._interludes:
            if st <= pos_eff < en:
                found = (st, en, anc)
                break
        if found is None:
            self._iv_focus = False
            self._active_iv = None
            return
        was_focus = self._iv_focus
        key = (found[0], found[1])
        if (self._active_iv is None or self._active_iv["key"] != key
                or jumped or pos_eff < self._active_iv["anchor_time"]):
            self._active_iv = self._make_iv_plan(found, pos_eff)
            if self._active_iv["usable"]:
                if was_focus:
                    # 已在间奏里（拖进度/后退 seek 重建了演出）：确保点
                    # 回到焦点，不能让它从“下方一行”重新滑入而卡在下面
                    self._dots_spring.set_target(self._focus_cy(), 0.0)
                else:
                    # 全新进入：从“上一行下方一行”滑入（AMLL 同款观感）
                    self._dots_spring.set_position(
                        self._focus_cy() + self._spacing)
        self._iv_focus = bool(self._active_iv and self._active_iv.get("usable"))

    def _make_iv_plan(self, iv, pos_eff):
        """按间奏区间与当前时刻算出整场演出的时间编排（AMLL 参数）。"""
        st, en, anc = iv
        anchor_time = min(max(pos_eff, st), en)
        remaining_ms = (en - anchor_time) * 1000.0
        delay = 0.0 if anc < 0 else DOTS_DELAY_MS
        body = remaining_ms - delay - DOTS_EXIT_MS
        plan = {"key": (st, en), "anchor": anc, "anchor_time": anchor_time,
                "delay_ms": delay, "usable": body >= DOTS_MIN_BODY_MS}
        if not plan["usable"]:
            return plan
        plan["body_end_ms"] = delay + body
        plan["total_end_ms"] = delay + body + DOTS_EXIT_MS
        if body < DOTS_HOLD_BODY_MS:
            plan["mode"] = "hold"
            plan["d3t"] = 1.0
        else:
            plan["mode"] = "breathe"
            cycles = max(1.0, math.floor(body / DOTS_PERIOD_MS))
            seg = round((body + DOTS_TRAIL_MS) / 3.0)
            d3 = body - seg * 2.0
            plan["period_ms"] = body / cycles
            plan["segment_ms"] = float(seg)
            plan["d3dur_ms"] = max(1.0, d3)
            plan["d3t"] = max(0.0, min(1.0, d3 / seg)) if seg > 0 else 1.0
        return plan

    @staticmethod
    def _clamp01(x):
        return min(1.0, max(0.0, x))

    def _eval_dots(self, pos_eff):
        """从播放位置推导三点动画快照 (ops, scale, opacity)；不展示时返回 None。"""
        plan = self._active_iv
        if not plan or not plan["usable"]:
            return None
        elapsed = (pos_eff - plan["anchor_time"]) * 1000.0
        if elapsed < plan["delay_ms"] or elapsed >= plan["total_end_ms"]:
            return None
        internal = elapsed - plan["delay_ms"]
        c01 = self._clamp01
        if internal >= plan["body_end_ms"]:
            # 退场：放大蓄力 -> 缩小 -> 渐隐；第三颗点补亮
            ex = internal - plan["body_end_ms"]
            fade_t = c01((ex - (DOTS_EXIT_MS - DOTS_EXIT_FADE_MS))
                         / DOTS_EXIT_FADE_MS)
            opacity = 1.0 - _E_EXIT_FADE(fade_t)
            if ex < DOTS_EXIT_PHASE1_MS:
                scale = 1.0 + _E_EXIT1(ex / DOTS_EXIT_PHASE1_MS) * (
                    DOTS_MAX_SCALE - 1.0)
            else:
                t2 = c01((ex - DOTS_EXIT_PHASE1_MS) / DOTS_EXIT_PHASE2_MS)
                scale = DOTS_MAX_SCALE - _E_EXIT2(t2) * (
                    DOTS_MAX_SCALE - DOTS_MIN_SCALE)
            fracs = [1.0, 1.0,
                     plan["d3t"] + (1.0 - plan["d3t"]) * c01(ex / DOTS_TRAIL_MS)]
        else:
            opacity = _E_ENTER(c01(internal / DOTS_ENTER_MS))
            if plan["mode"] == "hold":
                scale = 1.0
                fracs = [1.0, 1.0, 1.0]
            else:
                ct = (internal % plan["period_ms"]) / plan["period_ms"]
                scale = 1.0 + (0.5 - 0.5 * math.cos(2.0 * math.pi * ct)) * (
                    DOTS_MAX_SCALE - 1.0)
                seg = plan["segment_ms"]
                fracs = [
                    _E_LIGHT(c01(internal / seg)),
                    _E_LIGHT(c01((internal - seg) / seg)),
                    _E_LIGHT(c01((internal - 2.0 * seg) / plan["d3dur_ms"]))
                    * plan["d3t"],
                ]
        ops = []
        for i in range(3):
            a = DOTS_INACTIVE + (DOTS_ACTIVE - DOTS_INACTIVE) * c01(fracs[i])
            enter = c01((internal - i * DOTS_STAGGER_MS) / DOTS_FADE_MS) ** 2
            ops.append(a * enter)
        return (ops, scale, opacity)

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #
    def _font(self, pt, bold=False, heavy=False):
        # 拉丁优先随包的 **SF Pro Display**（heavy 会用最重的 Black 面），
        # 中文回退到 `cjk_font`（默认思源黑体 / Noto Sans SC，同样有 Black）。
        # 两家字体都是“同家族多字重”，所以家族名逐级点名 + 按字重回退
        # 两手都要；Qt 会按 families 列表逐字符回退（拉丁→SF，汉字→中文字体）。
        fam = str(self.font_family or DEFAULT_FONT)
        cjk = str(self.cjk_font or DEFAULT_CJK)
        level = 2 if heavy else (1 if bold else 0)

        def variants(name):
            if level == 2:
                return [name + " Black", name + " Heavy", name + " Bold",
                        name]
            if level == 1:
                return [name + " Bold", name]
            return [name + " Medium", name]

        chain = variants(fam)
        chain += variants("Inter")           # 随包拉丁（OFL，观感接近 SF Pro）
        if cjk and cjk != fam:
            chain += variants(cjk)
        chain += variants("Noto Sans S Chinese")   # 随包中文（思源黑体子集，OFL）
        chain += ["Segoe UI", "Microsoft YaHei UI"]
        seen, fams = set(), []
        for x in chain:
            if x not in seen:
                seen.add(x)
                fams.append(x)
        f = QFont()
        f.setFamilies(fams)
        f.setPointSizeF(pt)
        # heavy 用 900（Black）：SF Pro / 思源黑体 / MiSans 都真有 Black 或
        # Heavy 这一面；只有 Bold 的字体就回退到 Bold，不会伪粗
        f.setWeight(QFont.Weight.Black if level == 2
                    else (QFont.Weight.DemiBold if level == 1
                          else QFont.Weight.Medium))
        return f

    @staticmethod
    def _trans_rows(text, font, max_w):
        """把翻译折成最多两行。

        断点选择：先找出所有“放得下”的候选断点（优先空格 / 标点后），
        再挑**两行宽度最接近**的那个 —— 否则会出现“第二行只剩两个字”
        这种难看的排版。一个可断点都没有时退而求其次硬断。
        """
        fm = QFontMetricsF(font)
        if max_w <= 0 or fm.horizontalAdvance(text) <= max_w:
            return [text]
        punct = " ，。、；：？！,.;:?!-—"
        cands, any_cands = [], []
        for k in range(1, len(text)):
            if fm.horizontalAdvance(text[:k]) > max_w:
                break
            any_cands.append(k)
            if text[k - 1] in punct:
                cands.append(k)
        if not cands:
            cands = any_cands
        if not cands:
            return [text]
        best, best_score = cands[0], None
        for k in cands:
            wl = fm.horizontalAdvance(text[:k].rstrip())
            wr = fm.horizontalAdvance(text[k:].lstrip())
            score = max(wl, wr)          # 让最长的那行尽量短
            if best_score is None or score < best_score:
                best, best_score = k, score
        return [text[:best].rstrip(), text[best:].lstrip()]

    def _trans_layout(self, key, text, pt, max_w):
        """翻译排版：最多两行；两行还放不下就把整句缩小（缩完再量）。

        返回 (字号, 行列表)。折行算完要重新量——缩小后断点会变，
        所以迭代两三次。结果按行缓存（布局/文本不变就不重算）。
        """
        c = self._trans_cache.get(key)
        if c is not None and c[0] == text and abs(c[1] - max_w) < 1.0:
            return c[2], c[3]
        ratio, rows = 1.0, [text]
        if max_w > 0 and text:
            for _ in range(3):
                font = self._font(pt * ratio, heavy=True)
                rows = self._trans_rows(text, font, max_w * 0.98)
                fm = QFontMetricsF(font)
                widest = max(fm.horizontalAdvance(r) for r in rows)
                if widest <= max_w * 0.98:
                    break
                ratio *= (max_w * 0.98) / widest
        self._trans_cache[key] = (text, max_w, pt * ratio, rows)
        return pt * ratio, rows

    def _fit_ratio(self, key, texts, max_w, margin=0.98):
        """算出让这些文本都放得下的字号倍率。

        为什么不能一次算完：按比例缩小字号后，**每个字的实际步进会被
        量化/向上取整**，几十个字累起来就能多出十几个像素 —— 长句的尾巴
        正是这样被裁切框切掉的。所以缩完要再量、量完再纠（两次就收敛）。
        倍率只和文本 / 可用宽度有关，缓存起来。
        """
        c = self._fit_cache.get(key)
        if c is not None and abs(c[0] - max_w) < 1.0:
            return c[1]
        r = 1.0
        if max_w > 0 and texts:
            for _ in range(3):
                fm = QFontMetricsF(self._font(self._base_pt * r, heavy=True))
                w = max(fm.horizontalAdvance(t) for t in texts)
                if w <= max_w * margin:
                    break
                r *= (max_w * margin) / w
        self._fit_cache[key] = (max_w, r)
        return r

    def _ensure_layout(self):
        area_w = max(60.0, self.width() * TEXT_W)
        base_pt = min(76.0, max(20.0, self.height() * 0.042))
        dpr = self.devicePixelRatioF()
        if (abs(base_pt - self._base_pt) < 0.05
                and abs(area_w - self._layout_w) < 2.0
                and abs(dpr - self._dpr) < 0.01
                and self._layout_ver == self._lyrics_ver
                and len(self._segs_cache) == len(self._lines)):
            return
        if abs(dpr - self._dpr) >= 0.01:
            self._dpr = dpr                 # 换屏幕/缩放变化：位图要按新 DPR 重建
            self._blur_cache.clear()
        self._base_pt = base_pt
        self._layout_w = area_w
        self._layout_ver = self._lyrics_ver

        row_h = QFontMetricsF(self._font(base_pt)).height()
        self._row_h = row_h
        gap = row_h * GAP_ROWS
        self._spacing = row_h * (1.0 + GAP_ROWS)

        # 折行探测字体 = 实际绘制字体（heavy）+ 3% 余量：字重必须跟绘制一致，
        # 否则 Black 比 Bold 宽出来的那几个字会被裁切框硬切（右边缺一截）
        fm_probe = QFontMetricsF(self._font(base_pt * 1.03, heavy=True))
        segs_all = []
        for _t, text, _tr in self._lines:
            segs_all.append(self._wrap_for(text, fm_probe, area_w))
        self._segs_cache = segs_all
        self._fit_cache.clear()              # 布局变了，缩排倍率重算
        self._trans_cache.clear()
        self._runs_cache = []
        for i, segs in enumerate(segs_all):
            ws = self._rel_words[i] if i < len(self._rel_words) else None
            self._runs_cache.append(self._build_runs(segs, ws))

        # 翻译折行数：折两行的翻译要多占一行行高，计入行块高度 —— 否则第二行
        # 翻译会占掉行间空隙、叠到下一行歌词身上（主句自己也是两行时最明显）
        self._trans_h = QFontMetricsF(
            self._font(base_pt * TRANS_SCALE, heavy=True)).height()
        n_trans = []
        for i, (_t, _text, trans) in enumerate(self._lines):
            n = 1
            if trans and self.show_translation and area_w > 0:
                _pt, rows = self._trans_layout(("trans", i), trans,
                                               base_pt * TRANS_SCALE, area_w)
                n = max(1, len(rows))
            n_trans.append(n)
        self._n_trans = n_trans
        heights = [row_h * len(segs_all[i]) + (n_trans[i] - 1) * self._trans_h
                   for i in range(len(segs_all))]

        # 首/末字母的**墨迹**可能探出绘制原点（“j” 的左钩、"y" 的尾巴这类负
        # bearing）：正文左对齐、紧贴歌词区左缘画，探出的那一小条会被裁剪框
        # 切掉（“just …” 看起来像 “iust …”）。按实测外挂把裁剪框放宽，
        # 只放宽裁剪、不动文字位置，行距排版不受影响。
        fm_ink = QFontMetricsF(self._font(base_pt, heavy=True))
        fm_ink_t = QFontMetricsF(self._font(base_pt * TRANS_SCALE,
                                            heavy=True))
        left_over, right_over = 0.0, 0.0
        for _t, text, trans in self._lines:
            for s, fmx in ((text, fm_ink),
                           (trans if self.show_translation else "", fm_ink_t)):
                if not s:
                    continue
                br = fmx.tightBoundingRect(s[:24])
                if br.left() < left_over:
                    left_over = br.left()
                tail = s[-24:]
                right_over = max(right_over,
                                 fmx.tightBoundingRect(tail).right()
                                 - fmx.horizontalAdvance(tail))
        self._ink_pad = (max(2.0, -left_over + 1.5),
                         max(2.0, right_over + 1.5))
        # 布局/字号变了：翻译动画的起飞记录、baseline 缓存全部作废
        self._trans_state.clear()

        # 恒定"边缘间距"：块与块之间的空隙永远是 gap
        ys, y = [], 0.0
        for i, h in enumerate(heights):
            if i > 0:
                y += heights[i - 1] / 2.0 + gap + h / 2.0
            ys.append(y)
        self._line_y = ys
        self._row_heights = heights
        self._rebuild_rows(len(self._lines))

    @staticmethod
    def _build_runs(segs, words):
        """把折行后的行文本按逐词时间切成运行段 [(文本, b, e), ...]。

        运行段从词首到下一词首（含词间空格），逐词上浮时按词的起止时间
        平移。文本与词表对不上时返回 None（整行不浮动，保持原样绘制）。
        """
        if not words:
            return None
        out = []
        wi, wci = 0, 0                  # 当前词索引、词内已匹配字符数
        for seg in segs:
            n = len(seg)
            if wi >= len(words):
                # 词表已用完（行尾多出的字符）：并入上一行最后一段
                if out and out[-1]:
                    t, b, e = out[-1][-1]
                    out[-1][-1] = (t + seg, b, e)
                elif seg:
                    out.append([(seg, words[-1][0], words[-1][1])])
                continue
            marks = [(0, wi)] if wci > 0 else []   # 词跨行：本行从中间继续
            i = 0
            while i < n and wi < len(words):
                w = words[wi][2]
                if wci < len(w) and seg[i] == w[wci]:
                    if wci == 0:
                        marks.append((i, wi))      # 新词从这里开始
                    wci += 1
                    i += 1
                    if wci >= len(w):
                        wi += 1
                        wci = 0
                elif wci == 0 and not seg[i].isspace():
                    return None                    # 文本对不上：不浮动
                else:
                    i += 1
            if not marks:
                if seg.strip():
                    return None
                out.append([])
                continue
            if marks[0][0] != 0:
                marks[0] = (0, marks[0][1])        # 行首空格归入第一个词
            runs = []
            for k, (pos, idx) in enumerate(marks):
                end = marks[k + 1][0] if k + 1 < len(marks) else n
                b, e = words[idx][0], words[idx][1]
                runs.append((seg[pos:end], b, e))
            out.append(runs)
        return out

    @staticmethod
    def _wrap_for(text, fm, max_w):
        if fm.horizontalAdvance(text) <= max_w or len(text) < 4:
            return [text]
        mid = len(text) // 2
        cut = -1
        for delta in range(0, min(14, mid)):
            for pos in (mid - delta, mid + delta):
                if 0 < pos < len(text) - 1 and text[pos] == " ":
                    cut = pos
                    break
            if cut > 0:
                break
        if cut > 0:
            a, b = text[:cut].strip(), text[cut:].strip()
        else:
            a, b = text[:mid], text[mid:]
        return [a, b] if a and b else [text]

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        p.fillRect(self.rect(), QColor(11, 11, 14))
        # 彩色柔光底：模糊后的专辑封面（AMLL 方案），换歌时 0.5s 交叉过渡
        if self._bg is not None or self._bg_prev is not None:
            k = (1.0 if self._bg_prev is None
                 else min(1.0, (time.monotonic() - self._bg_ts) / BG_FADE_SEC))
            if self._bg_prev is not None and k < 1.0:
                p.setOpacity(self._bg_prev_alpha * (1.0 - k))
                p.drawPixmap(self.rect(), self._bg_prev)
            if self._bg is not None and k > 0.0:
                p.setOpacity(self._bg_alpha * k)
                p.drawPixmap(self.rect(), self._bg)
            p.setOpacity(1.0)
        # 压暗（上/下更深）与暗角：柔光底之上保证歌词可读
        g2 = QLinearGradient(0, 0, 0, h)
        g2.setColorAt(0.0, QColor(0, 0, 0, 76))
        g2.setColorAt(0.5, QColor(0, 0, 0, 22))
        g2.setColorAt(1.0, QColor(0, 0, 0, 132))
        p.fillRect(self.rect(), QBrush(g2))
        vg = QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.78)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 88))
        p.fillRect(self.rect(), QBrush(vg))

        vinyl_cx = w * 0.24
        vinyl_cy = h * 0.45
        radius = min(h * 0.37, w * 0.27)
        self._draw_vinyl(p, vinyl_cx, vinyl_cy, max(60.0, radius))

        area = QRectF(w * TEXT_X, h * TEXT_TOP, w * TEXT_W, h * TEXT_H)
        self._draw_header(p, area)
        self._draw_content(p, area)
        self._draw_bar(p)
        self._draw_toast(p)
        p.end()

    def _draw_vinyl(self, p, cx, cy, R):
        """唱片：柔影（封面色）+ 盘面（切歌时新旧交叉淡入）+ 唱臂。"""
        p.save()
        p.translate(cx, cy)
        # 封面色彩的柔影（对照 YesPlayMusic 歌词页的 .shadow）：模糊一份封面、
        # 略往下移、拉大一圈当光晕，唱片就像“浮”在自己的颜色上（只算一次）
        sh = self._art_shadow()
        if sh is not None:
            s = R * 2.6
            p.save()
            p.translate(0.0, R * 0.06)
            p.setOpacity(0.72)
            p.drawPixmap(QRectF(-s / 2.0, -s / 2.0, s, s), sh,
                         QRectF(sh.rect()))
            p.restore()
        k = self._vinyl_fade()
        if k < 1.0 and self._plate_prev is not None:
            self._draw_disc(p, cx, cy, R, self._plate_prev, self._art_prev,
                            1.0 - k)
        self._draw_disc(p, cx, cy, R, self._plate_pixmap(R), self._art, k)
        p.restore()

        self._draw_tonearm(p, cx, cy, R)

    def _draw_disc(self, p, cx, cy, R, layers, art, opacity):
        """画一张盘面（三层 + 封面标签）。

        顺序：底盘 → 花纹（随盘转）→ 沟槽 / 反光（不转）→ 封面标签（随盘
        转、压在沟槽之上）→ 标签压边。opacity < 1 用于切歌换盘。
        """
        base, pat, over = layers
        half = R + 3.0
        # 对齐到物理像素网格：避免亚像素重采样把 1px 的沟槽磨糊
        dpr = self._dpr
        gx = round((cx - half) * dpr) / dpr - cx
        gy = round((cy - half) * dpr) / dpr - cy
        rect = QRectF(gx, gy, half * 2.0, half * 2.0)
        p.setOpacity(opacity)
        p.drawPixmap(rect, base, QRectF(base.rect()))
        if pat is not None:                     # 花纹层跟着盘转
            p.save()
            p.rotate(self._angle)
            p.drawPixmap(rect, pat, QRectF(pat.rect()))
            p.restore()
        p.drawPixmap(rect, over, QRectF(over.rect()))

        # 封面（圆裁切 = 唱片中心标签）：只有图案要跟着转，圆形裁切不受影响
        rr = R * VINYL_COVER_R
        p.save()
        path = QPainterPath()
        path.addEllipse(QRectF(-rr, -rr, 2 * rr, 2 * rr))
        p.setClipPath(path)
        if art is not None:
            p.save()
            p.rotate(self._angle)
            p.drawPixmap(QRectF(-rr, -rr, 2 * rr, 2 * rr), art,
                         QRectF(art.rect()))
            p.restore()
        else:                          # 还没拿到封面：深色标签占位
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(28, 28, 32))
            p.drawEllipse(QRectF(-rr, -rr, 2 * rr, 2 * rr))
            p.setPen(QPen(QColor(255, 255, 255, 26), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(-rr * 0.72, -rr * 0.72, rr * 1.44, rr * 1.44))
        p.restore()
        # 标签压边：封面外是一圈很细的暗缝 + 一道亮线
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 110), 3.0))
        p.drawEllipse(QRectF(-rr - 1.5, -rr - 1.5, 2 * rr + 3.0, 2 * rr + 3.0))
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.2))
        p.drawEllipse(QRectF(-rr, -rr, 2 * rr, 2 * rr))
        p.setOpacity(1.0)

    def _art_shadow(self):
        """封面色彩的柔影（YesPlayMusic 的 .shadow：blur(16px) opacity(.6)
        + 下移 12px + scale(.92,.96)）。在 320px 的小画布上算一次高斯，
        绘制时拉到 2.6R —— 封面换一张就重算一次。"""
        if self._art is None:
            return None
        key = self._art.cacheKey()
        if self._shadow_pm is not None and self._shadow_key == key:
            return self._shadow_pm
        side = 320
        img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = side * 0.95 / 2.6                  # 影体半径（= 0.95R，画布边长 2.6R）
        box = QRectF(side / 2.0 - r, side / 2.0 - r, r * 2.0, r * 2.0)
        path = QPainterPath()
        path.addEllipse(box)
        q.setClipPath(path)
        q.drawPixmap(box, self._art, QRectF(self._art.rect()))
        q.end()
        if _HAS_PIL:
            img = _gaussian_qimage(img, 7.4)   # ≈ 0.06R 的 σ（同 YesPlayMusic 的比例）
        else:                                  # 无 Pillow：降采样近似
            half = img.scaled(side // 4, side // 4,
                              Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            img = half.scaled(side, side,
                              Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        # 压暗：背景本身就是同一张封面的柔光底，直接叠彩色晕看不出层次；
        # 压暗后它才读得出“投在地上的影”（YesPlayMusic 那张封面正好很暗）
        q = QPainter(img)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        q.fillRect(img.rect(), QColor(0, 0, 0, 165))
        q.end()
        self._shadow_pm = QPixmap.fromImage(img)
        self._shadow_key = key
        return self._shadow_pm

    def _plate_pixmap(self, R):
        """盘体预渲染成位图（交给 vinyl 模块），返回三层：

        (底盘, 花纹层, 表层) —— 花纹层要跟着盘转、其余两层不转，
        所以不能合成一张。只在尺寸 / 屏幕缩放 / 材质变化时重画。
        """
        key = (round(R, 1), round(self._dpr, 2), self._vinyl_mat["id"])
        if self._plate_pm is not None and self._plate_key == key:
            return self._plate_pm
        self._plate_pm = vinyl.render_plate(R, self._dpr, self._vinyl_mat)
        self._plate_key = key
        return self._plate_pm

    def _draw_tonearm(self, p, cx, cy, R):
        """唱臂：几何（枢轴/落点/抬臂）在这里算，样子交给 tonearm.py。

        唱臂从盘外右上斜进沟槽区，唱针落在 VINYL_ARM_HIT（≈0.8R，
        外圈音轨）；暂停时向外轻抬 VINYL_ARM_LIFT 度，像抬臂待机。
        """
        hx, hy = VINYL_ARM_HIT
        ax, ay = VINYL_ARM_PIVOT
        # 枢轴不能伸进歌词区（小窗口下自动往回收）；
        # 也不能太靠上 —— 否则配重会被屏幕顶边裁掉（配重伸到枢轴外 0.25R）
        px = min(cx + R * ax, self.width() * TEXT_X - R * 0.12)
        py = max(cy + R * ay, R * 0.30)
        dx, dy = cx + R * hx - px, cy + R * hy - py
        L = math.hypot(dx, dy)
        ang = math.degrees(math.atan2(dy, dx))
        tonearm.draw_static(p, px, py, R)           # 信号线（不随臂转）
        p.save()
        p.translate(px, py)
        p.rotate(ang + self._arm_off)
        tonearm.draw(p, R, L)
        p.restore()

    def _draw_header(self, p, area):
        """标题 / 歌手（比歌词小一级，但足够看清）。"""
        if not (self.title or self.artist):
            return
        f = self._font(max(14.0, self.height() * 0.024), heavy=True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 204))
        p.drawText(QRectF(area.left(), area.top() - self.height() * 0.088,
                          area.width(), self.height() * 0.048),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.title)
        f2 = self._font(max(12.0, self.height() * 0.018), bold=True)
        p.setFont(f2)
        p.setPen(QColor(255, 255, 255, 116))
        p.drawText(QRectF(area.left(), area.top() - self.height() * 0.052,
                          area.width(), self.height() * 0.034),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.artist)

    def _draw_content(self, p, area):
        p.save()
        # 左右按实测“墨迹外挂”放宽（首字母的左钩等），纵向保持原样；
        # 严格贴着区域左缘裁会切掉第一个字母探出的那一小条
        pl, pr = self._ink_pad
        p.setClipRect(area.adjusted(-pl, 0.0, pr, 0.0))
        if self._synced and self._lines:
            self._draw_synced(p, area)
        elif self._plain:
            self._draw_plain(p, area)
        else:
            f = self._font(max(14.0, self.height() * 0.028))
            p.setFont(f)
            p.setPen(QColor(220, 222, 232, 150))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter,
                       self.status_text or "暂无歌词")
        p.restore()

    def _draw_synced(self, p, area):
        self._ensure_layout()
        if not self._springs:
            return
        base_pt = self._base_pt
        cy = self._focus_cy()
        limit = area.height() * 0.60

        for i in range(len(self._lines)):
            if i >= len(self._line_y) or i >= len(self._springs):
                break
            y_c = self._springs[i].pos
            if abs(y_c - cy) > limit:
                continue
            _t, text, trans = self._lines[i]
            segs = self._segs_cache[i] if i < len(self._segs_cache) else [text]
            if i == self._cur_index:
                self._draw_active_line(p, area, segs, base_pt, y_c, trans)
            else:
                self._draw_other_line(p, area, i, segs, base_pt, y_c)

        # 间奏点（仿 Apple Music）：画在所有行之上
        if self._dots_snap is not None:
            self._draw_interlude_dots(p, area)

    def _draw_active_line(self, p, area, segs, base_pt, y_c, trans):
        """当前行：清晰、粗体、逐字填充（实时绘制，不用位图）。"""
        alpha = (self._alpha_cur[self._cur_index]
                 if self._cur_index < len(self._alpha_cur) else 1.0)
        if alpha < 0.995:
            p.setOpacity(alpha)              # 从上方滚入时亮度平滑淡入
        scale = (self._scale_springs[self._cur_index].pos
                 if self._cur_index < len(self._scale_springs)
                 else SCALE_ACTIVE)
        max_w = area.width()
        # 用和绘制一致的字重（Black）量，并按实际度量纠到放得下
        scale *= self._fit_ratio(("line", self._cur_index), segs, max_w)
        font = self._font(base_pt * scale, heavy=True)
        p.setFont(font)
        fm = QFontMetricsF(font)
        row_h = fm.height()
        widths = [fm.horizontalAdvance(s) for s in segs]
        total_h = row_h * len(segs)
        y0 = y_c - total_h / 2.0
        runs = (self._runs_cache[self._cur_index]
                if self._cur_index < len(self._runs_cache) else None)
        self._draw_rows(p, area, segs, widths, font, row_h, y0, self._frac,
                        runs=runs, em=self._em_px() * scale,
                        elapsed=self._elapsed)
        if trans and self.show_translation:
            # 翻译先折行（最多两行）；两行还放不下才缩（缩完再量），不硬切
            pt_t, rows = self._trans_layout(
                ("trans", self._cur_index), trans,
                base_pt * scale * TRANS_SCALE, max_w)
            f2 = self._font(pt_t, heavy=True)
            y_t = y0 + total_h
            if not self._draw_trans_converge(p, area, f2, y_t, row_h, rows):
                # 整行绘制：和逐字路径共用同一条 baseline（切回来不会跳）
                p.setFont(f2)
                p.setPen(QColor(255, 255, 255, TRANS_ACTIVE_ALPHA))
                h_t = QFontMetricsF(f2).height()
                for r, row in enumerate(rows):
                    p.drawText(QPointF(area.left(),
                                       y_t + r * h_t
                                       + self._trans_ascent(f2, row)), row)
        p.setOpacity(1.0)

    def _line_ascent(self, font, text):
        """整行（可能中英混排）的 baseline 离行顶有多远。

        为什么不能用 QFontMetricsF(font).ascent()：那是**首选字体**（拉丁）的
        度量；汉字实际由回退字体排版，它的 ascent 大很多 —— 整行绘制时 Qt 取
        的是两者中较大的那条 baseline。逐字绘制时若各用各字体，英文就会偏上，
        等整行画出来又落下（就是“英文名字突然往下跳一下”的根因）。
        这里用 QTextLayout 量出**整行真实的 ascent**，两边都用它当锚点。
        """
        tl = QTextLayout(text or "测", font)   # 空行给个汉字哨兵，拿到正常 ascent
        tl.beginLayout()
        line = tl.createLine()
        asc = None
        if line is not None:
            line.setLineWidth(1e6)             # 不换行：只要它的 ascent
            asc = float(line.ascent())
        tl.endLayout()
        if asc is None or asc <= 0.0:
            asc = float(QFontMetricsF(font).ascent())
        return asc

    def _trans_ascent(self, font, text):
        """翻译行的 baseline 偏移（按行文本缓存；换行/布局变化会清空）。"""
        st = self._trans_state
        cache = st.setdefault("ascents", {})
        asc = cache.get(text)
        if asc is None:
            asc = self._line_ascent(font, text)
            cache[text] = asc
        return asc

    def _draw_trans_converge(self, p, area, font, y_top, row_h, rows):
        """翻译的“从四周汇聚”入场：每个字从不同方向的偏移处由虚到实
        浮入到最终位置（可以一到两行）。

        **分工**（这是顺滑的关键）：
          * 出发时刻 = 主句填充进度越过该字的阈值 —— 跟演唱对齐，
            唱到哪个字，哪个字才起飞；
          * 飞行过程 = 播放时间轴上的固定时长（TRANS_MOTION_SEC）+ 缓出，
            和主句逐词上浮同一套时间轴：暂停冻结、seek 重来。
        早先版本把飞行也挂在填充上，而逐词填充在词间空隙会**冻结**，
        于是字会“飞一半停住、下一词开始时再跳一下”—— 不再这么干。

        返回 True 表示还需逐字绘制；False 表示所有字已归位，调用方按
        常规整行绘制（省开销）。
        """
        f = self._frac
        if f <= 0.0:
            return True                        # 主句还没起唱：先不出现
        fm = QFontMetricsF(font)
        em = self._em_px() * TRANS_SCALE      # 翻译字号（≈ em）
        h_t = fm.height()                      # 翻译行高（多行时按它下移）
        p.setFont(font)
        left = area.left()

        # 展开成 (字符, 行号, 行内 x)；行内定位用前缀度量。
        # 字表按行缓存，只有换行/换文本才重算（前缀度量是 O(n²)）。
        st = self._trans_state
        sig = tuple(rows or ())
        if st.get("rows") != sig:
            st["rows"] = sig
            st["items"] = [
                (ch, r, fm.horizontalAdvance(row[:k]),
                 fm.horizontalAdvance(row[:k + 1]))
                for r, row in enumerate(rows or [])
                for k, ch in enumerate(row)
            ]
            st.pop("starts", None)             # 文本/布局变了，飞行记录作废
            st["batch"] = True
        items = st["items"]
        if not items:
            return False

        # 换行 / 往回 seek / 跳段：整场重来；“回填”的字错峰起飞
        t = self._elapsed
        if (st.get("line") != self._cur_index
                or t + 0.05 < st.get("t", 0.0)):
            st["line"] = self._cur_index
            st.pop("starts", None)
            st["batch"] = True
        starts = st.setdefault("starts", {})
        if t - st.get("t", t) > 0.4:          # 往前跳（拖进度条）：也当接手
            st["batch"] = True
        st["t"] = t

        # 判断这次是“自然开唱”还是“中途接手”（seek 进句子中段 / 刚启动就在唱）：
        # 后者要把已经该出现的字直接回拨到各自的进度，否则字会排到“未来”才飞
        # —— 暂停着拖进度条时就会看到整句翻译空着（这是个真 bug）。
        span = TRANS_FILL_LAST - TRANS_FILL_START
        weights = [max(0.1, timing.fill_units(it[0])) for it in items]
        total_w = sum(weights) or 1.0
        if st.get("batch"):
            acc0, ready0 = 0.0, 0
            for wk in weights:
                if f >= TRANS_FILL_START + span * (acc0 / total_w):
                    ready0 += 1
                acc0 += wk
            st["catchup"] = ready0 > 2

        # 收尾：最后一个字也飞完了（或填充早已走完、我们中途才接手）→ 交回整行
        if f >= TRANS_FILL_DONE:
            last = len(items) - 1
            s0 = starts.get(last)
            if s0 is None or t - s0 >= TRANS_MOTION_SEC:
                st["batch"] = False
                st["catchup"] = False
                return False

        # 每个字按“发声量”分配起飞阈值（与主句填充同一套权重，
        # 中英混排、空格不会挤在一起）
        # 每行的 baseline 锚点（中英共用同一条，逐字/整行绘制才不会跳）
        row_asc = [self._trans_ascent(font, row) for row in (rows or [])]
        catchup = st.get("catchup", False)
        n_items = len(items)
        acc = 0.0
        for idx, (ch, r, x0, x1) in enumerate(items):
            wk = weights[idx]
            fk = TRANS_FILL_START + span * (acc / total_w)
            acc += wk
            if f < fk:
                continue                       # 还没轮到它起飞
            s0 = starts.get(idx)
            if s0 is None:
                if catchup:
                    # 中途接手：前面的字已飞得差不多，越靠后越“新”——
                    # 回拨出各自的进度（最后一个字也至少飞了 TRANS_CATCHUP_MIN）
                    back = TRANS_CATCHUP_MIN + (1.0 - TRANS_CATCHUP_MIN) * (
                        (n_items - 1 - idx) / max(1, n_items - 1))
                    s0 = t - TRANS_MOTION_SEC * back
                else:
                    s0 = t                   # 自然开唱：越过阈值即起飞
                starts[idx] = s0
            e = _E_CONVERGE(min(1.0, max(0.0, (t - s0) / TRANS_MOTION_SEC)))
            if ch == " ":
                continue
            x, w = x0, x1 - x0
            # 每个字从不同方向、不同距离出发（确定性伪随机，稳定不跳）
            h1 = ((self._cur_index * 131 + idx * 7919) % 997) / 997.0
            ang = h1 * math.tau
            rad = em * (0.55 + 0.45 * ((idx * 37) % 10) / 10.0)
            dx = math.cos(ang) * rad * (1.0 - e)
            dy = math.sin(ang) * rad * (1.0 - e)
            # 入场起点贴边收进来：向左/上飞的字原本会探出歌词区被裁掉一截
            bx = min(max(left + x + dx, left), area.right() - (w + 2.0))
            by = min(max(y_top + r * h_t + dy, area.top()),
                     area.bottom() - h_t)
            base = by + row_asc[r] if r < len(row_asc) else by
            # “由虚到实”：入场的字用几层微偏移的幽灵描一遍（≈ 方向柔化），
            # 随 e→1 自然归零，不会在动画结束时闪一下
            soft = TRANS_IN_SOFT * (1.0 - e)
            if soft > 0.15:
                p.setPen(QColor(255, 255, 255, int(44.0 * e)))
                for gx, gy in ((-soft, 0.0), (soft, 0.0),
                               (0.0, -soft), (0.0, soft)):
                    p.drawText(QPointF(bx + gx, base + gy), ch)
            p.setPen(QColor(255, 255, 255, int(TRANS_ACTIVE_ALPHA * e)))
            p.drawText(QPointF(bx, base), ch)
        st["batch"] = False
        st["catchup"] = False           # 只对“接手”那一帧生效，之后按自然节奏
        return True

    def _draw_other_line(self, p, area, i, segs, base_pt, y_c):
        """非当前行：模糊位图 + 透明度（仿 AMLL）。

        被滚走的行（焦点上方）只保留紧邻的一行：第二行往上按“滚上去的
        距离”连续淡出——滚动过渡自然，稳定后肉眼看只有一行，不会一路
        排着三行旧歌词。
        """
        op = (self._alpha_cur[i] if i < len(self._alpha_cur)
              else INACTIVE_OPACITY_NEAR)        # 平滑后的亮度（仿 AMLL）
        if i < self._cur_index - 1:
            span = max(1.0, self._spacing)
            r = (self._focus_cy() - y_c) / span   # 连续的上方行数
            if r > 1.6:
                return                        # 已滚走：彻底隐藏
            op *= max(0.0, min(1.0, (1.6 - r) / 0.6))
            if op <= 0.01:
                return
        scale = (self._scale_springs[i].pos
                 if i < len(self._scale_springs) else SCALE_INACTIVE)
        # 非当前行也要“缩到放得下”：位图宽度就是绘制宽度，不缩就会被裁切框硬切
        scale *= self._fit_ratio(("line", i), segs,
                                 max(60.0, self.width() * TEXT_W))
        pm, pad, block_h = self._line_pixmap(i, segs, base_pt, scale)
        # 位图已经在目标缩放下渲染好了：1:1 贴图，不做二次缩放
        # （位图缩放会让像素相位沿线漂移，看起来“逐词模糊不一致”），
        # 位置也对齐到物理像素网格，避免亚像素重采样再糊一层
        dpr = self._dpr
        x = round((area.left() - pad) * dpr) / dpr
        y = round((y_c - (pad + block_h / 2.0)) * dpr) / dpr
        w = pm.width() / dpr               # 物理像素 -> 逻辑坐标
        h = pm.height() / dpr
        p.setOpacity(op)
        # 模糊的光晕可能超出歌词区（左缘最明显：字贴着左边界画），
        # 贴图时把裁剪框按位图留边放宽，不让光晕被切出一条直边；
        # 但**上边不放宽**：向上滚的行不能探进标题/歌手带（会和歌手名重叠）
        p.save()
        p.setClipRect(area.adjusted(-pad, 0.0, pad, pad))
        p.drawPixmap(QRectF(x, y, w, h), pm, QRectF(pm.rect()))
        p.restore()
        p.setOpacity(1.0)

    def _draw_interlude_dots(self, p, area):
        """间奏点：三颗白色圆点，呼吸缩放 + 依次点亮（仿 Apple Music / AMLL）。"""
        if self._dots_snap is None:
            return
        ops, scale, opacity = self._dots_snap
        if opacity <= 0.004:
            return
        d = self._em_px() * 0.3                   # 圆点直径（AMLL：0.3em）
        gap = d * 0.6                             # AMLL：直径:间隙 = 1:0.6
        total_w = d * 3.0 + gap * 2.0
        cx = area.left() + total_w / 2.0
        y = self._dots_spring.pos
        # 点的标称左缘刚好压在歌词区裁剪框上，呼吸/退场放大时会被切掉一点；
        # 画点前把裁剪框向左放宽（看起来像被黑胶边缘截断的那个问题）
        pad = (DOTS_MAX_SCALE - 1.0) * (total_w / 2.0) + 6.0
        p.save()
        p.setClipRect(area.adjusted(-pad, 0.0, pad, pad))   # 上边不放开（见上）
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            alpha = round(255.0 * opacity * ops[i])
            if alpha <= 2:
                continue
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawEllipse(QPointF(cx + (i - 1) * (d + gap) * scale, y),
                          d / 2.0 * scale, d / 2.0 * scale)
        p.restore()

    def _line_pixmap(self, i, segs, base_pt, scale=1.0):
        """取（或生成）某行的模糊位图，返回 (pixmap, pad, 文字块高度)。

        位图直接在目标缩放下渲染（scale 量化到 1%），绘制时 1:1 贴图，
        避免位图缩放的采样相位造成“逐词模糊不一致”。位图里**不带翻译**
        —— 翻译只在当前行实时画（带汇聚入场），前后句只剩原文。
        """
        cur = self._blur_cur[i] if i < len(self._blur_cur) else 0.0
        q = max(0, round(cur * 2.0))            # σ 量化到 0.5 一档（过渡时逐档替换）
        qs = round(scale, 2)                    # 缩放量化到 1%（过渡时逐档替换）
        key = (i, q, qs)                        # 位图不带翻译：翻译只在当前行画
        item = self._blur_cache.get(key)
        if item is not None:
            self._blur_cache.move_to_end(key)
            return item
        item = self._render_line_bitmap(segs, base_pt, "", q / 2.0, qs)
        self._blur_cache[key] = item
        if len(self._blur_cache) > 128:         # 只留可见行附近的，LRU 淘汰
            self._blur_cache.popitem(last=False)
        return item

    def _render_line_bitmap(self, segs, base_pt, trans, sigma, scale=1.0):
        """把一行文字（含翻译）按物理像素画成位图并真高斯模糊。"""
        dpr = self._dpr
        font = self._font(base_pt * scale, heavy=True)   # 非当前行：Black
        fm = QFontMetricsF(font)
        row_h = fm.height()
        widths = [fm.horizontalAdvance(s) for s in segs]
        text_w = max(widths) if widths else 1.0
        block_h = row_h * len(segs)
        trans_h = 0.0
        if trans and self.show_translation:
            trans_h = QFontMetricsF(
                self._font(base_pt * TRANS_SCALE * scale, heavy=True)).height()
        pad = int(max(sigma * 3.0, 6.0)) + 2    # 给高斯扩散留边（逻辑 px）
        w = max(1, int(text_w) + pad * 2)
        h = max(1, int(block_h + trans_h) + pad * 2)
        img = QImage(int(w * dpr), int(h * dpr),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        q.scale(dpr, dpr)                       # 逻辑坐标渲染到物理像素位图
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        q.setFont(font)
        q.setPen(QColor(255, 255, 255, 255))
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for k, seg in enumerate(segs):
            q.drawText(QRectF(pad, pad + k * row_h, text_w + 2, row_h),
                       align, seg)
        if trans_h > 0:
            q.setFont(self._font(base_pt * TRANS_SCALE * scale, heavy=True))
            q.setPen(QColor(255, 255, 255, TRANS_ALPHA))
            q.drawText(QRectF(pad, pad + block_h, text_w + 2, trans_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       trans)
        q.end()
        if sigma > 0.05:
            if _HAS_PIL:
                img = _gaussian_qimage(img, sigma * dpr)   # σ 换算到物理像素
            else:
                k = 1.0 + sigma * BLUR_TEX
                small = img.scaled(max(1, int(img.width() / k)),
                                   max(1, int(img.height() / k)),
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                img = small.scaled(img.width(), img.height(),
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        return QPixmap.fromImage(img), pad, block_h

    def _draw_rows(self, p, area, segs, widths, font, row_h, y0, frac,
                   runs=None, em=0.0, elapsed=0.0):
        """Apple Music 风格：左端对齐；未唱灰白、唱过亮白。

        填充前沿用水平渐变笔做软过渡（AMLL 的 wordFadeWidth：默认
        0.5×行高、以边界为中心）；给了逐词运行段（runs）时，唱到的词
        还会按 AMLL 的 float 动画向上浮 0.05em（ease-out、时长
        max(1s, 词长)）。
        """
        p.setFont(font)
        fm = QFontMetricsF(font)
        dim = QColor(255, 255, 255, ACTIVE_DIM_ALPHA)
        hot = QColor(255, 255, 255, ACTIVE_HOT_ALPHA)
        filled = frac * sum(widths) if frac else 0.0
        fade = max(1.0, row_h * WORD_FADE_W)
        acc = 0.0
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for k, seg in enumerate(segs):
            wseg = widths[k]
            row_y = y0 + k * row_h
            edge = filled - acc                 # 本行内的填充前沿（px）
            row_runs = runs[k] if (runs and k < len(runs)) else None
            if not row_runs:
                # 没有逐词数据（或文本对不上）：整行绘制（原逻辑）
                box = QRectF(area.left(), row_y, wseg, row_h)
                self._draw_run(p, box, seg, edge, wseg, hot, dim, fade,
                               align)
            else:
                # 逐词绘制：每个词按自己的时间向上浮（用前缀度量定位，
                # 与整行绘制的字距一致，避免逐词累积出水平偏移）
                pos = 0
                for text, b, e in row_runs:
                    x = fm.horizontalAdvance(seg[:pos])
                    wr = fm.horizontalAdvance(seg[:pos + len(text)]) - x
                    pos += len(text)
                    dy = 0.0
                    if em > 0.0 and e > b:
                        dur = max(FLOAT_MIN_SEC, e - b)
                        t = (elapsed - b) / dur
                        if t > 0.0:
                            dy = -FLOAT_UP_EM * em * _E_FLOAT(
                                min(1.0, t))
                    box = QRectF(area.left() + x, row_y + dy, wr, row_h)
                    self._draw_run(p, box, text, edge - x, wr, hot, dim,
                                   fade, align)
            acc += wseg

    @staticmethod
    def _draw_run(p, box, text, edge, w_run, hot, dim, fade, align):
        """画一个运行段：按它相对填充前沿的位置选热/暗笔，跨界用渐变软边。"""
        if w_run <= 0 or edge <= 0.0:
            p.setPen(dim)
        elif edge >= w_run:
            p.setPen(hot)
        else:
            bx = box.left() + edge
            g = QLinearGradient(bx - fade * 0.5, 0.0, bx + fade * 0.5, 0.0)
            g.setColorAt(0.0, hot)
            g.setColorAt(1.0, dim)
            p.setPen(QPen(QBrush(g), 0.0))
        p.drawText(box, align, text)

    def _draw_plain(self, p, area):
        f = self._font(max(12.0, self.height() * 0.018), bold=True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        lh = fm.height() * 1.35
        y = area.center().y() - lh * len(self._plain) / 2.0
        for row in self._plain:
            if y > area.bottom():
                break
            if y > area.top() - lh:
                p.setPen(QColor(255, 255, 255, 190))
                p.drawText(QRectF(area.left(), y, area.width(), lh),
                           Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignTop, row)
            y += lh

    # ------------------------------------------------------------------ #
    # 底部控制条
    # ------------------------------------------------------------------ #
    def _draw_bar(self, p):
        if self._bar_t <= 0.02:
            self._buttons = []
            self._progress = None
            return
        w, h = self.width(), self.height()
        bar_w = min(w * 0.88, 1400.0)
        bar_h = max(42.0, min(56.0, h * 0.050))
        x = (w - bar_w) / 2.0
        y = h - bar_h - h * 0.026 + (1.0 - self._bar_t) * (bar_h + h * 0.05)
        cy = y + bar_h / 2.0
        r = max(12.0, bar_h * 0.32)
        self._buttons = []

        p.save()
        p.setOpacity(self._bar_t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_h / 2.0, bar_h / 2.0)

        # ---- 左：三个按钮（一行）----
        cursor = x + 22
        for action, big in (("prev", 1.0), ("toggle", 1.18), ("next", 1.0)):
            br = r * big
            rect = QRectF(cursor, cy - br, br * 2, br * 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawEllipse(rect)
            p.setBrush(QColor(255, 255, 255, 228))
            self._draw_icon(p, rect, action)
            self._buttons.append((rect, action))
            cursor += br * 2 + r * 0.55

        # ---- 右：音量（一行）----
        plus_r = QRectF(x + bar_w - 22 - r * 2, cy - r, r * 2, r * 2)
        num_r = QRectF(plus_r.left() - 46 - 6, cy - r, 46, r * 2)
        minus_r = QRectF(num_r.left() - 8 - r * 2, cy - r, r * 2, r * 2)
        f2 = self._font(max(12.0, bar_h * 0.32))
        for rect, action, label in ((minus_r, "volume_down", "−"),
                                    (plus_r, "volume_up", "+")):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawEllipse(rect)
            p.setPen(QColor(255, 255, 255, 220))
            p.setFont(f2)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            self._buttons.append((rect, action))
        f3 = self._font(max(10.0, bar_h * 0.26))
        p.setFont(f3)
        p.setPen(QColor(255, 255, 255, 175))
        p.drawText(num_r, Qt.AlignmentFlag.AlignCenter,
                   "%d" % self.volume if self.volume >= 0 else "--")

        # ---- 中：进度 + 时间（同一行）----
        left_edge = cursor + r * 0.35
        right_edge = minus_r.left() - 18
        avail = max(60.0, right_edge - left_edge)
        label_w = max(38.0, bar_h * 0.72)
        track_w = max(40.0, avail - label_w * 2 - 16)
        track = QRectF(left_edge + label_w + 8, cy - 3, track_w, 6)
        self._progress = track

        dur = self.duration if self.duration > 0 else 0.0
        ratio = min(1.0, max(0.0, self._pos / dur)) if dur > 0 else 0.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawRoundedRect(track, 3, 3)
        if ratio > 0:
            p.setBrush(QColor(255, 255, 255, 215))
            p.drawRoundedRect(QRectF(track.left(), track.top(),
                                     track.width() * ratio, track.height()), 3, 3)
            kx = track.left() + track.width() * ratio
            p.drawEllipse(QRectF(kx - 6, cy - 6, 12, 12))

        f = self._font(max(9.5, bar_h * 0.23))
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(left_edge, cy - 11, label_w, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._fmt_time(self._pos))
        p.drawText(QRectF(track.right() + 8, cy - 11, label_w, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._fmt_time(dur))
        p.restore()

    def _draw_icon(self, p, rect, action):
        cx, cy = rect.center().x(), rect.center().y()
        s = rect.width() * 0.30
        path = QPainterPath()
        if action == "toggle":
            if self._playing:
                bw = s * 0.42
                p.drawRoundedRect(QRectF(cx - s * 0.55, cy - s * 0.8, bw, s * 1.6),
                                  2, 2)
                p.drawRoundedRect(QRectF(cx + s * 0.13, cy - s * 0.8, bw, s * 1.6),
                                  2, 2)
            else:
                path.moveTo(cx - s * 0.5, cy - s * 0.85)
                path.lineTo(cx + s * 0.85, cy)
                path.lineTo(cx - s * 0.5, cy + s * 0.85)
                path.closeSubpath()
                p.drawPath(path)
        elif action == "next":
            path.moveTo(cx - s * 0.85, cy - s * 0.8)
            path.lineTo(cx + s * 0.35, cy)
            path.lineTo(cx - s * 0.85, cy + s * 0.8)
            path.closeSubpath()
            p.drawPath(path)
            p.drawRoundedRect(QRectF(cx + s * 0.5, cy - s * 0.8, s * 0.32,
                                     s * 1.6), 2, 2)
        elif action == "prev":
            path.moveTo(cx + s * 0.85, cy - s * 0.8)
            path.lineTo(cx - s * 0.35, cy)
            path.lineTo(cx + s * 0.85, cy + s * 0.8)
            path.closeSubpath()
            p.drawPath(path)
            p.drawRoundedRect(QRectF(cx - s * 0.82, cy - s * 0.8, s * 0.32,
                                     s * 1.6), 2, 2)

    @staticmethod
    def _fmt_time(sec):
        sec = max(0, int(sec or 0))
        return "%d:%02d" % (sec // 60, sec % 60)

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def _hit_button(self, pos):
        if self._bar_t < 0.35:
            return None
        for rect, action in self._buttons:
            if rect.contains(pos):
                return action
        return None

    def _lyric_area(self):
        """歌词绘制区域（与 paintEvent 里的一致），用于点击命中测试。"""
        w, h = float(self.width()), float(self.height())
        return QRectF(w * TEXT_X, h * TEXT_TOP, w * TEXT_W, h * TEXT_H)

    def _line_at(self, pos):
        """命中的歌词行 index（点击行 → 跳转到这一句）；没命中返回 None。"""
        if not self._synced or not self._lines or self._spacing <= 0.0:
            return None
        if not self._lyric_area().contains(pos):
            return None
        best, best_d = None, None
        for i in range(min(len(self._lines), len(self._springs))):
            d = abs(pos.y() - self._springs[i].pos)
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is None or best_d > self._spacing * 0.5:
            return None
        return best

    def _seek_to(self, target):
        """跳到指定秒（点击歌词行）：只发这一次指令，界面立即跟手。"""
        if self.duration > 0:
            target = min(max(0.0, target), max(0.0, self.duration - 0.5))
        self._pos_base = target
        self._pos_ts = time.monotonic()
        self._pos = target
        self.player_command.emit("seek", float(target))
        self.update()

    def mousePressEvent(self, event):
        pos = event.position()
        if time.monotonic() - self._shown_at < 0.8:
            return
        action = self._hit_button(pos)
        if action == "toggle":
            self.player_command.emit("toggle", 0.0)
            return
        if action in ("prev", "next"):
            self.player_command.emit(action, 0.0)
            return
        if action == "volume_up":
            self.player_command.emit("volume", float(VOL_STEP))
            return
        if action == "volume_down":
            self.player_command.emit("volume", float(-VOL_STEP))
            return
        if (self._bar_t > 0.35 and self._progress is not None
                and self._progress.adjusted(-10, -18, 10, 18).contains(pos)):
            self._dragging = True
            self._bar_target = 1.0
            self._last_mouse = time.monotonic()
            self._preview_seek(pos.x())
            return
        # 点中歌词某一行 → 跳到这一句的开头（仿 Apple Music / AMLL line-click）
        idx = self._line_at(pos)
        if idx is not None and idx < len(self._times):
            offset = float(self.cfg.get("lyrics_offset_sec", 0.0))
            self._seek_to(self._times[idx] + offset)
            return
        # 点空白处：全屏时退回窗口（不再直接关掉，避免误触）
        if self.isFullScreen():
            self.toggle_fullscreen()

    def mouseDoubleClickEvent(self, event):
        if self._line_at(event.position()) is not None:
            return                     # 歌词行上的双击不切全屏（第一次点击已在跳转）
        self.toggle_fullscreen()

    def contextMenuEvent(self, event):
        m = QMenu(self)
        m.addAction("退出全屏" if self.isFullScreen() else "全屏显示",
                    self.toggle_fullscreen)
        m.addSeparator()
        cur = float(self.cfg.get("lyrics_offset_sec", 0.0))
        sub = m.addMenu("歌词校准（唱得比白字早 → 提前）")
        sub.addAction("提前 0.5s", lambda: self._nudge_offset(-0.5))
        sub.addAction("提前 0.1s", lambda: self._nudge_offset(-0.1))
        sub.addAction("提前 0.05s", lambda: self._nudge_offset(-0.05))
        sub.addAction("延后 0.05s", lambda: self._nudge_offset(+0.05))
        sub.addAction("延后 0.1s", lambda: self._nudge_offset(+0.1))
        sub.addAction("延后 0.5s", lambda: self._nudge_offset(+0.5))
        sub.addSeparator()
        sub.addAction("当前偏移 %+.1fs（点此归零）" % cur,
                      lambda: self._set_offset(0.0))
        m.addSeparator()
        m.addAction("隐藏到托盘", self.close)
        m.exec(event.globalPos())

    def _nudge_offset(self, delta):
        cur = float(self.cfg.get("lyrics_offset_sec", 0.0))
        self._set_offset(cur + delta)

    def _set_offset(self, value):
        self.cfg["lyrics_offset_sec"] = round(max(-5.0, min(5.0, value)), 2)
        self._show_offset_toast()
        self.update()

    def _show_offset_toast(self):
        cur = float(self.cfg.get("lyrics_offset_sec", 0.0))
        tip = "延后" if cur > 0.001 else ("提前" if cur < -0.001 else "归零")
        self._toast_text = "歌词偏移 %+.2f 秒 · %s" % (cur, tip)
        self._toast_until = time.monotonic() + 1.4

    def _draw_toast(self, p):
        """屏幕下方的小提示（歌词校准反馈用），1.4s 后自动淡出。"""
        if not self._toast_text:
            return
        left = self._toast_until - time.monotonic()
        if left <= 0.0:
            return
        alpha = 1.0 if left > 0.35 else max(0.0, left / 0.35)
        f = self._font(max(11.0, self.height() * 0.016))
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(self._toast_text) + 36.0
        h = fm.height() + 18.0
        x = (self.width() - w) / 2.0
        y = self.height() - max(96.0, self.height() * 0.14) - h
        p.save()
        p.setOpacity(alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 205))
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2.0, h / 2.0)
        p.setPen(QColor(255, 255, 255, 235))
        p.setFont(f)
        p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter,
                   self._toast_text)
        p.restore()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.cfg["player_fullscreen"] = False
        else:
            self.showFullScreen()
            self.cfg["player_fullscreen"] = True
        self._layout_w = -1.0
        self.raise_()
        self.activateWindow()

    # 全屏时用无边框窗口，并在 Windows 11 上关掉系统圆角/描边
    # （否则四个角会露出细细的桌面白边）
    def showFullScreen(self):
        if not (self.windowFlags() & Qt.WindowType.FramelessWindowHint):
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        super().showFullScreen()
        self._kill_win_edges()

    def _kill_win_edges(self):
        """Windows 11：给窗口设 DONOTROUND / 无边框色，消掉全屏白边。"""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            pref = ctypes.c_int(1)          # DWMWCP_DONOTROUND
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref),
                                      ctypes.sizeof(pref))
            none = ctypes.c_uint(0xFFFFFFFE)   # DWMWA_COLOR_NONE
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(none),
                                      ctypes.sizeof(none))
        except Exception:
            pass

    def showNormal(self):
        was_frameless = bool(
            self.windowFlags() & Qt.WindowType.FramelessWindowHint)
        if was_frameless:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
        super().showNormal()
        if was_frameless:
            # 重建窗口后恢复全屏前的尺寸位置
            size = self.cfg.get("player_size") or [1100, 700]
            self.resize(int(size[0]), int(size[1]))
            pos = self.cfg.get("player_pos")
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                self.move(int(pos[0]), int(pos[1]))

    def mouseMoveEvent(self, event):
        self._last_mouse = time.monotonic()
        pos = event.position()
        if self._dragging:
            self._preview_seek(pos.x())
            return
        # 鼠标靠近底部 → 控制条像 dock 一样滑上来；离开/静置就沉下去
        h = max(1, self.height())
        self._bar_target = 1.0 if pos.y() > h * 0.74 else 0.0
        self._update_cursor(pos)

    def _update_cursor(self, pos):
        """可点的东西（按钮/进度条/歌词行）上显示手型光标。"""
        hand = self._hit_button(pos) is not None
        if (not hand and self._bar_t > 0.35 and self._progress is not None
                and self._progress.adjusted(-10, -18, 10, 18).contains(pos)):
            hand = True
        if not hand:
            hand = self._line_at(pos) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if hand
                       else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._bar_target = 0.0
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._commit_seek(event.position().x())

    # --- 进度条：拖动时只动界面，松手才发一次指令 ------------------------ #
    def _ratio_at(self, x):
        if self._progress is None or self.duration <= 0:
            return None
        ratio = (x - self._progress.left()) / max(1.0, self._progress.width())
        return min(1.0, max(0.0, ratio))

    def _preview_seek(self, x):
        """拖动中：只把界面挪过去（不发指令，否则音箱会不停重新缓冲）。"""
        ratio = self._ratio_at(x)
        if ratio is None:
            return
        self._pos_base = ratio * self.duration
        self._pos_ts = time.monotonic()
        self._pos = self._pos_base
        self.update()

    def _commit_seek(self, x):
        """松手：只发这一次 Seek。"""
        ratio = self._ratio_at(x)
        if ratio is None:
            return
        target = ratio * self.duration
        self._pos_base = target
        self._pos_ts = time.monotonic()
        self._pos = target
        self.player_command.emit("seek", float(target))
        self.update()
