# -*- coding: utf-8 -*-
"""端到端冒烟测试：假 DLNA 音箱 -> UpnpBackend -> SpeakerPoller -> Qt 信号。

验证泛化后的轮询链路:信号能带着曲目/位置/播放状态送达界面侧。
跑法（项目根目录）：
    python tests/test_poller_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402

import speakers  # noqa: E402
from main import SpeakerPoller  # noqa: E402
from test_upnp_backend import (  # noqa: E402
    ARTIST,
    TITLE,
    MockDlnaSpeaker,
)


def test_poller_emits_track_and_position():
    dev = MockDlnaSpeaker()
    try:
        app = QCoreApplication.instance() or QCoreApplication([])
        backend = speakers.open_backend(
            "upnp", "127.0.0.1",
            name="MockSpeaker", location=dev.url("/description.xml"))
        assert "control" in backend.capabilities

        poller = SpeakerPoller(backend, local_ip="127.0.0.1")
        got = {"track": None, "pos": [], "vol": [], "status": []}
        poller.track_changed.connect(lambda info: got.__setitem__("track", info))
        poller.position.connect(lambda s, p, prec: got["pos"].append(s))
        poller.volume_changed.connect(lambda v: got["vol"].append(v))
        poller.status.connect(lambda s: got["status"].append(s))

        poller.start()
        QTimer.singleShot(2600, app.quit)      # 给轮询几圈的机会（音量约 2s 读一次）
        app.exec()
        poller.stop()
        poller.wait(1500)

        assert got["track"], "没有收到 track_changed: %r" % (got["status"],)
        info = got["track"]
        assert info["title"] == TITLE, info
        assert info["artist"] == ARTIST, info
        assert info["album_art"].startswith("http://127.0.0.1:%d" % dev.port), info
        assert got["pos"], "没有收到 position"
        assert abs(got["pos"][-1] - 42.0) < 2.5, got["pos"][-1]
        assert got["vol"] and got["vol"][-1] == 37, got["vol"]
        print("  冒烟通过: title=%r artist=%r pos=%.1fs vol=%s"
              % (info["title"], info["artist"], got["pos"][-1], got["vol"][-1]))
    finally:
        dev.close()


if __name__ == "__main__":
    test_poller_emits_track_and_position()
    print("ALL PASSED")
