# -*- coding: utf-8 -*-
"""Sonos 后端：直接走 UPnP/SOAP 读状态、发控制（不依赖 soco）。

Sonos 音箱在 1400 端口暴露标准 UPnP 服务：
    http://<ip>:1400/MediaRenderer/AVTransport/Control
    http://<ip>:1400/MediaRenderer/RenderingControl/Control
另外还有一个私有的 ZoneGroupTopology：多房间/立体声配对时，从机的
TrackMetaData / RelTime 都是 NOT_IMPLEMENTED，要靠它找到组里的协调器。
"""

import re
import xml.etree.ElementTree as ET

from . import http
from .base import (
    CAN_COORDINATOR,
    CAN_CONTROL,
    CAN_EVENTS,
    CAN_SEEK,
    CAN_VOLUME,
    Backend,
    NowPlaying,
    absolutize,
    split_title_artist,
)


# --------------------------------------------------------------------------- #
# 元数据解析（尽量兜底，因为不同音源填的字段不一样）
# --------------------------------------------------------------------------- #
def parse_metadata(meta_xml):
    """解析 TrackMetaData（DIDL-Lite）-> (title, artist, album, art)。

    三套兜底：正常 DIDL 字段、streamContent/radioShowMd 里的
    "歌手 - 歌名"、title 里带 " - " 但 creator 为空。
    """
    title = artist = album = art = ""
    if not meta_xml:
        return title, artist, album, art
    try:
        root = ET.fromstring(meta_xml)
    except ET.ParseError:
        return title, artist, album, art

    title = http.text(root, "title")
    artist = http.text(root, "creator") or http.text(root, "artist")
    album = http.text(root, "album")
    art = http.text(root, "albumArtURI")

    # 兜底 1：有些音源把信息塞在 streamContent / radioShowMd
    stream = http.text(root, "streamContent") or http.text(root, "radioShowMd")
    if stream and not (title and artist):
        t, a = split_title_artist(stream)
        if t:
            title = title or t
            artist = artist or a
        elif not title:
            title = stream.strip()

    # 兜底 2：title 里其实是 "歌手 - 歌名"，而 creator 为空
    if title and not artist:
        t, a = split_title_artist(title)
        if t:
            title, artist = t, a

    return title.strip(), artist.strip(), album.strip(), art.strip()


def _ip_from_location(location):
    """设备描述地址 http://192.168.1.20:1400/xml/... -> 192.168.1.20"""
    m = re.search(r"https?://([^/:]+)", location or "")
    return m.group(1) if m else ""


class SonosBackend(Backend):
    """Sonos 音箱后端。host 是 IP，port 默认 1400（一般不用改）。"""

    kind = "sonos"
    capabilities = frozenset({CAN_CONTROL, CAN_SEEK, CAN_VOLUME, CAN_EVENTS,
                              CAN_COORDINATOR})

    def __init__(self, host, name="", location="", port=1400):
        super().__init__(host, name=name, location=location)
        self.port = int(port or 1400)
        self._base = "http://%s:%d" % (self.host, self.port)

    # -- 地址 ---------------------------------------------------------------- #
    def _control_url(self, service):
        # 通用服务在 /MediaRenderer/<service>/Control，拓扑是 Sonos 私有路径
        if service == "ZoneGroupTopology":
            return self._base + "/ZoneGroupTopology/Control"
        return "%s/MediaRenderer/%s/Control" % (self._base, service)

    # -- 读 ------------------------------------------------------------------ #
    def get_transport_state(self):
        root = http.soap_xml(self._control_url("AVTransport"), "AVTransport",
                             "GetTransportInfo", {"InstanceID": 0})
        return http.text(root, "CurrentTransportState") or "STOPPED"

    def now_playing(self):
        root = http.soap_xml(self._control_url("AVTransport"), "AVTransport",
                             "GetPositionInfo", {"InstanceID": 0})
        meta_xml = http.text(root, "TrackMetaData")
        title, artist, album, art = parse_metadata(meta_xml)
        return NowPlaying(
            title=title,
            artist=artist,
            album=album,
            # 封面常是 /getaa?... 相对地址，补成绝对 URL 界面才能直接加载
            album_art=absolutize(self._base, art),
            position=http.parse_clock(http.text(root, "RelTime")),
            duration=http.parse_clock(http.text(root, "TrackDuration")),
            uri=http.text(root, "TrackURI"),
            state=self.get_transport_state(),
            raw={"meta_xml": meta_xml},
        )

    def get_volume(self):
        try:
            root = http.soap_xml(self._control_url("RenderingControl"),
                                 "RenderingControl", "GetVolume",
                                 {"InstanceID": 0, "Channel": "Master"})
            return int(http.text(root, "CurrentVolume") or 0)
        except Exception:
            return -1   # -1 = 读不到，界面不显示

    def get_mute(self):
        try:
            root = http.soap_xml(self._control_url("RenderingControl"),
                                 "RenderingControl", "GetMute",
                                 {"InstanceID": 0, "Channel": "Master"})
            return (http.text(root, "CurrentMute") or "").lower() in ("1", "true")
        except Exception:
            return False

    # -- 控（只有用户在界面上点了才会被调用） ---------------------------------- #
    def play(self):
        http.soap_xml(self._control_url("AVTransport"), "AVTransport", "Play",
                      {"InstanceID": 0, "Speed": 1})

    def pause(self):
        http.soap_xml(self._control_url("AVTransport"), "AVTransport", "Pause",
                      {"InstanceID": 0})

    def next_track(self):
        http.soap_xml(self._control_url("AVTransport"), "AVTransport", "Next",
                      {"InstanceID": 0})

    def previous_track(self):
        http.soap_xml(self._control_url("AVTransport"), "AVTransport", "Previous",
                      {"InstanceID": 0})

    def seek(self, seconds):
        http.soap_xml(self._control_url("AVTransport"), "AVTransport", "Seek",
                      {"InstanceID": 0, "Unit": "REL_TIME",
                       "Target": http.fmt_clock(seconds)})

    def set_volume(self, value):
        value = max(0, min(100, int(value)))   # 越界值先夹住，返回实际生效值
        http.soap_xml(self._control_url("RenderingControl"), "RenderingControl",
                      "SetVolume",
                      {"InstanceID": 0, "Channel": "Master",
                       "DesiredVolume": value})
        return value

    def set_mute(self, mute):
        http.soap_xml(self._control_url("RenderingControl"), "RenderingControl",
                      "SetMute",
                      {"InstanceID": 0, "Channel": "Master",
                       "DesiredMute": "1" if mute else "0"})
        return bool(mute)

    # -- 事件 / 多房间 -------------------------------------------------------- #
    def event_urls(self):
        # ZoneGroupTopology 事件用来感知分组变化，变化后要重新找协调器
        return [
            "%s/MediaRenderer/AVTransport/Event" % self._base,
            "%s/ZoneGroupTopology/Event" % self._base,
        ]

    def coordinator(self):
        """查 ZoneGroupTopology，返回要跟随的 (协调器 IP, 房间名) 或 None。

        从机自己读不到播放信息，必须去问协调器；查不到或自己就是协调器时
        返回 None（调用方只在非 None 时跟随）。
        """
        try:
            root = http.soap_xml(self._control_url("ZoneGroupTopology"),
                                 "ZoneGroupTopology", "GetZoneGroupState", {})
            state_xml = http.text(root, "ZoneGroupState")
            if not state_xml:
                return None
            zroot = ET.fromstring(state_xml)
        except Exception:
            # 拓扑读不到不该打断播放，当作「不用跟随」处理
            return None

        groups = [g for g in zroot.iter()
                  if http.localname(g.tag) == "ZoneGroup"]

        def members(group):
            # ZoneGroupMember 是 ZoneGroup 的直接子节点
            return [m for m in group
                    if http.localname(m.tag) == "ZoneGroupMember"]

        def coord_of(group):
            coord_uuid = group.attrib.get("Coordinator")
            for m in group.iter():
                if http.localname(m.tag) != "ZoneGroupMember":
                    continue
                if m.attrib.get("UUID") == coord_uuid:
                    ip = _ip_from_location(m.attrib.get("Location", "")) or self.host
                    return ip, m.attrib.get("ZoneName", "")
            return None

        for g in groups:
            if any(_ip_from_location(m.attrib.get("Location", "")) == self.host
                   for m in members(g)):
                got = coord_of(g)
                if got and got[0] != self.host:
                    return got
                return None
        # 自己不在任何组里（罕见）：退回第一组，同样只在不是自己时跟随
        for g in groups:
            got = coord_of(g)
            if got and got[0] != self.host:
                return got
        return None

    def close(self):
        # 纯 HTTP 调用，没有长连接/订阅需要释放
        pass
