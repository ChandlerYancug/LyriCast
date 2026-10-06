# -*- coding: utf-8 -*-
"""唱臂皮肤表：键齐全、全局选择正确（config 优先，未知值回退默认）、轮换走遍全部。

跑法（项目根目录）：
    python tests/test_tonearm.py
    pytest tests/test_tonearm.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tonearm  # noqa: E402

_REQUIRED = ("id", "name", "desc", "shape", "tube_edge", "tube_body",
             "tube_gloss", "tube_spec", "shell_col", "cart", "accent",
             "cw_col", "pivot_col")


def test_skins_have_required_keys():
    assert len(tonearm.SKINS) >= 5
    ids = set()
    for s in tonearm.SKINS:
        for key in _REQUIRED:
            assert key in s, (s.get("id"), key)
        assert s["shape"] in ("s", "j", "straight"), s["shape"]
        assert s["id"] not in ids, "皮肤 id 重复：%s" % s["id"]
        ids.add(s["id"])
    assert tonearm.DEFAULT_ID in ids


def test_pick_prefers_config_then_default():
    assert tonearm.pick({})["id"] == tonearm.DEFAULT_ID
    want = tonearm.SKINS[-1]["id"]
    assert tonearm.pick({"tonearm_skin": want})["id"] == want
    # 未知值回退默认（不再按歌随机换）
    assert tonearm.pick({"tonearm_skin": "no-such"})["id"] == tonearm.DEFAULT_ID


def test_by_id_lookup():
    assert tonearm.by_id(tonearm.DEFAULT_ID)["name"]
    assert tonearm.by_id("nope") is None
    assert tonearm.by_id(None) is None


def test_next_of_cycles_everything():
    skin = tonearm.SKINS[0]
    seen = set()
    for _ in range(len(tonearm.SKINS)):
        skin = tonearm.next_of(skin)
        seen.add(skin["id"])
    assert len(seen) == len(tonearm.SKINS)


TESTS = (
    test_skins_have_required_keys,
    test_pick_prefers_config_then_default,
    test_by_id_lookup,
    test_next_of_cycles_everything,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
