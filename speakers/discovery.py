# -*- coding: utf-8 -*-
"""局域网设备发现（SSDP）。

同一条 M-SEARCH 里同时问两类设备：
    ZonePlayer:1     Sonos 系统（自带更完整的播放信息）
    MediaRenderer:1  通用 DLNA / UPnP-AV 渲染器（WiiM、HEOS、MusicCast、Volumio…）

发现结果统一成 dict：
    {ip, name, kind, udn, location, model, manufacturer}
    kind: "sonos" | "upnp"
    location: 设备描述 XML 的 URL（DLNA 后端重新连接时要用，建议存进配置）
"""

import re
import socket
import time

from . import http

SSDP_ADDR = ("239.255.255.250", 1900)
M_SEARCH_STS = (
    "urn:schemas-upnp-org:device:ZonePlayer:1",       # Sonos
    "urn:schemas-upnp-org:device:MediaRenderer:1",    # 通用 UPnP AV
)

# 手动填 IP（没有 SSDP 响应）时按顺序猜设备描述地址
DESC_CANDIDATES = (
    "/description.xml",
    "/rootDesc.xml",
    "/upnp/description.xml",
    "/DeviceDescription.xml",
    "/desc.xml",
    "/xml/device_description.xml",
)


def _m_search_msg(st):
    return "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        "HOST: 239.255.255.250:1900",
        'MAN: "ssdp:discover"',
        "MX: 2",
        "ST: " + st,
        "USER-AGENT: " + http.UA,
        "", "",
    ])


def _ssdp_probe(timeout):
    """一次 M-SEARCH，收集 {ip: {st:..., location:...}}（同 IP 多设备再细分）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except OSError:
        pass
    sock.settimeout(0.5)

    try:
        for st in M_SEARCH_STS:
            try:
                sock.sendto(_m_search_msg(st).encode("utf-8"), SSDP_ADDR)
            except OSError:
                pass
    except OSError:
        sock.close()
        return []

    found = {}          # (ip, location) -> {"st": set(), ...}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        head = data.decode("utf-8", "ignore")
        loc = _header(head, "LOCATION")
        if not loc:
            continue
        key = (addr[0], loc)
        item = found.setdefault(key, {"ip": addr[0], "location": loc, "st": set()})
        st = _header(head, "ST")
        if st:
            item["st"].add(st)
    sock.close()
    return list(found.values())


def _header(text, name):
    m = re.search(r"(?im)^%s:\s*(\S+)\s*$" % name, text)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# 设备描述文档
# --------------------------------------------------------------------------- #
def describe_location(location, ip="", timeout=4.0):
    """读取设备描述 XML，返回统一 dict（失败也要返回 ip，方便兜底手动选）。"""
    info = {"ip": ip, "name": ip, "kind": "upnp", "udn": "", "location": location,
            "model": "", "manufacturer": "", "device_type": ""}
    try:
        r = http.http_get(location, timeout=timeout)
        root = http.parse_xml(r.content, lenient=False)
    except Exception:
        return info
    if root is None:
        return info

    raw_type = http.text(root, "deviceType")
    info["udn"] = http.text(root, "UDN")
    info["model"] = http.text(root, "modelName")
    info["manufacturer"] = http.text(root, "manufacturer")
    info["device_type"] = raw_type.split(":")[-2] if raw_type.count(":") >= 3 else raw_type
    # Sonos 的描述里有 roomName；通用设备用 friendlyName
    info["name"] = (http.text(root, "roomName")
                    or http.text(root, "friendlyName") or ip)
    low = ("%s %s %s" % (info["manufacturer"], info["model"], raw_type)).lower()
    if "sonos" in low or "/zonePlayer" in raw_type:
        info["kind"] = "sonos"
    return info


def kind_of_st(st_set):
    for st in st_set:
        if st.lower().endswith("zoneplayer:1"):
            return "sonos"
    return "upnp"


def discover(timeout=3.0):
    """局域网发现，返回设备列表（按 Sonos 优先、其次名称排序）。"""
    out = {}
    for raw in _ssdp_probe(timeout):
        info = describe_location(raw["location"], raw["ip"])
        if raw["st"] and info["kind"] == "upnp":
            info["kind"] = kind_of_st(raw["st"])
        key = (info["ip"], info["location"])
        prev = out.get(key)
        if prev is None or (prev["kind"] != "sonos" and info["kind"] == "sonos"):
            out[key] = info
    devices = list(out.values())
    devices.sort(key=lambda d: (d["kind"] != "sonos", (d.get("name") or "").lower()))
    return devices


# --------------------------------------------------------------------------- #
# 手动 IP：猜设备描述地址（给不想开 SSDP 或跨网段的用户）
# --------------------------------------------------------------------------- #
def guess_locations(host):
    """给出该主机上可能的设备描述 URL 列表（DLNA 各家路径不统一，挨个试）。"""
    bases = ["http://%s:49152" % host, "http://%s:1400" % host,
             "http://%s:8080" % host, "http://%s" % host]
    urls = []
    for base in bases:
        for path in DESC_CANDIDATES:
            urls.append(base + path)
    return urls


def find_description(host, timeout=1.5):
    """在常见端口/路径里找一个能解析、且带 AVTransport 的 UPnP 描述。

    返回 (location, info) 或 (None, None)。
    """
    for url in guess_locations(host):
        info = describe_location(url, host, timeout=timeout)
        if info["udn"] or info["model"] or info["name"] != host:
            return url, info
    return None, None
