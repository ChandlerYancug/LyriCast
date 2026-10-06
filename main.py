# -*- coding: utf-8 -*-
"""LyriCast —— 局域网音箱歌词条 / 黑胶播放器（入口）。

    python main.py

流程：发现/连接音箱（Sonos / 通用 UPnP 后端）-> 轮询播放状态 ->
匹配歌词（Apple Music / 网易云 / LRCLIB）-> 悬浮窗 / 全屏黑胶显示

支持的音箱与扩展方式见 docs/BACKENDS.md。
"""

import json
import io
import os
import sys
import threading
import time

from speakers import paths as app_paths   # 只读资源 / 可写数据目录（exe 模式不同）

RES_DIR = app_paths.bundle_dir()          # fonts/、icon.ico 等只读资源
DATA_DIR = app_paths.data_dir()           # config.json / am_token.txt / cache/
CONFIG_PATH = app_paths.config_path()

try:                                  # 中文 Windows 默认 GBK:输出流切 UTF-8
    from utf8mode import ensure_utf8
    ensure_utf8()
except Exception:                     # 极端情况(如只拷了 main.py):别影响启动
    pass


def _check_qt():
    """PyQt6 装坏了（版本不匹配）时给个人话提示，别丢一堆 traceback。"""
    try:
        import PyQt6.QtCore  # noqa: F401
        return True, ""
    except Exception as exc:            # noqa: BLE001
        return False, str(exc)


_qt_ok, _qt_err = _check_qt()
if not _qt_ok:
    try:
        from speakers.http import APP_NAME as _name
    except Exception:
        _name = "LyriCast"
    msg = (
        "PyQt6 无法加载：\n%s\n\n"
        "请打开命令行执行：py -3 -m pip install --upgrade PyQt6\n"
        "（国内网络慢/超时的话加清华镜像："
        "-i https://pypi.tuna.tsinghua.edu.cn/simple）"
    ) % _qt_err
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "%s · 启动失败" % _name, 0x10)
    except Exception:
        pass
    try:
        with io.open(os.path.join(DATA_DIR, "startup_error.log"), "a",
                     encoding="utf-8") as fp:
            fp.write(msg + "\n")
    except Exception:
        pass
    sys.exit(1)

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QInputDialog, QMenu, QMessageBox,
                             QSystemTrayIcon)

import lyrics as lyrics_mod
import relclock
import speakers
import eventing
import cache
from fullscreen import FullscreenView
from overlay import DEFAULT_CJK, DEFAULT_FONT, LyricOverlay

try:
    import mediakeys                 # 仅 Windows：全局媒体键 / 音量键接管
except Exception:                    # 其它平台没有这套 API，功能自动禁用
    mediakeys = None

VOL_KEY_STEP = 2        # 键盘音量键每档调多少（音箱音量 0~100）

DEFAULTS = {
    # ---- 音箱（任何 UPnP/DLNA / Sonos 音箱；HomePod 见 docs/BACKENDS.md）----
    "speaker_type": "auto",          # auto | sonos | upnp（将来：smtc / macos / listen）
    "speaker_host": "",             # 音箱 IP；留空则自动发现
    "speaker_name": "",             # 想固定某台设备时填它的房间名/友好名
    "speaker_location": "",         # 仅 upnp 需要：设备描述 URL
    "font_family": DEFAULT_FONT,          # 拉丁：随包或系统字体（缺失自动回退）
    "cjk_font": DEFAULT_CJK,             # 中文回退：思源黑体 / Noto Sans SC
    "font_size": 26,
    "opacity": 0.96,
    "window_width": 900,
    "window_height": 300,
    "corner_radius": 18,
    "window_mode": "normal",        # normal = 普通窗口(可缩放/可在任务栏) | floating = 无边框悬浮
    "always_on_top": False,          # 普通模式下默认不置顶，和其他窗口一样
    "click_through": False,
    "show_track_info": True,
    "show_translation": True,
    "bg_album_art": True,
    "lyrics_offset_sec": 0.0,
    "vinyl_turn_seconds": 12.0,
    "vinyl_material": "auto",      # 用户上次挑的彩胶（auto=默认经典黑胶；见 vinyl.py）
    "tonearm_skin": "auto",       # 用户上次挑的唱臂（auto=默认碳纤维；见 tonearm.py）
    "song_skins": {},              # 每首歌的皮肤记忆（见 skins.py，自动维护）
    "media_keys": True,
    "volume_keys_speaker": True,     # 键盘音量键接管来调音箱（否则调系统音量）
    "start_view": "player",          # player = 开黑胶播放器；bar = 只开悬浮歌词条
    "player_fullscreen": False,      # 播放器启动时是否全屏
    "player_size": [1100, 700],
    "player_pos": None,
    "provider_order": ["apple", "netease", "lrclib"],
    "apple_storefront": "in",
    "window_position": None,
}


def load_bundled_fonts():
    """把 fonts/ 目录里的字体（SF Pro 等）注册进 Qt，供界面选用。"""
    fonts_dir = app_paths.fonts_dir()
    if not os.path.isdir(fonts_dir):
        return
    for name in sorted(os.listdir(fonts_dir)):
        if name.lower().endswith((".otf", ".ttf", ".ttc")):
            QFontDatabase.addApplicationFont(os.path.join(fonts_dir, name))


def load_config():
    cfg = dict(DEFAULTS)
    raw = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg.update(raw)
        except Exception:
            pass
    # 旧版本配置迁移：sonos_ip / sonos_name -> speaker_host / speaker_name
    # （用户文件里没写 speaker_type 才强制为 sonos，避免把新配置改坏）
    if not cfg.get("speaker_host") and raw.get("sonos_ip"):
        cfg["speaker_host"] = raw["sonos_ip"]
        if "speaker_type" not in raw:
            cfg["speaker_type"] = "sonos"
    if not cfg.get("speaker_name") and raw.get("sonos_name"):
        cfg["speaker_name"] = raw["sonos_name"]
    if "volume_keys_speaker" not in raw and "volume_keys_sonos" in raw:
        cfg["volume_keys_speaker"] = bool(raw["volume_keys_sonos"])
    # 旧默认字体（雅黑）自动升级为苹方，观感更接近 Apple Music
    if str(cfg.get("font_family") or "") in ("", "Microsoft YaHei UI"):
        cfg["font_family"] = DEFAULT_FONT
    # apple 不在歌词源里时补回最前（缺了它就没有官方逐词歌词）
    prov = cfg.get("provider_order")
    if isinstance(prov, list) and "apple" not in prov:
        cfg["provider_order"] = ["apple"] + [p for p in prov if p != "apple"]
    return cfg


def save_config(cfg):
    """写配置时保留文件里已有的其它键（避免旧版本实例把新键抹掉）。"""
    data = {}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    data.update(cfg)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 音箱轮询线程（后端无关：Sonos / DLNA 都走同一套）
# --------------------------------------------------------------------------- #
class SpeakerPoller(QThread):
    track_changed = pyqtSignal(dict)
    position = pyqtSignal(float, bool, bool)   # (秒, 播放中, 是否精确)
    status = pyqtSignal(str)
    volume_changed = pyqtSignal(int)
    lost = pyqtSignal(str)                     # 连续读不到：请上层重新发现设备

    def __init__(self, backend, wake=None, event_server=None, local_ip=""):
        super().__init__()
        self.backend = backend
        self.ip = backend.host
        self.name = backend.name
        self.log = speakers.get_logger("poller")
        self._wake = wake or threading.Event()
        self._event_server = event_server
        self._local_ip = local_ip
        self._subs = {}
        self._sub_ts = 0.0
        self._stop = False
        self._last_key = None
        self._failed = 0
        self._last_status = ""
        self._coord_ts = 0.0
        self._last_pos = -1.0
        self._fast_until = 0.0
        self._volume = -1
        self._vol_tick = 7           # 首次轮询就读一次音量（界面控制条早点显示）
        self._clock = relclock.RelTimeEdgeClock()   # 整秒读数的台阶边沿校准
        self._last_art_url = ""     # 已通知给界面的封面地址
        self._art_emit_ts = 0.0     # 上次封面补发的时间（限速用）

    def stop(self):
        self._stop = True
        self._wake.set()

    # ---- 事件订阅 -------------------------------------------------------- #
    def _subscribe_all(self, force=False):
        """订阅后端给出的事件地址（自节流）。不支持事件的后端直接跳过。"""
        if self._event_server is None or not self._event_server.running:
            return
        now = time.time()
        if not force and now - self._sub_ts < 170.0:
            return
        cb = "http://%s:%d/notify" % (self._local_ip, self._event_server.port)
        try:
            urls = list(self.backend.event_urls() or [])
        except Exception:
            urls = []
        new_subs = {}
        for url in urls:
            old = self._subs.get(url)
            if old:
                try:
                    eventing.renew(url, old)
                    new_subs[url] = old
                    continue
                except Exception:
                    pass
                eventing.unsubscribe(url, old)
            try:
                sid = eventing.subscribe(url, cb)
                if sid:
                    new_subs[url] = sid
            except Exception:
                pass
        self._subs = new_subs
        self._sub_ts = now

    def _refresh_coordinator(self):
        """多房间/立体声时，从机读不到曲目 —— 换成主音箱去读（仅 Sonos 有）。"""
        if not self.backend or speakers.CAN_COORDINATOR not in self.backend.capabilities:
            return
        if time.time() - self._coord_ts < 20.0:
            return
        self._coord_ts = time.time()
        try:
            got = self.backend.coordinator()
        except Exception:
            return
        if not got:
            return
        host, cname = got
        if not host or host == self.backend.host:
            return
        try:
            self.backend = speakers.open_backend(
                self.backend.kind, host, name=cname or self.backend.name)
        except Exception:
            return
        self.ip = host
        self._last_key = None
        self._subs = {}                 # 换了设备，订阅要重建
        self.log.info("跟随主音箱：%s（%s）", cname or "", host)
        self.status.emit("已跟随主音箱：%s（%s）" % (cname or "", host))

    def _track_transition(self, info):
        """判断本次轮询相比上一帧发生了什么：

        返回 'track'（换了曲目）/ 'art'（同曲但封面地址刚就绪）/ None。

        AirPlay 投送时 Sonos 的专辑封面地址往往比曲名/歌手晚一两拍才
        就绪，而轮询去重只看曲名/歌手/专辑/URI——晚到的封面永远不会触发
        曲目变化，封面就一直空着（退出重进反而正常，因为启动首帧
        封面已经就绪）。这里把“同一首歌里封面地址从无到有/变化”也当作
        一次事件补发给界面（地址反复抖动时限速 1.5s；被限速的地址
        不会标记为已发，超出限速窗口后仍会发出去）。
        """
        key = (info["title"], info["artist"], info["album"], info["uri"])
        art_url = info.get("album_art") or ""
        if key != self._last_key:
            self._last_key = key
            self._last_art_url = art_url
            self._art_emit_ts = time.time()
            return "track"
        if art_url and art_url != self._last_art_url:
            now = time.time()
            if not self._last_art_url or now - self._art_emit_ts > 1.5:
                self._last_art_url = art_url
                self._art_emit_ts = now
                return "art"
        return None

    def _now_playing_dict(self):
        """后端返回的 NowPlaying 转成界面/歌词管线用的 dict。

        原始字段（如 meta_xml）一并带上，右键菜单导出排查信息时靠它。
        """
        np = self.backend.now_playing()
        d = {
            "title": np.title,
            "artist": np.artist,
            "album": np.album,
            "album_art": np.album_art,
            "position": np.position,
            "duration": np.duration,
            "uri": np.uri,
            "state": np.state,
        }
        if np.raw:
            d.update(np.raw)
        return d

    def run(self):
        self._subscribe_all(force=True)
        while not self._stop:
            self._refresh_coordinator()
            self._subscribe_all()
            try:
                info = self._now_playing_dict()
            except Exception as exc:
                self._failed += 1
                if self._failed in (1, 5):
                    self.status.emit("连接音箱失败，正在重试…")
                if self._failed in (10, 70, 190):
                    # 连了十几次还不行：多半是设备重启/换 IP 了，
                    # 让上层重新发现（而不是原地重试到天荒）
                    self.log.warning("连续 %d 次读不到状态（%r），请重新发现设备",
                                     self._failed, exc)
                    self.lost.emit("与音箱失去联系，正在重新查找…")
                elif self._failed <= 5:
                    self.log.debug("读状态失败（第 %d 次）：%r", self._failed, exc)
                self.msleep(2000)
                continue

            self._failed = 0
            state = info.get("state") or ""

            pos = float(info.get("position") or 0.0)
            jump = self._last_pos >= 0 and abs(pos - self._last_pos) > 1.5
            if jump:
                # 拖进度条后进入 2 秒“快速追赶”，尽快跟上真实位置
                self._fast_until = time.time() + 2.0
            self._last_pos = pos

            if not info["title"] and not info["artist"]:
                # 读不到曲目：告诉用户到底发生了什么，方便判断
                msg = "未读到曲目信息"
                if state:
                    msg += "（状态：%s）" % state
                if state in ("PLAYING", "TRANSITIONING"):
                    msg += ("\n正在播放但元数据为空：可能是投送（AirPlay / 蓝牙）"
                            "或设备把曲目信息放到了私有接口里")
                else:
                    msg += "\n先在音箱 App 里播一首歌试试"
                if msg != self._last_status:
                    self._last_status = msg
                    self.status.emit(msg)
            else:
                self._last_status = ""
                if self._track_transition(info):
                    self.track_changed.emit(info)
            if state in ("PLAYING", "TRANSITIONING"):
                playing = True
            elif state in ("PAUSED_PLAYBACK", "STOPPED", "NO_MEDIA_PRESENT"):
                playing = False
            else:
                playing = True

            # 跳转/缓冲中（TRANSITIONING）音箱报的位置不可信：
            # 这几帧喂给界面会让歌词高亮来回抖 —— 索性不喂，等它稳定
            if state != "TRANSITIONING":
                # 台阶边沿时钟：把整秒读数校准成精确位置（直接采信）
                pos_cal, precise = self._clock.update(
                    info["position"], playing, time.monotonic())
                self.position.emit(pos_cal, playing, precise)

            # 捎带看一眼音量（约 2 秒一次），供全屏控制条显示
            self._vol_tick += 1
            if self._vol_tick % 8 == 0:
                try:
                    vol = self.backend.get_volume()
                    if vol >= 0 and vol != self._volume:
                        self._volume = vol
                        self.volume_changed.emit(vol)
                except Exception:
                    pass

            fast = time.time() < self._fast_until or state == "TRANSITIONING"
            # 平时 263ms 一次（刻意避开 250ms：与 1 秒的整秒读数整除会
            # 让采样相位锁定，边沿估计变成固定偏差；263ms 让相位逐圈漂移，
            # 多个边沿平均后误差趋于零）。拖进度条后的追赶期 70ms 一次；
            # 一旦收到音箱的事件推送，立刻醒来查一次（这就是“瞬时”的来源）
            self._wake.wait((70 if fast else 263) / 1000.0)
            self._wake.clear()


# --------------------------------------------------------------------------- #
# 歌词抓取任务
# --------------------------------------------------------------------------- #
class _TaskSignals(QObject):
    done = pyqtSignal(int, object, object)   # seq, result, art_bytes


class LyricsTask(QRunnable):
    def __init__(self, seq, info, providers, force=False):
        super().__init__()
        self.signals = _TaskSignals()
        self.seq = seq
        self.info = info
        self.providers = providers
        self.force = force

    def run(self):
        title = self.info.get("title", "") or ""
        artist = self.info.get("artist", "") or ""
        album = self.info.get("album", "") or ""
        duration = self.info.get("duration") or 0.0

        # ---- 歌词：先查本地缓存 ----
        result = None
        hit = False
        if not self.force:
            cached = cache.load_lyrics(title, artist, album, duration)
            if cached is not None:
                result = cached or None      # {} 表示“之前就没找到”
                hit = True
        if not hit:
            try:
                result, had_error = lyrics_mod.fetch_ex(
                    title, artist, album, duration or None,
                    providers=tuple(self.providers),
                )
            except Exception:
                result, had_error = None, True
            # 只有“确实搜了、确实没有”才缓存；网络出错不写，避免污染
            if result is not None or not had_error:
                cache.save_lyrics(title, artist, album, duration, result)

        # ---- 封面：同样先查缓存 ----
        art = None
        if not self.force:
            art = cache.load_art(title, artist, album)
        if not art:
            # 后端直接给的封面（SMTC 缩略图是内存 bytes，没有 URL）
            art = self.info.get("art_bytes") or None
        if not art:
            try:
                art = speakers.fetch_album_art(self.info.get("album_art", ""))
            except Exception:
                art = None
            if art:
                cache.save_art(title, artist, album, art)

        # 退出时任务可能还在跑：信号对象已销毁就安静收尾（别刷 traceback）
        try:
            self.signals.done.emit(self.seq, result, art)
        except RuntimeError:
            pass


class _ArtSignals(QObject):
    done = pyqtSignal(int, object)          # seq, art_bytes


class ArtTask(QRunnable):
    """轻量封面补抓：同一首歌的封面地址晚到（AirPlay 常见）时用。"""

    def __init__(self, seq, info):
        super().__init__()
        self.signals = _ArtSignals()
        self.seq = seq
        self.info = info

    def run(self):
        title = self.info.get("title", "") or ""
        artist = self.info.get("artist", "") or ""
        album = self.info.get("album", "") or ""
        art = cache.load_art(title, artist, album)   # 命中缓存就不发网络请求
        if not art:
            art = self.info.get("art_bytes") or None
        if not art:
            try:
                art = speakers.fetch_album_art(self.info.get("album_art", ""))
            except Exception:
                art = None
            if art:
                cache.save_art(title, artist, album, art)
        if art:
            try:
                self.signals.done.emit(self.seq, art)
            except RuntimeError:            # 退出时对象已销毁，忽略
                pass


class _Bridge(QObject):
    devices = pyqtSignal(list)
    token_done = pyqtSignal(str, str)        # (凭证, 多行说明)


# --------------------------------------------------------------------------- #
# 主程序
# --------------------------------------------------------------------------- #
class LyriCastApp(QObject):
    volume_signal = pyqtSignal(int)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.log = speakers.get_logger("app")
        self.cfg = load_config()

        self.overlay = LyricOverlay(self.cfg)
        self.fullscreen = FullscreenView(self.cfg)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(3)

        self.poller = None
        self.seq = 0
        self.current_track = None
        self._tasks = set()          # 保持 QRunnable 引用，防止信号对象被回收
        self._last_lyrics = None     # 当前歌词结果（开全屏时要用）
        self._apple_hint_shown = False   # “配 Apple 凭证”只提示一次
        self._token_busy = False         # 正在后台读浏览器 cookie
        self._last_art = None        # 当前封面 bytes
        self._art_key = None         # 当前封面对应的曲目（补抓去重用）
        self._overlay_was_visible = True
        self._ignore_pos_until = 0.0  # seek 后短暂忽略在途旧读数
        self._discover_purpose = "connect"   # connect = 自动连上；pick = 只填充托盘菜单
        self._last_lost_ts = 0.0             # 失联重连的节流
        self._retry_timer = None             # 找不到设备时的重试定时器

        # UPnP 事件订阅（让 seek / 换歌瞬间就能同步）
        self._wake = threading.Event()
        self._event_server = eventing.EventServer()
        self._event_announced = False

        self.bridge = _Bridge()
        self.bridge.devices.connect(self._on_devices)
        self.bridge.token_done.connect(self._on_token_done)

        self.overlay.request_relyrics.connect(self.relyrics)
        self.overlay.request_fullscreen.connect(self._open_fullscreen)
        self.overlay.request_dump.connect(self._dump_track)
        self.overlay.request_quit.connect(self.quit)
        self.fullscreen.closed.connect(self._on_fullscreen_closed)
        self.fullscreen.player_command.connect(self._on_player_command)
        self.volume_signal.connect(self._on_volume)

        self.media_keys = None
        self._setup_media_keys()

        # 音量键 → Sonos 音量（拦键盘音量键，聚合后发指令）
        self.volume_hook = None
        self._vol_pending = 0
        self._vol_timer = QTimer(self)
        self._vol_timer.setSingleShot(True)
        self._vol_timer.setInterval(170)
        self._vol_timer.timeout.connect(self._flush_volume)
        self._setup_volume_hook()

        self._build_tray()

    # ---- 托盘 ----------------------------------------------------------- #
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._make_icon(), self.app)
        self.tray.setToolTip(speakers.APP_NAME)
        menu = QMenu()
        menu.addAction("显示 / 隐藏歌词条", self._toggle_visible)
        menu.addAction("打开黑胶播放器", lambda: self._show_player())
        menu.addAction("播放器：全屏 / 窗口 切换", self._toggle_player_fullscreen)
        menu.addAction("重新搜索歌词", self.relyrics)
        menu.addAction("Apple Music 凭证（逐词/翻译）…", self._show_apple_token_help)
        menu.addAction("清空歌词/封面缓存", self._clear_cache)
        menu.addAction("导出当前曲目信息（排查用）", self._dump_track)
        menu.addSeparator()
        menu.addAction("重新连接音箱", self.reconnect)
        self.speaker_menu = QMenu("选择音箱", menu)
        self._populate_speaker_menu([])
        menu.addMenu(self.speaker_menu)
        menu.addAction("搜索音箱设备…", self._search_devices)
        menu.addAction("重新发现（忽略已保存设备）", self._rediscover)
        menu.addAction("手动输入音箱 IP…", self._enter_speaker_ip)
        menu.addAction("HomePod / AirPlay 搜不到？", self._open_homepod_docs)
        menu.addSeparator()
        menu.addAction("黑胶转速 慢一点", lambda: self._nudge_vinyl(+3.0))
        menu.addAction("黑胶转速 快一点", lambda: self._nudge_vinyl(-3.0))
        menu.addAction("换一张彩胶", self._cycle_vinyl)
        menu.addAction("换一支唱臂", self._cycle_tonearm)
        menu.addSeparator()
        mk = menu.addAction("多媒体键控制音箱（全局）")
        mk.setCheckable(True)
        mk.setChecked(bool(self.cfg.get("media_keys", True)))
        mk.triggered.connect(self._toggle_media_keys)
        vk = menu.addAction("音量旋钮控制音箱（键盘音量键）")
        vk.setCheckable(True)
        vk.setChecked(bool(self.cfg.get("volume_keys_speaker", True)))
        vk.triggered.connect(self._toggle_volume_keys)
        menu.addSeparator()
        auto = menu.addAction("开机自启")
        auto.setCheckable(True)
        auto.setChecked(os.path.exists(self._autostart_path()))
        auto.triggered.connect(self._toggle_autostart)
        menu.addSeparator()
        menu.addAction("打开日志文件夹", self._open_logs)
        menu.addAction("查看运行日志（记事本）", self._open_log_file)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._toggle_visible()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    @staticmethod
    def _make_icon():
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30, 215, 96))
        p.drawEllipse(4, 4, 56, 56)
        f = QFont()
        f.setPointSize(30)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(20, 20, 22))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "词")
        p.end()
        return QIcon(pm)

    def _toggle_visible(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()

    # ---- 启动 ----------------------------------------------------------- #
    def start(self):
        if (self.cfg.get("start_view") or "player").lower() == "bar":
            self.overlay.show()
        else:
            self._show_player(
                fullscreen=bool(self.cfg.get("player_fullscreen", False)))
        QTimer.singleShot(150, self.reconnect)

    def reconnect(self):
        if self._retry_timer is not None:
            self._retry_timer.stop()
            self._retry_timer = None
        if self.poller is not None:
            self.poller.stop()
            self.poller.wait(1500)
            self.poller = None

        backend = self._open_configured_backend()
        if backend is not None:
            self._start_poller(backend)
            return

        self.overlay.set_status("正在搜索局域网内的音箱…")
        self._discover_purpose = "connect"
        threading.Thread(target=self._discover_worker, daemon=True).start()

    def _schedule_retry(self, delay_ms=15000):
        """找不到设备时定期重试（音箱开机晚于电脑是常见场景）。"""
        if self._retry_timer is None:
            self._retry_timer = QTimer(self)
            self._retry_timer.setSingleShot(True)
            self._retry_timer.timeout.connect(self._retry_connect)
        self._retry_timer.start(delay_ms)

    def _retry_connect(self):
        if self.poller is None:
            self.log.info("自动重试：重新搜索音箱")
            self.reconnect()

    def _open_configured_backend(self):
        """按配置直接连接（不搜索）；没配或连不上返回 None。"""
        kind = (self.cfg.get("speaker_type") or "auto").strip().lower()
        name = self.cfg.get("speaker_name") or ""
        loc = self.cfg.get("speaker_location") or ""
        if kind == "smtc":                 # 本机媒体会话：没有 IP
            try:
                return speakers.open_backend("smtc", "", name=name)
            except Exception as exc:
                self.log.warning("SMTC 后端不可用：%r", exc)
                self.overlay.set_status("本机媒体会话不可用：%s" % (exc,))
                return None
        host = (self.cfg.get("speaker_host") or "").strip()
        if not host:
            return None
        kinds = [kind] if kind in ("sonos", "upnp") else ["sonos", "upnp"]
        last = None
        for k in kinds:
            try:
                return speakers.open_backend(k, host, name=name, location=loc)
            except Exception as exc:
                last = exc
        self.log.warning("连接音箱失败（%s %s）：%r", kind, host, last)
        self.overlay.set_status("连接音箱失败（%s）：%s\n正在重新搜索…" % (kind, last))
        return None

    def _discover_worker(self):
        try:
            devices = speakers.discover(3.0)
            self.log.info("SSDP 发现 %d 台设备：%s", len(devices),
                          ", ".join("%s[%s]" % (d.get("name") or d.get("ip"),
                                              d.get("kind")) for d in devices))
            if not devices:
                self.log.warning(
                    "SSDP 没发现任何设备（本机防火墙 / VPN、Clash 等 TUN 代理、"
                    "路由器 AP 隔离都会导致）；可托盘菜单「手动输入音箱 IP…」直连")
        except Exception as exc:
            self.log.warning("设备发现失败：%r", exc)
            devices = []
        try:
            self.bridge.devices.emit(devices)
        except RuntimeError:
            pass

    # ---- 音箱选择器 ------------------------------------------------------ #
    def _search_devices(self):
        """托盘菜单：只搜索并填充菜单，不自动连接。"""
        self._discover_purpose = "pick"
        self.overlay.set_status("正在搜索音箱设备…")
        threading.Thread(target=self._discover_worker, daemon=True).start()

    def _populate_speaker_menu(self, devices):
        m = getattr(self, "speaker_menu", None)
        if m is None:
            return
        m.clear()
        cur_kind = (self.cfg.get("speaker_type") or "").lower()
        cur_host = (self.cfg.get("speaker_host") or "").strip()
        if "smtc" in speakers.backend_kinds():
            act = m.addAction("本机媒体会话（电脑在放歌时用）")
            act.setCheckable(True)
            act.setChecked(cur_kind == "smtc")
            act.triggered.connect(lambda: self._choose_smtc())
            m.addSeparator()
        if devices:
            for d in devices:
                # 同名设备（立体声/多房间常这样）用 IP 区分
                label = "%s（%s %s）" % (d.get("name") or d.get("ip"),
                                          d.get("kind"), d.get("ip"))
                act = m.addAction(label)
                act.setCheckable(True)
                act.setChecked(d.get("ip") == cur_host
                               and d.get("kind") == cur_kind)
                act.triggered.connect(
                    lambda _checked=False, dev=d: self._choose_device(dev))
        else:
            act = m.addAction("（还没搜索到设备）")
            act.setEnabled(False)
        m.addSeparator()
        m.addAction("搜索设备…", self._search_devices)

    def _choose_device(self, dev):
        """用户从托盘里指定了一台音箱：存进配置并连上去。"""
        self.cfg["speaker_type"] = dev.get("kind") or "upnp"
        self.cfg["speaker_host"] = dev["ip"]
        self.cfg["speaker_name"] = dev.get("name", "")
        self.cfg["speaker_location"] = dev.get("location", "")
        save_config(self.cfg)
        self.log.info("选定音箱：%s（%s %s）", dev.get("name"),
                      dev.get("kind"), dev["ip"])
        self.reconnect()

    def _choose_smtc(self):
        """用户选了“本机媒体会话”后端。"""
        self.cfg["speaker_type"] = "smtc"
        self.cfg["speaker_host"] = ""
        self.cfg["speaker_name"] = "本机媒体会话"
        self.cfg["speaker_location"] = ""
        save_config(self.cfg)
        self.log.info("选定后端：本机媒体会话（SMTC）")
        self.reconnect()

    def _enter_speaker_ip(self):
        """托盘菜单：SSDP 被防火墙 / VPN 拦住时，直接输入音箱 IP 连接。

        完全绕过搜索：Sonos 走 1400 端口；DLNA 会自动在常见端口/路径
        里猜设备描述地址（见 discovery.find_description）。
        """
        text, ok = QInputDialog.getText(
            None, "%s · 手动连接音箱" % speakers.APP_NAME,
            "输入音箱的 IP 地址（如 192.168.1.20）：\n"
            "· Sonos：App 里「设置 → 系统 → 关于我的系统」\n"
            "· 其它音箱：路由器管理页的设备列表里看")
        if not ok:
            return
        host = (text or "").strip()
        if not host:
            return
        self.cfg["speaker_host"] = host
        self.cfg["speaker_type"] = "auto"
        self.cfg["speaker_location"] = ""
        self.cfg["speaker_name"] = ""
        save_config(self.cfg)
        self.log.info("手动指定音箱 IP：%s", host)
        self.reconnect()

    def _open_logs(self):
        """托盘菜单：打开日志文件夹（提 issue 时要发的东西在这里）。"""
        path = speakers.log_dir()
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)          # noqa: S606  （用户主动点的）
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self.overlay.set_status("打开日志目录失败：%r\n%s" % (exc, path))

    # ---- 两个新手最容易卡住的点的入口（都放在托盘里，不用去翻文档）---- #
    def _open_homepod_docs(self):
        """托盘菜单：HomePod / AirPlay 为什么搜不到、怎么办。"""
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(
                "https://github.com/ChandlerYancug/LyriCast/"
                "blob/main/docs/BACKENDS.md"))
        except Exception as exc:
            self.overlay.set_status("打开说明失败：%r" % (exc,))

    def _show_apple_token_help(self):
        """托盘菜单：逐词歌词 / 翻译需要配置 Apple Music 凭证。"""
        box = QMessageBox()
        box.setWindowTitle("%s · Apple Music 凭证" % speakers.APP_NAME)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "想要逐词歌词和中文翻译，需要配置一次 Apple Music 凭证。\n\n"
            "点「自动获取」→ 从浏览器里读出凭证\n"
            "（浏览器需先登录 music.apple.com）；\n"
            "读不到时会给出手动复制的步骤。\n\n"
            "没有凭证也能用，只是没有逐词高亮和翻译（退回普通歌词）。")
        box.setDetailedText(
            "手动步骤：\n"
            "1. 浏览器登录 https://music.apple.com（保持登录）；\n"
            "2. F12 → Application → Cookies → https://music.apple.com\n"
            "   → 复制 media-user-token 的值；\n"
            "3. 存成项目目录下的 am_token.txt（整个文件就这一行）；\n"
            "4. 重启本程序。\n\n"
            "凭证有效期几个月，过期后重做一次即可。")
        auto_btn = box.addButton("自动获取（推荐）",
                                 QMessageBox.ButtonRole.AcceptRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is auto_btn:
            self._fetch_apple_token()

    def _fetch_apple_token(self):
        """后台线程里从浏览器读凭证（全程在应用内，不弹命令行窗口）。"""
        if self._token_busy:
            return
        self._token_busy = True
        self.log.info("从浏览器读取 Apple 凭证…")
        try:
            self.tray.showMessage(
                speakers.APP_NAME, "正在从浏览器读取 Apple Music 凭证…",
                QSystemTrayIcon.MessageIcon.Information, 4000)
        except Exception:
            pass

        def work():
            try:
                import apple_music
                token, logs = apple_music.find_browser_token()
            except Exception as exc:      # 导入/解密失败都归到“没拿到”
                token, logs = "", ["读取失败：%r" % (exc,)]
            try:
                self.bridge.token_done.emit(token, "\n".join(logs))
            except RuntimeError:          # 退出时信号对象已销毁
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_token_done(self, token, logs):
        """后台取凭证结束：成功就保存并重抓歌词，失败给手动步骤。"""
        self._token_busy = False
        import apple_music
        if token and apple_music.save_user_token(token):
            self._apple_hint_shown = True
            self.log.info("Apple 凭证已更新（%d 字符）", len(token))
            QMessageBox.information(
                None, "Apple Music 凭证",
                "已找到并保存凭证。\n\n%s\n\n马上重新抓歌词…" % logs)
            self.relyrics()
        else:
            self.log.warning("取 Apple 凭证失败：%s",
                             (logs or "").replace("\n", " | "))
            QMessageBox.warning(
                None, "Apple Music 凭证",
                "没拿到凭证。\n\n%s\n\n"
                "可以按「详细说明」里的步骤在浏览器里手动复制\n"
                "media-user-token，在「手动粘贴」里保存。" % (logs or "",))

    def _open_log_file(self):
        """托盘菜单：直接打开最新日志（Windows 用记事本；别处用默认程序）。"""
        path = speakers.log_path()
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(["notepad.exe", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self.overlay.set_status("打开日志失败：%r\n%s" % (exc, path))

    def _on_speaker_lost(self, msg):
        """连续读不到音箱：重新发现（节流，避免设备真关机时反复搜索）。"""
        now = time.monotonic()
        if now - self._last_lost_ts < 30.0:
            return
        self._last_lost_ts = now
        self.log.warning("音箱失联：%s", msg)
        self.overlay.set_status(msg + "\n（音箱可能重启/换了 IP；先按配置重连，再自动搜索）")
        self.reconnect()

    def _on_devices(self, devices):
        # 无论哪种目的，先把托盘菜单填上（换设备时直接点）
        self._populate_speaker_menu(devices)
        if self._discover_purpose == "pick":
            if devices:
                self.overlay.set_status("发现 %d 台音箱：托盘菜单 → 选择音箱"
                                        % len(devices))
            return
        if not devices:
            self.overlay.set_status(
                "未发现音箱设备（同一 Wi-Fi 也搜不到？多半是本机被拦了）：\n"
                "· Windows 防火墙弹窗要点「允许」；VPN / Clash 的 TUN 模式先关\n"
                "· 托盘菜单 →「手动输入音箱 IP…」可以完全绕过搜索直接连\n"
                "· HomePod / 纯 AirPlay 搜不到是正常的（托盘里有说明）"
            )
            self._schedule_retry(15000)
            return
        want = (self.cfg.get("speaker_name") or "").strip()
        picked = None
        if want:
            for d in devices:
                if d.get("name") == want:
                    picked = d
                    break
        if picked is None:
            picked = devices[0]
        self.cfg["speaker_type"] = picked.get("kind") or "upnp"
        self.cfg["speaker_host"] = picked["ip"]
        self.cfg["speaker_name"] = picked.get("name", "")
        self.cfg["speaker_location"] = picked.get("location", "")
        save_config(self.cfg)
        self.log.info("自动连接：%s（%s %s）", picked.get("name"),
                      picked.get("kind"), picked["ip"])
        self.overlay.set_status("已连接：%s" % picked.get("name", picked["ip"]))
        try:
            backend = speakers.open_backend(
                self.cfg["speaker_type"], picked["ip"],
                name=picked.get("name", ""), location=picked.get("location", ""))
        except Exception as exc:
            self.log.warning("打开音箱失败：%r", exc)
            self.overlay.set_status("打开音箱失败：%s" % (exc,))
            self._schedule_retry(15000)
            return
        self._start_poller(backend)

    def _start_poller(self, backend):
        local_ip = eventing.local_ip_for(backend.host)
        if not self._event_server.running:
            if self._event_server.start(self._on_upnp_event):
                self._event_announced = False
                self.overlay.set_status(
                    "正在启用实时事件监听…\n若弹出防火墙提示，请勾选“专用网络”并允许"
                )
        self.poller = SpeakerPoller(backend, self._wake,
                                    self._event_server, local_ip)
        self.poller.track_changed.connect(self._on_track)
        self.poller.position.connect(self._on_position)
        self.poller.status.connect(self.overlay.set_status)
        self.poller.volume_changed.connect(self._on_volume)
        self.poller.lost.connect(self._on_speaker_lost)
        self.poller.start()
        self.log.info("已启动轮询：%r（能力：%s）", backend,
                      ", ".join(sorted(backend.capabilities)))

    def _rediscover(self):
        """托盘菜单：忽略已保存的设备，重新搜索（换音箱时用）。"""
        self.log.info("用户请求：忽略已保存设备，重新发现")
        self.cfg["speaker_host"] = ""
        self.cfg["speaker_name"] = ""
        self.cfg["speaker_location"] = ""
        self.cfg["speaker_type"] = "auto"
        self._populate_speaker_menu([])
        save_config(self.cfg)
        self.reconnect()

    def _on_upnp_event(self, sid, body):
        """收到音箱推送（在 HTTP 线程里）—— 立刻唤醒轮询线程去查真实位置。"""
        self._wake.set()
        if not self._event_announced:
            self._event_announced = True
            try:
                hints = eventing.parse_last_change(body)
                state = hints.get("TransportState", "")
                self.overlay.set_status("已启用实时事件推送 ✅"
                                        + ("（%s）" % state if state else ""))
            except Exception:
                pass

    def _on_position(self, seconds, playing, precise=False):
        if time.monotonic() < self._ignore_pos_until:
            return                       # seek 后：等 Sonos 报出新位置再更新
        self.overlay.set_position(seconds, playing, precise)
        self.fullscreen.set_position(seconds, playing, precise)

    def _on_volume(self, vol):
        self.fullscreen.set_volume(vol)

    def _on_player_command(self, action, value):
        """用户在播放器界面上操作了 —— 在后台线程转发给音箱，不卡界面。"""
        if self.poller is None:
            return
        be = self.poller.backend
        need = {"toggle": speakers.CAN_CONTROL, "next": speakers.CAN_CONTROL,
                "prev": speakers.CAN_CONTROL, "seek": speakers.CAN_SEEK,
                "seek_rel": speakers.CAN_SEEK, "volume": speakers.CAN_VOLUME,
                "mute": speakers.CAN_VOLUME}
        cap = need.get(action)
        if cap and cap not in be.capabilities:
            self.overlay.set_status("当前音箱后端不支持这个操作")
            return
        if action in ("seek", "seek_rel"):
            # 刚发起 seek：0.8s 内忽略在途的旧位置读数，避免歌词闪回
            self._ignore_pos_until = time.monotonic() + 0.8
        wake = self._wake
        emit_vol = self.volume_signal.emit

        def run():
            try:
                if action == "toggle":
                    state = be.get_transport_state()
                    if state == "PLAYING":
                        be.pause()
                    else:
                        be.play()
                elif action == "next":
                    be.next_track()
                elif action == "prev":
                    be.previous_track()
                elif action == "seek":
                    be.seek(value)
                elif action == "seek_rel":
                    info = be.now_playing()
                    be.seek(max(0.0, float(info.position) + value))
                elif action == "volume":
                    cur = be.get_volume()
                    if cur < 0:
                        cur = 20
                    vol = be.set_volume(cur + int(value))
                    emit_vol(vol)
                elif action == "mute":
                    be.toggle_mute()
            except Exception:
                pass
            wake.set()               # 操作完立刻刷新一次状态

        threading.Thread(target=run, daemon=True).start()

    def _show_player(self, fullscreen=None):
        """显示黑胶播放器（窗口 或 全屏），并把当前状态一次性推过去。"""
        fs = self.fullscreen
        if self.current_track:
            fs.set_track(self.current_track)
            fs.set_album_art_bytes(self._last_art)
            if self._last_lyrics is not None:
                fs.set_lyrics(self._last_lyrics)
        if fullscreen is None:
            fullscreen = bool(self.cfg.get("player_fullscreen", False))
        if fullscreen:
            fs.showFullScreen()
        else:
            size = self.cfg.get("player_size") or [1100, 700]
            fs.resize(int(size[0]), int(size[1]))
            pos = self.cfg.get("player_pos")
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                fs.move(int(pos[0]), int(pos[1]))
            else:
                scr = fs.screen()
                if scr is not None:
                    geo = scr.availableGeometry()
                    fs.move(geo.center().x() - fs.width() // 2,
                            geo.center().y() - fs.height() // 2)
            fs.show()
        self.cfg["player_fullscreen"] = bool(fullscreen)
        fs.raise_()
        fs.activateWindow()

    def _toggle_player_fullscreen(self):
        if self.fullscreen.isVisible():
            self.fullscreen.toggle_fullscreen()
        else:
            self._show_player(fullscreen=True)

    def _open_fullscreen(self):
        self._overlay_was_visible = self.overlay.isVisible()
        if self._overlay_was_visible:
            self.overlay.hide()
        self._show_player(fullscreen=True)

    def _on_fullscreen_closed(self):
        if self._overlay_was_visible:
            self.overlay.show()

    # ---- 开机自启 / 快捷方式（仅 Windows） ------------------------------- #
    @staticmethod
    def _autostart_path():
        appdata = os.environ.get("APPDATA")
        if sys.platform != "win32" or not appdata:
            return ""
        return os.path.join(
            appdata,
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
            "%s.lnk" % speakers.APP_NAME,
        )

    def _toggle_autostart(self, checked):
        path = self._autostart_path()
        if not path:
            self.overlay.set_status("开机自启目前只支持 Windows")
            return
        if checked:
            create_app_shortcut(path)
        else:
            try:
                os.remove(path)
            except OSError:
                pass

    def _nudge_vinyl(self, delta):
        """黑胶转速：值 = 转一圈的秒数，越大越慢。"""
        cur = float(self.cfg.get("vinyl_turn_seconds", 12.0))
        self.cfg["vinyl_turn_seconds"] = max(4.0, min(40.0, cur + delta))
        save_config(self.cfg)

    def _cycle_vinyl(self):
        """换一张彩胶：写进配置 + 记住这首歌（下次放这首还是它）。"""
        if not self.fullscreen.isVisible():
            self._show_player()
        self.fullscreen.cycle_material()
        save_config(self.cfg)

    def _cycle_tonearm(self):
        """换一支唱臂：写进配置 + 记住这首歌（下次放这首还是它）。"""
        if not self.fullscreen.isVisible():
            self._show_player()
        self.fullscreen.cycle_tonearm()
        save_config(self.cfg)

    # ---- 全局多媒体键（仅 Windows） ------------------------------------- #
    def _setup_media_keys(self, enable=None):
        if mediakeys is None:            # 非 Windows：没有这套 API，静默禁用
            return False
        if enable is None:
            enable = bool(self.cfg.get("media_keys", True))
        if self.media_keys is None:
            try:
                hwnd = int(self.overlay.winId())
            except Exception:
                return False
            self.media_keys = mediakeys.MediaKeyFilter(hwnd, self._on_media_key)
            self.app.installNativeEventFilter(self.media_keys)
        if enable:
            n = self.media_keys.register()
            self.cfg["media_keys"] = n > 0
            self.log.info("多媒体键注册 %d/4", n)
            return n > 0
        self.media_keys.unregister()
        self.cfg["media_keys"] = False
        return True

    def _on_media_key(self, action):
        self._on_player_command(action, 0.0)

    def _toggle_media_keys(self, checked):
        ok = self._setup_media_keys(enable=bool(checked))
        if checked and not ok:
            self.overlay.set_status("多媒体键注册失败（可能被其它程序占用）")
        save_config(self.cfg)

    # ---- 音量键接管（键盘旋钮 → Sonos 音量）----------------------------- #
    def _on_volume_key(self, action):
        """键盘钩子回调（主线程，必须尽快返回）；返回 True 吞掉按键。"""
        if self.poller is None:
            return False                 # 没连音箱：音量键交还给系统
        if action == "mute":
            self._on_player_command("mute", 0.0)
            return True
        self._vol_pending += (VOL_KEY_STEP if action == "vol_up"
                              else -VOL_KEY_STEP)
        self._vol_timer.start()          # 聚合旋转过程中的连续按键
        return True

    def _flush_volume(self):
        delta = self._vol_pending
        self._vol_pending = 0
        if delta:
            self._on_player_command("volume", float(delta))

    def _setup_volume_hook(self, enable=None):
        if mediakeys is None:            # 非 Windows：音量键交还给系统
            return False
        if enable is None:
            enable = bool(self.cfg.get("volume_keys_speaker", True))
        if self.volume_hook is None:
            self.volume_hook = mediakeys.VolumeKeyHook(self._on_volume_key)
        if enable:
            ok = self.volume_hook.install()
            self.log.info("音量键接管：%s", "ok" if ok else "failed")
            return ok
        self.volume_hook.uninstall()
        return True

    def _toggle_volume_keys(self, checked):
        ok = self._setup_volume_hook(enable=bool(checked))
        self.cfg["volume_keys_speaker"] = bool(checked)   # 记录用户意愿
        if checked and not ok:
            self.overlay.set_status("音量键接管失败（可能被安全软件拦截）")
        save_config(self.cfg)

    def _clear_cache(self):
        n = cache.clear()
        st = cache.stats()
        self.overlay.set_status("已清空缓存（%d 个文件，剩余 %d）" % (n, st["lyrics"] + st["art"]))

    # ---- 歌词 ----------------------------------------------------------- #
    @staticmethod
    def _track_key(info):
        if not info:
            return None
        return (info.get("title"), info.get("artist"),
                info.get("album"), info.get("uri"))

    def _on_track(self, info):
        if (self.current_track is not None
                and self._track_key(info) == self._track_key(self.current_track)):
            # 同一首歌：可能是封面地址晚到（AirPlay 常见）——只补封面，
            # 不动已显示的歌词，也不重新搜索
            self.current_track = info
            if info.get("album_art") and self._art_key != self._track_key(info):
                self._refresh_art(info)
            return
        self.current_track = info
        self._last_lyrics = None
        self.log.info("曲目：%s — %s（专辑：%s，时长 %.0fs，状态 %s）",
                      info.get("artist"), info.get("title"),
                      info.get("album"), float(info.get("duration") or 0.0),
                      info.get("state"))
        self.overlay.set_track(info)
        self.fullscreen.set_track(info)
        # 不清封面：留上一张，等新封面到了无缝换掉，避免闪占位图
        self._fetch_lyrics()

    def _refresh_art(self, info):
        """后台补抓封面（曲目未变，只是封面地址刚就绪）。"""
        task = ArtTask(self.seq, info)
        task.signals.done.connect(
            lambda seq, art, t=task: self._on_art_refreshed(seq, art, t)
        )
        self._tasks.add(task)
        self.pool.start(task)

    def _on_art_refreshed(self, seq, art, task=None):
        if task is not None:
            self._tasks.discard(task)
        if seq != self.seq or not art:
            return
        if art == self._last_art:
            return                      # 已经显示的就是这张，省一次重绘
        self._last_art = art
        self._art_key = self._track_key(self.current_track)
        self.overlay.set_album_art_bytes(art)
        self.fullscreen.set_album_art_bytes(art)

    def relyrics(self):
        if self.current_track:
            self._fetch_lyrics(force=True)      # 手动重搜：绕过缓存
        else:
            self.overlay.set_status("还没有播放信息")

    def _dump_track(self):
        """把当前曲目的原始信息写进 track_debug.txt（排查匹配不到歌词的歌）。"""
        info = self.current_track or {}
        path = os.path.join(DATA_DIR, "track_debug.txt")
        try:
            with io.open(path, "w", encoding="utf-8") as fp:
                fp.write(u"时间: %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                for key, val in info.items():
                    if key == "meta_xml":
                        continue
                    fp.write(u"%-12s = %r\n" % (key, val))
                fp.write(u"\nTrackMetaData 原文:\n")
                fp.write(info.get("meta_xml") or u"(空)")
                fp.write(u"\n")
            self.overlay.set_status("已导出 track_debug.txt")
        except Exception as exc:
            self.overlay.set_status("导出失败：%r" % (exc,))

    def _fetch_lyrics(self, force=False):
        if not self.current_track:
            return
        self.seq += 1
        task = LyricsTask(
            self.seq,
            self.current_track,
            self.cfg.get("provider_order") or ["apple", "netease", "lrclib"],
            force=force,
        )
        task.signals.done.connect(
            lambda seq, result, art, t=task: self._on_lyrics(seq, result, art, t)
        )
        self._tasks.add(task)
        self.pool.start(task)

    def _on_lyrics(self, seq, result, art, task=None):
        if task is not None:
            self._tasks.discard(task)
        if seq != self.seq:
            return                      # 已经切歌，丢弃过期结果
        self.log.info("歌词结果：%s（封面 %s）",
                      "无" if not result else
                      ("逐词 %d 行" % len(result.get("lines") or []) if
                       result.get("synced") else
                       "逐行 %d 行" % len(result.get("plain") or [])),
                      "有" if art else "无")
        # 逐词歌词要 Apple 凭证：没配过就提示一次，免得用户以为逐词是坏了
        if (not self._apple_hint_shown and result
                and not (result.get("words") or [])
                and not os.path.exists(app_paths.token_path())):
            self._apple_hint_shown = True
            try:
                self.tray.showMessage(
                    speakers.APP_NAME,
                    "当前是普通歌词。配置 Apple Music 凭证后会有逐词高亮和翻译"
                    "（托盘菜单 →「Apple Music 凭证」）",
                    QSystemTrayIcon.MessageIcon.Information, 8000)
            except Exception:
                pass
        self._last_lyrics = result
        self.overlay.set_lyrics(result)
        self.fullscreen.set_lyrics(result)
        self._last_art = art
        if art:
            self._art_key = self._track_key(self.current_track)
        self.overlay.set_album_art_bytes(art)
        self.fullscreen.set_album_art_bytes(art)

    # ---- 退出 ----------------------------------------------------------- #
    def quit(self):
        self.log.info("退出")
        if self._retry_timer is not None:
            self._retry_timer.stop()
        if self.poller is not None:
            self.poller.stop()
            self.poller.wait(1500)
        self._event_server.stop()
        if self.media_keys is not None:
            self.media_keys.unregister()
        if self.volume_hook is not None:
            self.volume_hook.uninstall()
        self.overlay.save_position()
        save_config(self.cfg)
        self.tray.hide()
        self.app.quit()


def create_app_shortcut(link_path):
    """用 PowerShell + WScript.Shell 创建快捷方式（仅 Windows；启动时无黑框）。"""
    if sys.platform != "win32" or not link_path:
        return False
    if app_paths.is_frozen():               # exe：直接指向自己（图标取 exe 自己的）
        target = sys.executable
        args = ""
        workdir = os.path.dirname(sys.executable)
        icon = sys.executable
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        target = pythonw
        args = os.path.join(RES_DIR, "main.py")
        workdir = RES_DIR
        icon = app_paths.icon_path()
    ps1 = app_paths.shortcut_ps1()
    try:
        import subprocess
        subprocess.Popen(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", ps1,
                "-LinkPath", link_path,
                "-Target", target,
                "-ScriptArgs", args,
                "-WorkDir", workdir,
                "-Icon", icon if os.path.exists(icon) else "",
            ],
            creationflags=0x08000000,          # CREATE_NO_WINDOW
        )
        return True
    except Exception:
        return False


def main():
    if sys.platform == "win32":
        # 固定 AppUserModelID：任务栏/通知按“LyriCast”归类，
        # 图标才会用我们的 icon.ico，而不是 pythonw.exe 的 Python 图标
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ChandlerYancug.LyriCast")
        except Exception:
            pass
    speakers.setup()                      # 日志：文件 + 控制台（有终端时）
    speakers.install_excepthook()
    log = speakers.get_logger("main")
    log.info("%s %s 启动（Python %s）", speakers.APP_NAME,
             speakers.APP_VERSION, sys.version.split()[0])
    app = QApplication(sys.argv)
    app.setApplicationName(speakers.APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    load_bundled_fonts()
    icon = app_paths.icon_path()
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))

    controller = LyriCastApp(app)
    app.aboutToQuit.connect(lambda: save_config(controller.cfg))
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
