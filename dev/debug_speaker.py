# -*- coding: utf-8 -*-
"""诊断脚本：把音箱返回的原始数据全部导出，方便定位"读不到曲目"的问题。

用法：播放音乐的状态下双击 debug.bat（或 python dev/debug_speaker.py），
把生成的 debug_output.txt 发出来。

对 Sonos 和通用 DLNA 音箱都适用：
- 先 SSDP 发现，再按配置/发现结果打开对应后端；
- 打印后端能力、播放信息、原始 TrackMetaData；
- 能拿到控制地址的后端会把 GetTransportInfo / GetPositionInfo /
  GetMediaInfo / GetVolume 的**原始 SOAP 响应**也导出来。
"""

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)            # 项目根目录（本脚本在 dev/ 下）
sys.path.insert(0, BASE)

from utf8mode import ensure_utf8  # noqa: E402  （中文 Windows 默认 GBK）
ensure_utf8()

import speakers  # noqa: E402
from speakers import http  # noqa: E402

OUT_PATH = os.path.join(HERE, "debug_output.txt")

REQUESTS = [
    ("GetTransportInfo", "AVTransport", "GetTransportInfo", {"InstanceID": 0}),
    ("GetPositionInfo", "AVTransport", "GetPositionInfo", {"InstanceID": 0}),
    ("GetMediaInfo", "AVTransport", "GetMediaInfo", {"InstanceID": 0}),
    ("GetVolume", "RenderingControl", "GetVolume",
     {"InstanceID": 0, "Channel": "Master"}),
]


class Logger(object):
    def __init__(self, path):
        self.fp = io.open(path, "w", encoding="utf-8")

    def __call__(self, line=u""):
        try:
            print(line)
        except Exception:
            pass
        self.fp.write(line + u"\n")
        self.fp.flush()

    def close(self):
        self.fp.close()


def control_url(be, service):
    """尽力拿到某服务的控制地址（两种后端的私有字段不同，这里兜底试）。"""
    if be.kind == "sonos":
        if service == "ZoneGroupTopology":
            return "http://%s:1400/ZoneGroupTopology/Control" % be.host
        return "http://%s:1400/MediaRenderer/%s/Control" % (be.host, service)
    if service == "AVTransport":
        return getattr(be, "_avt_url", "")
    if service == "RenderingControl":
        return getattr(be, "_rc_url", "")
    return ""


def dump_info(log, be, title):
    log(u"")
    log(u"=== %s ===" % title)
    try:
        np = be.now_playing()
    except Exception as exc:
        log(u"  读播放信息失败: %r" % (exc,))
        return None
    for key in ("state", "title", "artist", "album", "position",
                "duration", "uri", "album_art"):
        log(u"  %-10s = %r" % (key, getattr(np, key)))
    meta = (np.raw or {}).get("meta_xml") or u""
    log(u"")
    log(u"  TrackMetaData 原文:")
    log(meta if meta else u"  (空)")
    try:
        log(u"")
        log(u"  音量 = %r" % (be.get_volume(),))
    except Exception as exc:
        log(u"  读音量失败: %r" % (exc,))
    return np


def main():
    log = Logger(OUT_PATH)
    log(u"%s · 诊断" % speakers.APP_NAME)
    log(u"时间: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    log(u"Python: " + sys.version.split()[0])
    log(u"")

    # ---- 1. 配置 ----
    cfg = {}
    try:
        with io.open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        log(u"读取 config.json 失败: %r" % (exc,))
    host = (cfg.get("speaker_host") or cfg.get("sonos_ip") or "").strip()
    kind = (cfg.get("speaker_type") or "auto").strip()
    loc = (cfg.get("speaker_location") or "").strip()
    log(u"配置: speaker_type=%r speaker_host=%r speaker_location=%r"
        % (kind, host, loc))

    # ---- 2. SSDP 发现 ----
    log(u"")
    log(u"=== 1) SSDP 发现（4 秒）===")
    devs = []
    try:
        devs = speakers.discover(4.0)
        if not devs:
            log(u"  没发现任何设备")
        for d in devs:
            log(u"  [%-5s] %-16s %-20s %s"
                % (d.get("kind"), d.get("ip", "?"), d.get("name", ""),
                   d.get("model", "")))
    except Exception as exc:
        log(u"  发现失败: %r" % (exc,))

    # ---- 3. 打开后端 ----
    if not host and devs:
        host = devs[0].get("ip", "")
        kind = devs[0].get("kind", "upnp")
        loc = devs[0].get("location", "")
    if not host:
        log(u"")
        log(u"没有可用的音箱地址，结束。")
        log.close()
        return
    if kind not in ("sonos", "upnp"):
        kind = "sonos" if loc == "" and (cfg.get("sonos_ip") or "") else "upnp"
    log(u"")
    log(u"=== 2) 打开后端 ===")
    try:
        be = speakers.open_backend(kind, host, name=cfg.get("speaker_name") or "",
                                   location=loc)
        log(u"  %r" % (be,))
        log(u"  能力: %s" % ", ".join(sorted(be.capabilities)))
        log(u"  事件地址: %r" % (be.event_urls(),))
    except Exception as exc:
        log(u"  打开失败: %r" % (exc,))
        log.close()
        return

    # ---- 4. 原始 SOAP ----
    for label, service, action, args in REQUESTS:
        url = control_url(be, service)
        log(u"")
        log(u"=== 3) %s 原始返回（%s）===" % (label, url or "无地址"))
        if not url:
            log(u"  该后端拿不到此服务的控制地址，跳过")
            continue
        try:
            raw = http.soap_call(url, service, action, args)
            root = http.parse_xml(raw, lenient=False)
            pretty = (http.ET.tostring(root, encoding="unicode") if root
                      else raw)
            log(pretty)
        except Exception as exc:
            log(u"  请求失败: %r" % (exc,))

    # ---- 5. 解析结果 ----
    dump_info(log, be, "4) 解析结果")

    # ---- 6. 协调器（仅 Sonos 多房间）----
    if speakers.CAN_COORDINATOR in be.capabilities:
        log(u"")
        log(u"=== 5) 主音箱（协调器）===")
        try:
            got = be.coordinator()
            if got:
                log(u"  需要跟随: %s (%s)" % (got[1] or "", got[0]))
                be2 = speakers.open_backend(be.kind, got[0], name=got[1] or "")
                dump_info(log, be2, "主音箱")
            else:
                log(u"  无需跟随（当前就是主音箱，或读不到拓扑）")
        except Exception as exc:
            log(u"  失败: %r" % (exc,))

    log(u"")
    log(u"完成 -> " + OUT_PATH)
    log.close()


if __name__ == "__main__":
    main()
