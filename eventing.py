# -*- coding: utf-8 -*-
"""UPnP / GENA 事件订阅（音箱 → 本机 的主动推送）。

为什么需要它：音箱的 GetPositionInfo 轮询有延迟（RelTime 往往只有 1 秒粒度，
seek 之后音箱也要缓冲后才上报新位置），所以光靠轮询，进度条一拖就会"慢一两句"。

订阅之后，音箱会在 **seek / 换歌 / 暂停的那一刻** 主动 POST 一条事件到我们本机，
我们立刻去查一次位置 —— 延迟从"几百毫秒 + 音箱上报延迟"降到几十毫秒。

代价：需要在本机监听一个端口，首次运行 Windows 会弹一次防火墙授权。
若订阅失败（例如用户拒绝了防火墙），程序自动退回纯轮询，只是没那么快。

注意：这里全部用**绝对地址**（各家设备的控制/事件地址不同，由后端解析设备
描述得到，如 Sonos 的 :1400/MediaRenderer/... 或 DLNA 的 :49152/upnp/event/...）。
"""

import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from speakers.http import APP_NAME, APP_VERSION, UA

SUB_TIMEOUT_SEC = 300          # 订阅有效期（秒），到期前续订

# 裸的 & （不是合法实体）会让解析整个失败，先补转义
_BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")


def _localname(tag):
    return tag.rsplit("}", 1)[-1]


# --------------------------------------------------------------------------- #
# 本机 IP
# --------------------------------------------------------------------------- #
def local_ip_for(remote_ip):
    """取本机在通往 remote_ip 的那张网卡上的 IP（不会真的发包）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((remote_ip, 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# --------------------------------------------------------------------------- #
# 接收回调的 HTTP 服务
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "%sEvent/%s" % (APP_NAME, APP_VERSION)

    def log_message(self, *args):        # 静音
        pass

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_NOTIFY(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length else b""
        sid = self.headers.get("SID", "")
        self._ok()
        cb = getattr(self.server, "on_event", None)
        if cb is not None:
            try:
                cb(sid, body)
            except Exception:
                pass

    def do_SUBSCRIBE(self):
        self._ok()

    def do_GET(self):
        self._ok()

    def do_POST(self):
        self.do_NOTIFY()


class EventServer(object):
    """极小的 HTTP 服务，只用来收音箱的事件推送。"""

    def __init__(self):
        self.httpd = None
        self.port = 0

    def start(self, on_event):
        if self.httpd is not None:
            return True
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", 0), _Handler)
        except Exception:
            return False
        httpd.daemon_threads = True
        httpd.on_event = on_event
        self.httpd = httpd
        self.port = httpd.server_address[1]
        t = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
        )
        t.start()
        return True

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            self.httpd = None

    @property
    def running(self):
        return self.httpd is not None and self.port > 0


# --------------------------------------------------------------------------- #
# 订阅 / 续订 / 退订
# --------------------------------------------------------------------------- #
def subscribe(event_url, callback_url, timeout_sec=SUB_TIMEOUT_SEC, timeout=6):
    """订阅一个事件地址（绝对 URL），返回 SID（失败抛异常）。"""
    headers = {
        "CALLBACK": "<%s>" % callback_url,
        "NT": "upnp:event",
        "TIMEOUT": "Second-%d" % timeout_sec,
        "USER-AGENT": UA,
    }
    r = requests.request("SUBSCRIBE", event_url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.headers.get("SID", "")


def renew(event_url, sid, timeout_sec=SUB_TIMEOUT_SEC, timeout=6):
    headers = {
        "SID": sid,
        "TIMEOUT": "Second-%d" % timeout_sec,
        "USER-AGENT": UA,
    }
    r = requests.request("SUBSCRIBE", event_url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return True


def unsubscribe(event_url, sid, timeout=4):
    try:
        requests.request("SUBSCRIBE", event_url,
                         headers={"SID": sid, "USER-AGENT": UA},
                         timeout=timeout)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 解析事件内容
# --------------------------------------------------------------------------- #
def parse_last_change(body):
    """从 NOTIFY 报文里抽出 AVTransport 的状态字段 -> dict。

    结构：propertyset / property / LastChange（里面是一段被转义的 XML）。
    """
    out = {}
    if not body:
        return out
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out

    last_change = None
    for el in root.iter():
        name = _localname(el.tag)
        if name == "LastChange" and el.text:
            last_change = el.text
        elif name == "ZoneGroupState" and el.text:
            out["__ZoneGroupState__"] = el.text
    if not last_change:
        return out

    try:
        ev = ET.fromstring(last_change)
    except ET.ParseError:
        # 容忍报文里混进的裸 & 等小毛病
        try:
            ev = ET.fromstring(_BARE_AMP_RE.sub("&amp;", last_change))
        except ET.ParseError:
            return out
    for el in ev.iter():
        val = el.attrib.get("val")
        if val is not None:
            out[_localname(el.tag)] = val
    return out


if __name__ == "__main__":
    # 简单自测：起服务并打印收到的原始事件
    # 用法：python eventing.py <事件地址>   例：
    #   python eventing.py http://192.168.1.20:1400/MediaRenderer/AVTransport/Event
    import sys

    def on_ev(sid, body):
        print("SID:", sid)
        print(body.decode("utf-8", "ignore")[:2000])

    srv = EventServer()
    print("start:", srv.start(on_ev), "port:", srv.port)
    if len(sys.argv) > 1:
        url = sys.argv[1]
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0]
        cb = "http://%s:%d/notify" % (local_ip_for(host), srv.port)
        print("callback:", cb)
        print("subscribe:", subscribe(url, cb))
        print("等待事件 30 秒（去音箱 App 拖一下进度条）…")
        time.sleep(30)
