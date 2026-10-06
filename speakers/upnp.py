# -*- coding: utf-8 -*-
"""通用 UPnP-AV / DLNA 渲染器后端（WiiM、HEOS、MusicCast、Bluesound、Volumio…）。

能力完全由设备的描述文档（description.xml）决定，不碰任何厂商私有接口：

    AVTransport       读播放信息 / 播放 / 暂停 / 切歌 / Seek
    RenderingControl  音量 / 静音（个别纯渲染器没有，降级为「读 -1、写 NotSupported」）

和 Sonos 后端不同：通用设备没有多房间拓扑，所以不声明 CAN_COORDINATOR。
控制/事件地址按 UPnP 规范解析：描述里有 <URLBase> 以它为准，否则以描述
文档自身的 URL 为基准，相对路径（controlURL/eventSubURL）用 urljoin 补全。
"""

from urllib.parse import urljoin, urlsplit

from . import discovery, http
from .base import (
    CAN_CONTROL,
    CAN_EVENTS,
    CAN_SEEK,
    CAN_VOLUME,
    Backend,
    NotSupported,
    NowPlaying,
    absolutize,
    split_title_artist,
)

# 找不到设备描述时的报错：必须告诉用户去 config.json 手填，别只抛堆栈
_NO_LOCATION_MSG = (
    "找不到 %(host)s 的 UPnP 设备描述；请在 config.json 的 "
    "\"speaker_location\" 里填入设备描述 URL（例如 "
    "http://192.168.1.20:49152/description.xml），"
    "或确认设备已开机、和电脑在同一网段"
)


class UpnpBackend(Backend):
    """一台通用 DLNA / UPnP-AV 渲染器（连接时读设备描述，确定可用服务）。"""

    kind = "upnp"
    capabilities = frozenset({CAN_CONTROL, CAN_SEEK, CAN_VOLUME, CAN_EVENTS})

    def __init__(self, host, name="", location=""):
        super().__init__(host, name=name, location=location)
        self._avt_url = ""      # AVTransport 控制地址
        self._rc_url = ""       # RenderingControl 控制地址（可能没有）
        self._event_avt = ""    # AVTransport 事件地址
        self._event_rc = ""     # RenderingControl 事件地址（暂不订阅，音量靠轮询）
        self._origin = ""       # 描述文档所在主机的 origin（封面相对地址补全用）

        if not self.location:
            found, info = discovery.find_description(self.host)
            if not found:
                raise RuntimeError(_NO_LOCATION_MSG % {"host": self.host or "设备"})
            self.location = found
            if not name and info:
                self.name = info.get("name") or self.name

        parts = urlsplit(self.location)
        self._origin = "%s://%s" % (parts.scheme or "http", parts.netloc or self.host)
        self._parse_description()

    # ------------------------------------------------------------------ #
    # 设备描述
    # ------------------------------------------------------------------ #
    def _parse_description(self):
        """读描述文档的服务表，解析出各控制/事件地址。"""
        r = http.http_get(self.location)
        r.raise_for_status()
        root = http.parse_xml(r.content)      # 宽松解析：个别设备描述里有裸 &
        if root is None:
            raise RuntimeError("设备描述不是合法 XML：%s" % self.location)

        # URLBase 优先；没有就以描述文档 URL 为基准（UPnP 规范）
        base = http.text(root, "URLBase") or self.location
        have_avt = False
        for svc in root.iter():
            if http.localname(svc.tag) != "service":
                continue
            stype = http.text(svc, "serviceType")
            ctrl = http.text(svc, "controlURL")
            if not ctrl:
                continue
            evt = http.text(svc, "eventSubURL")
            if "AVTransport" in stype and not have_avt:
                have_avt = True
                self._avt_url = urljoin(base, ctrl)
                self._event_avt = urljoin(base, evt) if evt else ""
            elif "RenderingControl" in stype and not self._rc_url:
                self._rc_url = urljoin(base, ctrl)
                self._event_rc = urljoin(base, evt) if evt else ""
        if not self._avt_url:
            raise RuntimeError(
                "设备描述里没有 AVTransport 服务，不能当播放器用：%s" % self.location)

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def get_transport_state(self):
        """传输状态；失败不抛（状态只用于显示，不能让轮询层崩）。"""
        try:
            root = http.soap_xml(self._avt_url, "AVTransport", "GetTransportInfo",
                                 {"InstanceID": 0})
            return http.text(root, "CurrentTransportState")
        except Exception:
            return ""

    def now_playing(self):
        """读一次播放信息。网络错误照常抛（轮询层重试）；元数据缺失只留空字段。"""
        root = http.soap_xml(self._avt_url, "AVTransport", "GetPositionInfo",
                             {"InstanceID": 0})
        meta_xml = http.text(root, "TrackMetaData")
        title, artist, album, art = _parse_metadata(meta_xml, self._origin)
        if title and not artist:
            # 兜底：有些设备只把 "歌手 - 歌名" 塞进 title（部分流媒体源如此）
            split_title, split_artist = split_title_artist(title)
            if split_title and split_artist:
                title, artist = split_title, split_artist
        return NowPlaying(
            title=title,
            artist=artist,
            album=album,
            album_art=art,
            position=http.parse_clock(http.text(root, "RelTime")),
            duration=http.parse_clock(http.text(root, "TrackDuration")),
            uri=http.text(root, "TrackURI"),
            state=self.get_transport_state(),
            raw={"meta_xml": meta_xml},
        )

    def get_volume(self):
        """失败返回 -1（界面不显示音量）；设备没有 RenderingControl 也一样。"""
        if not self._rc_url:
            return -1
        try:
            root = http.soap_xml(self._rc_url, "RenderingControl", "GetVolume",
                                 {"InstanceID": 0, "Channel": "Master"})
            value = http.text(root, "CurrentVolume")
            return int(value) if value.isdigit() else -1
        except Exception:
            return -1

    # ------------------------------------------------------------------ #
    # 控（界面按 capabilities 决定是否显示按钮）
    # ------------------------------------------------------------------ #
    def _avt_call(self, action, args=None):
        args = dict(args or {})
        args["InstanceID"] = 0
        return http.soap_call(self._avt_url, "AVTransport", action, args)

    def play(self):
        self._avt_call("Play", {"Speed": 1})

    def pause(self):
        self._avt_call("Pause")

    def next_track(self):
        self._avt_call("Next")

    def previous_track(self):
        self._avt_call("Previous")

    def seek(self, seconds):
        self._avt_call("Seek", {"Unit": "REL_TIME",
                                "Target": http.fmt_clock(seconds)})

    def set_volume(self, value):
        if not self._rc_url:
            raise NotSupported("volume")
        value = max(0, min(100, int(value)))
        http.soap_call(self._rc_url, "RenderingControl", "SetVolume",
                       {"InstanceID": 0, "Channel": "Master",
                        "DesiredVolume": value})
        return value

    def get_mute(self):
        if not self._rc_url:
            return False
        try:
            root = http.soap_xml(self._rc_url, "RenderingControl", "GetMute",
                                 {"InstanceID": 0, "Channel": "Master"})
        except Exception:
            return False
        return (http.text(root, "CurrentMute") or "").lower() in ("1", "true")

    def set_mute(self, mute):
        if not self._rc_url:
            raise NotSupported("mute")
        http.soap_call(self._rc_url, "RenderingControl", "SetMute",
                       {"InstanceID": 0, "Channel": "Master",
                        "DesiredMute": "1" if mute else "0"})
        return bool(mute)

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def event_urls(self):
        """只订阅 AVTransport：Seek/切歌瞬间同步靠它；RenderingControl
        事件各厂商差异太大，音量变化交给轮询。"""
        return [self._event_avt] if self._event_avt else []


# --------------------------------------------------------------------------- #
# 元数据解析（TrackMetaData 是 DIDL-Lite，各家命名空间前缀不一，按 localname 找）
# --------------------------------------------------------------------------- #
def _parse_metadata(meta_xml, origin):
    """TrackMetaData -> (title, artist, album, album_art)；解析失败返回空。"""
    root = http.parse_xml(meta_xml) if meta_xml else None
    if root is None:
        return "", "", "", ""
    title = http.text(root, "title")               # dc:title（DIDL 里第一个 title）
    artist = http.text(root, "creator") or http.text(root, "artist")
    album = http.text(root, "album")               # upnp:album
    art = http.text(root, "albumArtURI")           # upnp:albumArtURI，常是相对路径
    return title, artist, album, absolutize(origin, art)
