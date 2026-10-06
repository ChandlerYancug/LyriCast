# -*- coding: utf-8 -*-
"""音箱后端抽象：把「读播放状态 / 控制 / 订阅事件」抽象成统一接口。

一个后端对应一种音频源（不一定是音箱本身）：

    sonos     Sonos 系统音箱（UPnP + 私有 ZoneGroupTopology）
    upnp      通用 DLNA / UPnP-AV 渲染器（WiiM、HEOS、MusicCast、Bluesound、
              foobar2000、Volumio…几乎所有「网络音箱/数播」都吃这套）
    smtc      Windows 系统媒体会话（电脑自己播放时读，包括经电脑 AirPlay 投给 HomePod）
    macos     macOS Now Playing（将来）
    listen    麦克风 + 音频指纹（任何音箱都能用，包括 HomePod；实验性，将来）

写新后端只需继承 `Backend` 并实现读接口；控制/订阅按能力声明，
界面会自动隐藏不支持的按钮（`capabilities`）。
"""

from dataclasses import dataclass, field
import re


# 能力位
CAN_CONTROL = "control"        # 播放/暂停/切歌
CAN_SEEK = "seek"              # 拖进度条
CAN_VOLUME = "volume"          # 读/调音量、静音
CAN_EVENTS = "events"          # 支持 UPnP/GENA 事件订阅（seek 瞬间同步）
CAN_COORDINATOR = "coordinator"  # 多房间/立体声：需要跟随协调器

PLAYING_STATES = ("PLAYING", "TRANSITIONING")
PAUSED_STATES = ("PAUSED_PLAYBACK", "PAUSED", "STOPPED", "NO_MEDIA_PRESENT", "")


class NotSupported(Exception):
    """该后端不支持这个操作（界面不应调用）。"""


@dataclass
class NowPlaying:
    """统一后的播放信息。字段与界面/歌词管线一一对应。"""

    title: str = ""
    artist: str = ""
    album: str = ""
    album_art: str = ""          # 绝对 URL（后端负责把相对地址补全）
    position: float = 0.0        # 秒
    duration: float = 0.0        # 秒
    uri: str = ""                # 曲目 URI（去重用）
    state: str = ""              # PLAYING / PAUSED_PLAYBACK / STOPPED / TRANSITIONING / ""
    raw: dict = field(default_factory=dict)   # 后端原始信息（排查用，如 meta_xml）

    @property
    def playing(self):
        """未知状态按「在播放」处理（个别设备会报私有状态）。"""
        return self.state not in PAUSED_STATES or self.state == ""

    @property
    def empty(self):
        return not self.title and not self.artist


class Backend(object):
    """所有后端的基类。默认「只会读」，支持什么由子类声明 capabilities。"""

    kind = "generic"
    capabilities = frozenset()

    def __init__(self, host, name="", location=""):
        self.host = host or ""
        self.name = name or host or ""
        self.location = location or ""      # 设备描述 URL（DLNA 重新连接用）

    # ------------------------------------------------------------------ #
    # 读（必须实现）
    # ------------------------------------------------------------------ #
    def now_playing(self):
        raise NotImplementedError

    def get_transport_state(self):
        return ""

    def get_volume(self):
        return -1                            # -1 = 读不到，界面不显示

    # ------------------------------------------------------------------ #
    # 控（默认不支持；只有用户点了才会被调用）
    # ------------------------------------------------------------------ #
    def play(self):
        raise NotSupported("play")

    def pause(self):
        raise NotSupported("pause")

    def next_track(self):
        raise NotSupported("next")

    def previous_track(self):
        raise NotSupported("previous")

    def seek(self, seconds):
        raise NotSupported("seek")

    def set_volume(self, value):
        raise NotSupported("volume")

    def get_mute(self):
        return False

    def set_mute(self, mute):
        raise NotSupported("mute")

    def toggle_mute(self):
        return self.set_mute(not self.get_mute())

    # ------------------------------------------------------------------ #
    # 事件（UPnP/GENA 的绝对事件地址；空 = 不支持）
    # ------------------------------------------------------------------ #
    def event_urls(self):
        return []

    # ------------------------------------------------------------------ #
    # 多房间：返回要跟随的协调器 (host, name)；不需要跟随返回 None
    # ------------------------------------------------------------------ #
    def coordinator(self):
        return None

    # ------------------------------------------------------------------ #
    # 杂项
    # ------------------------------------------------------------------ #
    def describe(self):
        return {"kind": self.kind, "name": self.name, "host": self.host,
                "location": self.location,
                "capabilities": sorted(self.capabilities)}

    def close(self):
        pass

    def __repr__(self):
        return "<%s %s (%s)>" % (type(self).__name__, self.name, self.host)


# --------------------------------------------------------------------------- #
# 元数据小工具：不同音源填的字段五花八门，共用一套兜底逻辑
# --------------------------------------------------------------------------- #
_SPLIT_PATTERNS = (
    re.compile(r"^(?P<artist>.+?)\s+[-–—]\s+(?P<title>.+)$"),
    re.compile(r"^(?P<title>.+?)\s+[-–—]\s+(?P<artist>.+)$"),
)


def split_title_artist(text):
    """'歌手 - 歌名' / '歌名 - 歌手' -> (title, artist)；拆不开返回 ('', 原文)。"""
    text = (text or "").strip()
    if not text:
        return "", ""
    for pat in _SPLIT_PATTERNS:
        m = pat.match(text)
        if m:
            return m.group("title").strip(), m.group("artist").strip()
    return "", text


def absolutize(base, url):
    """把相对 URL（/getaa?xxx）补成绝对地址。"""
    url = (url or "").strip()
    if not url:
        return ""
    low = url.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return url
    if not base:
        return url
    base = base.rstrip("/")
    if url.startswith("/"):
        return base + url
    return base + "/" + url
