# -*- coding: utf-8 -*-
"""回归测试：网易云对 OST/专辑类歌会把「作词 / 作曲 / 编曲…」制作人员表
放在歌词最前面 —— 这不是歌词，必须丢掉（否则界面看起来完全乱掉）。

只丢**开头**连续的一小段（最多 _strip_credits 的 max_drop 行）：
歌词中间真出现“作词 :”这种字样的，不动。

跑法（项目根目录）：
    python tests/test_lyrics_credits.py
    pytest tests/test_lyrics_credits.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lyrics import _strip_credits, parse_lrc  # noqa: E402


def _texts(rows):
    return [t for _, t in rows]


def test_leading_credits_dropped():
    lrc = ("[00:00.00]作词 : Lin-Manuel Miranda\n"
           "[00:01.00]作曲 : Lin-Manuel Miranda\n"
           "[00:02.00]编曲 : Alex Lacamoire\n"
           "[00:03.00]指挥家 : Alex Lacamoire\n"
           "[00:10.00]How does a bastard, orphan, son of a whore\n")
    assert _texts(_strip_credits(parse_lrc(lrc))) == [
        "How does a bastard, orphan, son of a whore"]


def test_english_credits_dropped():
    lrc = ("[00:00.00]Produced by: Someone\n"
           "[00:01.00]Mixed by: Someone Else\n"
           "[00:02.00]Guitar: A Player\n"
           "[00:03.00]Real lyric line\n")
    assert _texts(_strip_credits(parse_lrc(lrc))) == ["Real lyric line"]


def test_normal_lyrics_untouched():
    lrc = "[00:00.00]Hello, it's me\n[00:01.00]I was wondering\n"
    rows = parse_lrc(lrc)
    assert _strip_credits(rows) == rows


def test_only_leading_credits_dropped():
    lrc = ("[00:00.00]Real first line\n"
           "[00:01.00]作曲 : Mid-song credit stays\n")
    assert _texts(_strip_credits(parse_lrc(lrc))) == [
        "Real first line", "作曲 : Mid-song credit stays"]


def test_max_drop_cap():
    lines = ["[00:%02d.00]作词 : Person %d" % (i, i) for i in range(30)]
    lines.append("[00:31.00]Actual lyric")
    rows = parse_lrc("\n".join(lines))
    # 最多丢 12 行，剩下的原样保留（防止把整首纯文本歌词一口气丢光）
    assert len(_strip_credits(rows)) == len(rows) - 12


TESTS = (
    test_leading_credits_dropped,
    test_english_credits_dropped,
    test_normal_lyrics_untouched,
    test_only_leading_credits_dropped,
    test_max_drop_cap,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
