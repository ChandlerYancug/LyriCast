# -*- coding: utf-8 -*-
"""彩胶记忆（skins.py）：单首歌的选择能存能取，全局选择不按歌随机。

跑法（项目根目录）：
    python tests/test_skins.py
    pytest tests/test_skins.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skins  # noqa: E402
import vinyl  # noqa: E402


def test_recall_empty_by_default():
    cfg = {}
    assert skins.recall(cfg, "A|B") == {}
    assert skins.recall(cfg, "") == {}


def test_remember_and_recall_roundtrip():
    cfg = {}
    skins.remember(cfg, "A|B", vinyl="clear-red")
    assert skins.recall(cfg, "A|B") == {"vinyl": "clear-red"}
    assert skins.recall(cfg, "C|D") == {}


def test_remember_ignores_empty_values():
    cfg = {}
    skins.remember(cfg, "A|B")
    skins.remember(cfg, "", vinyl="black")
    assert skins.recall(cfg, "A|B") == {}
    assert cfg.get("song_skins", {}) == {}


def test_track_key_normalizes_spaces():
    assert skins.track_key("  Song ", " Artist ") == "Song|Artist"
    assert skins.track_key(None, None) == "|"


def test_prunes_oldest_over_limit():
    cfg = {}
    for i in range(skins.MAX_ENTRIES + 25):
        skins.remember(cfg, "song-%d|a" % i, vinyl="black")
    table = cfg["song_skins"]
    assert len(table) == skins.MAX_ENTRIES
    assert "song-0|a" not in table                 # 最早的被丢掉
    assert "song-%d|a" % (skins.MAX_ENTRIES + 24) in table


def test_global_pick_defaults_to_black():
    """没定彩胶时用默认黑胶（不再按歌随机、也不再从 config 固定；
    按封面自动配见 tests/test_vinyl_color.py）。"""
    assert vinyl.pick({})["id"] == "black"
    assert vinyl.pick()["id"] == "black"
    assert vinyl.by_id("nope") is None


TESTS = (
    test_recall_empty_by_default,
    test_remember_and_recall_roundtrip,
    test_remember_ignores_empty_values,
    test_track_key_normalizes_spaces,
    test_prunes_oldest_over_limit,
    test_global_pick_defaults_to_black,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
