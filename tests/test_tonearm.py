# -*- coding: utf-8 -*-
"""唱臂（tonearm.py）：唯一的这支臂键齐全、能画出来（不再有换肤逻辑）。

跑法（项目根目录）：
    python tests/test_tonearm.py
    pytest tests/test_tonearm.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tonearm  # noqa: E402

_APP = None


def _ensure_app():
    """保持 QApplication 的全局引用（只写表达式会被垃圾回收）。"""
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP

_REQUIRED = ("id", "name", "desc", "shape", "tube_edge", "tube_body",
             "tube_gloss", "tube_spec", "shell_col", "cart", "accent",
             "cw_col", "pivot_col")


def test_skin_has_required_keys():
    s = tonearm.SKIN
    for key in _REQUIRED:
        assert key in s, key
    assert s["shape"] in ("s", "j", "straight"), s["shape"]


def test_draw_smoke():
    """不弹窗把唱臂画到 QImage 上：出错了这里就会炸。"""
    _ensure_app()
    from PyQt6.QtGui import QImage, QPainter

    img = QImage(640, 480, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    tonearm.draw_static(p, 480.0, 120.0, 120.0)
    tonearm.draw(p, 120.0, 300.0)
    p.end()
    assert not img.isNull()


TESTS = (
    test_skin_has_required_keys,
    test_draw_smoke,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
