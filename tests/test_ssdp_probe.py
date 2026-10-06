# -*- coding: utf-8 -*-
"""SSDP 探测：同一请求要重发（UDP 丢包容错），响应要正确解析与去重。

用假 socket 替换真实网络：不依赖局域网里真的有设备。

跑法（项目根目录）：
    python tests/test_ssdp_probe.py
    pytest tests/test_ssdp_probe.py
"""

import os
import socket
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakers import discovery  # noqa: E402


class FakeSock(object):
    """按脚本吐响应；没有响应了就抛 socket.timeout（同真实收包超时）。"""

    def __init__(self, responses):
        self.sent = []
        self.responses = list(responses)

    def setsockopt(self, *args):
        pass

    def settimeout(self, *args):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, size):
        if self.responses:
            return self.responses.pop(0)
        raise socket.timeout()

    def close(self):
        pass


def _resp(ip, loc, st="urn:schemas-upnp-org:device:ZonePlayer:1"):
    head = "HTTP/1.1 200 OK\r\nLOCATION: %s\r\nST: %s\r\n\r\n" % (loc, st)
    return head.encode("utf-8"), (ip, 1900)


def test_retransmits_within_timeout():
    """一个 timeout 窗口里至少要发两轮（每轮 2 个 ST）——丢包容错的基础。"""
    fake = FakeSock([])
    with mock.patch.object(discovery.socket, "socket", lambda *a, **k: fake):
        out = discovery._ssdp_probe(2.4)
    assert out == []
    assert len(fake.sent) >= 4, len(fake.sent)
    assert all(addr == discovery.SSDP_ADDR for _, addr in fake.sent)


def test_parses_response():
    loc = "http://192.168.1.20:1400/xml/device_description.xml"
    fake = FakeSock([_resp("192.168.1.20", loc)])
    with mock.patch.object(discovery.socket, "socket", lambda *a, **k: fake):
        out = discovery._ssdp_probe(1.0)
    assert len(out) == 1
    assert out[0]["ip"] == "192.168.1.20"
    assert out[0]["location"] == loc
    assert any("zoneplayer" in st.lower() for st in out[0]["st"])


def test_dedup_same_device():
    """同一设备回多个 ST：合并成一条，ST 全部记下。"""
    loc = "http://192.168.1.20:1400/xml/device_description.xml"
    fake = FakeSock([_resp("192.168.1.20", loc),
                     _resp("192.168.1.20", loc, st="upnp:rootdevice")])
    with mock.patch.object(discovery.socket, "socket", lambda *a, **k: fake):
        out = discovery._ssdp_probe(1.0)
    assert len(out) == 1
    assert len(out[0]["st"]) == 2


TESTS = (
    test_retransmits_within_timeout,
    test_parses_response,
    test_dedup_same_device,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
