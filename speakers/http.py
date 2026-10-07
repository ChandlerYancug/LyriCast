# -*- coding: utf-8 -*-
"""HTTP / XML / SOAP 公共工具：各「音箱后端」共用的一套小函数。

后端只做三件事：**读**播放状态、**控**（用户点了才发）、**订阅**事件。
所有对外的网络访问都从这里走，超时/UA/重试口径一致，方便统一排查。
"""

import html
import re
import xml.etree.ElementTree as ET

import requests

# 换名字/建仓库后改这两行即可
APP_NAME = "LyriCast"
APP_VERSION = "0.4.2"
UA = "%s/%s (+https://github.com/)" % (APP_NAME, APP_VERSION)

DEFAULT_TIMEOUT = 5.0

_SOAP_TPL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>"
    '<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">{args}</u:{action}>'
    "</s:Body></s:Envelope>"
)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get(url, timeout=DEFAULT_TIMEOUT, headers=None):
    """GET，返回 requests.Response（失败抛异常，调用方决定兜底）。"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    return requests.get(url, timeout=timeout, headers=h)


def fetch_bytes(url, timeout=6.0):
    """下载二进制（封面等），失败返回 None —— 网络问题不该打断播放。"""
    if not url:
        return None
    try:
        r = http_get(url, timeout=timeout)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


def soap_call(url, service, action, args=None, timeout=DEFAULT_TIMEOUT):
    """发一次 UPnP SOAP 调用，返回原始响应文本。

    url     完整控制地址（每个设备不同：Sonos 是 :1400/...，DLNA 由描述文档给出）
    service 'AVTransport' / 'RenderingControl' / 'ZoneGroupTopology' ...
    """
    args = args or {}
    arg_xml = "".join("<%s>%s</%s>" % (k, html.escape(str(v)), k)
                      for k, v in args.items())
    body = _SOAP_TPL.format(action=action, service=service, args=arg_xml)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": '"urn:schemas-upnp-org:service:%s:1#%s"' % (service, action),
        "User-Agent": UA,
    }
    r = requests.post(url, data=body.encode("utf-8"), headers=headers,
                      timeout=timeout)
    r.raise_for_status()
    return r.text


def soap_xml(url, service, action, args=None, timeout=DEFAULT_TIMEOUT):
    """SOAP 调用并解析成 ElementTree 根节点。"""
    return ET.fromstring(soap_call(url, service, action, args, timeout))


# --------------------------------------------------------------------------- #
# XML 小工具（命名空间无关，各厂商 XML 差异大，一律按 localname 找）
# --------------------------------------------------------------------------- #
def localname(tag):
    return tag.rsplit("}", 1)[-1]


def find(root, name):
    if root is None:
        return None
    for el in root.iter():
        if localname(el.tag) == name:
            return el
    return None


def text(root, name, default=""):
    if root is None:
        return default
    el = find(root, name)
    if el is None or el.text is None:
        return default
    return el.text.strip()


def attr(root, name, key, default=""):
    el = find(root, name)
    if el is None:
        return default
    return el.attrib.get(key, default)


_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")


def parse_xml(data, lenient=True):
    """解析 XML；lenient=True 时先修补裸 & 再试一次（部分设备报文不合法）。"""
    if not data:
        return None
    if isinstance(data, str):
        data = data.encode("utf-8", "ignore")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        pass
    if not lenient:
        return None
    try:
        fixed = _AMP_RE.sub("&amp;", data.decode("utf-8", "ignore"))
        return ET.fromstring(fixed)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 时间格式
# --------------------------------------------------------------------------- #
def parse_clock(value):
    """'0:03:21' / '0:03:21.500' / 'NOT_IMPLEMENTED' -> 秒（无效返回 0.0）。"""
    if not value:
        return 0.0
    value = str(value).strip()
    if value.upper().replace(" ", "_") in ("NOT_IMPLEMENTED", "NOT_AVAILABLE", ""):
        return 0.0
    parts = value.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return 0.0
    secs = 0.0
    for p in parts:
        secs = secs * 60.0 + p
    return secs


def fmt_clock(seconds):
    """秒 -> 'H:MM:SS'（Seek 用）。"""
    seconds = max(0.0, float(seconds))
    return "%d:%02d:%02d" % (int(seconds) // 3600,
                             (int(seconds) % 3600) // 60,
                             int(seconds) % 60)
