# -*- coding: utf-8 -*-
"""UpnpBackend 的离线测试：标准库起一台假 DLNA 音箱，验证描述解析 / 读 / 控。

跑法（项目根目录）：
    python tests/test_upnp_backend.py     # 直接跑，顺序执行并打印 OK
    pytest tests/test_upnp_backend.py     # 也能被收集
"""

import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from xml.sax.saxutils import escape as xml_escape

# 直接运行时脚本目录是 tests/，得手动把项目根塞进 import 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakers.base import NotSupported           # noqa: E402
from speakers.upnp import UpnpBackend            # noqa: E402

# Mock 设备给的数据（测试断言与之一一对应）
TITLE = "夜空中最亮的星"
ARTIST = "逃跑计划"
ALBUM = "世界"
ART_PATH = "/art/cover42.jpg"
TRACK_URI = "http://192.168.1.20:8200/MediaItems/42.mp3"
REL_TIME = "0:00:42"
DURATION = "0:03:21"
VOLUME = 37

# TrackMetaData：和真实设备一样是嵌套 XML（放进响应前要转义）
DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item id="42" parentID="1" restricted="1">'
    "<dc:title>%s</dc:title>"
    "<dc:creator>%s</dc:creator>"
    "<upnp:album>%s</upnp:album>"
    "<upnp:albumArtURI>%s</upnp:albumArtURI>"
    '<res protocolInfo="http-get:*:audio/mpeg:*">%s</res>'
    "</item>"
    "</DIDL-Lite>"
) % (TITLE, ARTIST, ALBUM, ART_PATH, TRACK_URI)


def _envelope(service, action, inner=""):
    """拼一个带完整命名空间的 SOAP 响应（真实设备的形状）。"""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        '<u:%sResponse xmlns:u="urn:schemas-upnp-org:service:%s:1">%s</u:%sResponse>'
        "</s:Body>"
        "</s:Envelope>"
    ) % (action, service, inner, action)


def _action_of(soapaction, body):
    """从 SOAPACTION 头（或 body）里取出动作名。"""
    if "#" in soapaction:
        return soapaction.rsplit("#", 1)[1].strip().strip('"')
    m = re.search(r"<u:([A-Za-z]+)", body)
    return m.group(1) if m else ""


class MockDlnaSpeaker(object):
    """一台假 DLNA 音箱：设备描述 + AVTransport/RenderingControl 两个 SOAP 端点。"""

    def __init__(self):
        self.calls = []      # 收到的请求：[{path, action, soapaction, body}, ...]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    # -- 生命周期 ---------------------------------------------------------- #
    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def last_call(self, path_suffix):
        """最近一条命中路径后缀的请求（断言发出去的 SOAP）。"""
        for call in reversed(self.calls):
            if call["path"].endswith(path_suffix):
                return call
        raise AssertionError("没有收到路径以 %s 结尾的请求" % path_suffix)

    # -- 响应内容 ---------------------------------------------------------- #
    def _description(self, with_rc):
        services = [("AVTransport", "upnp/control/AVTransport",
                     "upnp/event/AVTransport")]
        if with_rc:
            services.append(("RenderingControl", "upnp/control/RenderingControl",
                             "upnp/event/RenderingControl"))
        entries = "".join(
            "<service>"
            "<serviceType>urn:schemas-upnp-org:service:%s:1</serviceType>"
            "<serviceId>urn:upnp-org:serviceId:%s</serviceId>"
            "<controlURL>%s</controlURL>"
            "<eventSubURL>%s</eventSubURL>"
            "<SCPDURL>upnp/%s.xml</SCPDURL>"
            "</service>" % (name, name, ctrl, evt, name)
            for name, ctrl, evt in services
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion>"
            "<URLBase>http://127.0.0.1:%d</URLBase>"
            "<device>"
            "<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>"
            "<friendlyName>Mock DLNA Speaker</friendlyName>"
            "<manufacturer>Mock</manufacturer>"
            "<modelName>TestRenderer</modelName>"
            "<UDN>uuid:mock-upnp-speaker</UDN>"
            "<serviceList>%s</serviceList>"
            "</device>"
            "</root>"
        ) % (self.port, entries)

    def _soap_response(self, path, action):
        if not action:
            return None
        if path.endswith("/control/AVTransport"):
            if action == "GetPositionInfo":
                inner = (
                    "<Track>1</Track>"
                    "<TrackDuration>%s</TrackDuration>"
                    "<TrackMetaData>%s</TrackMetaData>"
                    "<TrackURI>%s</TrackURI>"
                    "<RelTime>%s</RelTime>"
                    "<AbsTime>NOT_IMPLEMENTED</AbsTime>"
                    "<RelativeCounterPosition>0</RelativeCounterPosition>"
                    "<AbsoluteCounterPosition>0</AbsoluteCounterPosition>"
                ) % (DURATION, xml_escape(DIDL), TRACK_URI, REL_TIME)
            elif action == "GetTransportInfo":
                inner = ("<CurrentTransportState>PLAYING</CurrentTransportState>"
                         "<CurrentTransportStatus>OK</CurrentTransportStatus>"
                         "<CurrentSpeed>1</CurrentSpeed>")
            else:                       # Play / Pause / Next / Previous / Seek
                inner = ""
            return _envelope("AVTransport", action, inner)
        if path.endswith("/control/RenderingControl"):
            if action == "GetVolume":
                inner = "<CurrentVolume>%d</CurrentVolume>" % VOLUME
            elif action == "GetMute":
                inner = "<CurrentMute>0</CurrentMute>"
            else:                       # SetVolume / SetMute
                inner = ""
            return _envelope("RenderingControl", action, inner)
        return None

    # -- HTTP 处理 ---------------------------------------------------------- #
    def _handler_class(self):
        speaker = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                pass                # 别把测试输出搞脏

            def _send(self, code, text):
                data = text.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", 'text/xml; charset="utf-8"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path in ("/description.xml", "/description_norc.xml"):
                    self._send(200, speaker._description(
                        self.path == "/description.xml"))
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8", "ignore")
                soapaction = self.headers.get("SOAPACTION", "")
                action = _action_of(soapaction, body)
                speaker.calls.append({"path": self.path, "action": action,
                                      "soapaction": soapaction, "body": body})
                xml = speaker._soap_response(self.path, action)
                if xml is None:
                    self.send_error(404)
                else:
                    self._send(200, xml)

        return Handler


# --------------------------------------------------------------------------- #
# 测试
# --------------------------------------------------------------------------- #
def test_now_playing_from_mock():
    """描述解析 + GetPositionInfo/GetTransportInfo + DIDL 元数据。"""
    with MockDlnaSpeaker() as spk:
        be = UpnpBackend("127.0.0.1", location=spk.url("/description.xml"))
        # 相对 controlURL 按 <URLBase> 补全成了绝对控制地址
        assert be._avt_url == spk.url("/upnp/control/AVTransport"), be._avt_url
        assert be._rc_url == spk.url("/upnp/control/RenderingControl"), be._rc_url

        np = be.now_playing()
        assert np.title == TITLE, np.title
        assert np.artist == ARTIST, np.artist
        assert np.album == ALBUM, np.album
        assert np.position == 42.0, np.position
        assert np.duration == 201.0, np.duration
        assert np.state == "PLAYING", np.state
        assert np.uri == TRACK_URI, np.uri
        assert np.album_art.startswith("http://"), np.album_art
        assert np.album_art == spk.url(ART_PATH), np.album_art
        assert "DIDL-Lite" in np.raw.get("meta_xml", ""), np.raw


def test_controls_and_seek():
    """音量读取、Seek 目标时间、四个传输控制、音量夹取与静音。"""
    with MockDlnaSpeaker() as spk:
        be = UpnpBackend("127.0.0.1", location=spk.url("/description.xml"))

        assert be.get_volume() == VOLUME

        be.seek(12.5)
        call = spk.last_call("/control/AVTransport")
        assert call["action"] == "Seek", call
        assert "<Target>0:00:12</Target>" in call["body"], call["body"]
        assert "<Unit>REL_TIME</Unit>" in call["body"], call["body"]
        assert "<InstanceID>0</InstanceID>" in call["body"], call["body"]

        before = len(spk.calls)
        be.play()
        be.pause()
        be.next_track()
        be.previous_track()
        assert [c["action"] for c in spk.calls[before:]] == [
            "Play", "Pause", "Next", "Previous"]
        assert "<Speed>1</Speed>" in spk.calls[before]["body"]

        assert be.set_volume(150) == 100        # 夹到上限并返回生效值
        call = spk.last_call("/control/RenderingControl")
        assert call["action"] == "SetVolume", call
        assert "<DesiredVolume>100</DesiredVolume>" in call["body"], call["body"]

        assert be.get_mute() is False
        assert be.set_mute(True) is True
        call = spk.last_call("/control/RenderingControl")
        assert "<DesiredMute>1</DesiredMute>" in call["body"], call["body"]


def test_event_urls():
    """事件地址是绝对的，指向描述里的 eventSubURL。"""
    with MockDlnaSpeaker() as spk:
        be = UpnpBackend("127.0.0.1", location=spk.url("/description.xml"))
        urls = be.event_urls()
        assert urls == [spk.url("/upnp/event/AVTransport")], urls
        assert urls[0].startswith("http://"), urls


def test_missing_description_raises():
    """自动找描述失败 -> RuntimeError，且报错要教用户去 config.json 填。"""
    with mock.patch("speakers.discovery.find_description",
                    return_value=(None, None)):
        try:
            UpnpBackend("127.0.0.1", location="")
        except RuntimeError as exc:
            msg = str(exc)
            assert "config.json" in msg, msg
            assert "speaker_location" in msg, msg
            assert "http://" in msg, msg
        else:
            raise AssertionError("找不到设备描述时应抛 RuntimeError")


def test_without_rendering_control():
    """缺 RenderingControl 的纯渲染器：还能读，音量降级。"""
    with MockDlnaSpeaker() as spk:
        be = UpnpBackend("127.0.0.1", location=spk.url("/description_norc.xml"))
        assert be._rc_url == ""
        assert be.get_volume() == -1
        assert be.now_playing().title == TITLE
        try:
            be.set_volume(30)
        except NotSupported:
            pass
        else:
            raise AssertionError("没有 RenderingControl 时 set_volume 应抛 NotSupported")


TESTS = (
    test_now_playing_from_mock,
    test_controls_and_seek,
    test_event_urls,
    test_missing_description_raises,
    test_without_rendering_control,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
