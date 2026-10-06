# -*- coding: utf-8 -*-
"""utf8mode：输出流应统一切成 UTF-8（中文 Windows 默认 GBK 的兜底）。

不碰真实控制台：用假流对象替换 sys.stdout / sys.stderr，只验证
“该切的时候切、已经是 UTF-8 就不动、切失败也绝不抛异常”。

跑法（项目根目录）：
    python tests/test_utf8mode.py
    pytest tests/test_utf8mode.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utf8mode import ensure_utf8  # noqa: E402


class FakeStream(object):
    def __init__(self, encoding):
        self.encoding = encoding
        self.calls = []

    def reconfigure(self, **kw):
        self.calls.append(kw)


def _run_with(out, err):
    """把 sys.stdout/stderr 换成假流后调用 ensure_utf8，再恢复原样。"""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        return ensure_utf8()
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def test_gbk_streams_switched():
    out, err = FakeStream("cp936"), FakeStream("gbk")
    assert _run_with(out, err) is True
    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_utf8_streams_untouched():
    out, err = FakeStream("utf-8"), FakeStream("UTF8")
    assert _run_with(out, err) is False
    assert out.calls == [] and err.calls == []


def test_none_stream_skipped():
    out = FakeStream("cp936")
    assert _run_with(out, None) is True
    assert out.calls and out.calls[0]["encoding"] == "utf-8"


def test_reconfigure_failure_is_silent():
    class Bad(object):
        encoding = "cp1252"

        def reconfigure(self, **kw):
            raise OSError("nope")

    assert _run_with(Bad(), None) is False


TESTS = (
    test_gbk_streams_switched,
    test_utf8_streams_untouched,
    test_none_stream_skipped,
    test_reconfigure_failure_is_silent,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
