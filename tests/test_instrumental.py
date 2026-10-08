# -*- coding: utf-8 -*-
"""回归测试：纯音乐 / 伴奏 / 卡拉 OK 不去搜歌词（搜到的基本都不相干）。

跑法（项目根目录）：
    python tests/test_instrumental.py
    pytest tests/test_instrumental.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lyrics  # noqa: E402
from lyrics import is_instrumental  # noqa: E402


def test_instrumental_markers_hit():
    cases = (
        ("River Flows in You (Instrumental)", ""),
        ("Merry Christmas Mr. Lawrence", "ピアノ伴奏集"),
        ("卡农（纯音乐）", ""),
        ("告白气球 (伴奏)", ""),
        ("Song (Off Vocal)", ""),
        ("Track (Karaoke Version)", ""),
        ("Piano Man (Inst.)", ""),
        ("春の海 (インスト)", ""),
        ("No Scrubs (No Vocals)", ""),
    )
    for title, album in cases:
        assert is_instrumental(title, album), (title, album)


def test_vocal_titles_not_blocked():
    cases = (
        ("Instrument", ""),                # “instrument” ≠ “instrumental”
        ("Instrumentalist", ""),
        ("Live Forever", "Live 2012"),
        ("纯白", ""),
        ("River Flows in You", ""),
        ("Bohemian Rhapsody (Remastered 2011)", ""),
        ("", ""),
    )
    for title, album in cases:
        assert not is_instrumental(title, album), (title, album)


def test_fetch_ex_skips_providers_for_instrumental():
    def boom(*_a, **_k):
        raise RuntimeError("should not be called")

    old = lyrics._provider_funcs
    lyrics._provider_funcs = lambda: {"boom": boom}
    try:
        res, err = lyrics.fetch_ex("Track (Instrumental)", "A",
                                   providers=("boom",))
        assert res is None and err is False     # 没进搜索、也没报错
        res, err = lyrics.fetch_ex("Normal Song", "A", providers=("boom",))
        assert res is None and err is True      # 证明普通歌名确实进了搜索
    finally:
        lyrics._provider_funcs = old


TESTS = (
    test_instrumental_markers_hit,
    test_vocal_titles_not_blocked,
    test_fetch_ex_skips_providers_for_instrumental,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
