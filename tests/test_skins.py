# -*- coding: utf-8 -*-
"""皮肤记忆（skins.py）：单首歌的选择能存能取，全局选择不再按歌随机。

跑法（项目根目录）：
    python tests/test_skins.py
    pytest tests/test_skins.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skins  # noqa: E402
import tonearm  # noqa: E402
import vinyl  # noqa: E402


def test_recall_empty_by_default():
    cfg = {}
    assert skins.recall(cfg, "A|B") == {}
    assert skins.recall(cfg, "") == {}


def test_remember_and_recall_roundtrip():
    cfg = {}
    skins.remember(cfg, "A|B", vinyl="clear-red", arm="carbon")
    assert skins.recall(cfg, "A|B") == {"vinyl": "clear-red", "arm": "carbon"}
    assert skins.recall(cfg, "C|D") == {}


def test_remember_partial_keeps_other_field():
    cfg = {}
    skins.remember(cfg, "A|B", vinyl="black")
    skins.remember(cfg, "A|B", arm="mirror")
    assert skins.recall(cfg, "A|B") == {"vinyl": "black", "arm": "mirror"}


def test_track_key_normalizes_spaces():
    assert skins.track_key("  Song ", " Artist ") == "Song|Artist"
    assert skins.track_key(None, None) == "|"


def test_prunes_oldest_over_limit():
    cfg = {}
    for i in range(skins.MAX_ENTRIES + 25):
        skins.remember(cfg, "song-%d|a" % i, arm="carbon")
    table = cfg["song_skins"]
    assert len(table) == skins.MAX_ENTRIES
    assert "song-0|a" not in table                 # 最早的被丢掉
    assert "song-%d|a" % (skins.MAX_ENTRIES + 24) in table


def test_global_pick_no_random_per_song():
    """全局选择只看 config：没配就用默认，不随歌变化。"""
    assert tonearm.pick({})["id"] == tonearm.DEFAULT_ID
    assert tonearm.pick({"tonearm_skin": "midnight"})["id"] == "midnight"
    assert vinyl.pick({})["id"] == "black"
    assert vinyl.pick({"vinyl_material": "clear-red"})["id"] == "clear-red"
    assert vinyl.pick({"vinyl_material": "no-such"})["id"] == "black"
    assert vinyl.by_id("nope") is None


TESTS = (
    test_recall_empty_by_default,
    test_remember_and_recall_roundtrip,
    test_remember_partial_keeps_other_field,
    test_track_key_normalizes_spaces,
    test_prunes_oldest_over_limit,
    test_global_pick_no_random_per_song,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
