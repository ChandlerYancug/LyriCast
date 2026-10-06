# -*- coding: utf-8 -*-
"""唱臂皮肤表：键齐全、选择稳定（同一首歌跨进程固定）、轮换能走遍全部。

跑法（项目根目录）：
    python tests/test_tonearm.py
    pytest tests/test_tonearm.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tonearm  # noqa: E402

_REQUIRED = ("id", "name", "desc", "shape", "tube_edge", "tube_body",
             "tube_hi", "shell", "shell_col", "cart", "accent", "cw",
             "pivot")


def test_skins_have_required_keys():
    assert len(tonearm.SKINS) >= 6
    ids = set()
    for s in tonearm.SKINS:
        for key in _REQUIRED:
            assert key in s, (s.get("id"), key)
        assert s["shape"] in ("s", "j", "straight"), s["shape"]
        assert s["id"] not in ids, "皮肤 id 重复：%s" % s["id"]
        ids.add(s["id"])


def test_pick_is_deterministic_and_config_wins():
    a = tonearm.pick({}, "song|artist")
    b = tonearm.pick({"tonearm_skin": "auto"}, "song|artist")
    assert a["id"] == b["id"]                 # 同一首歌固定一支
    want = tonearm.SKINS[-1]["id"]
    assert tonearm.pick({"tonearm_skin": want}, "song")["id"] == want
    # 未知值当作 auto 处理（同一 key 结果一致）
    assert tonearm.pick({"tonearm_skin": "no-such"},
                        "song|artist")["id"] == a["id"]


def test_pick_varies_across_songs():
    ids = {tonearm.pick({}, "song-%d|artist" % i)["id"] for i in range(12)}
    assert len(ids) >= 3                      # 12 首歌至少落到 3 支不同的臂


def test_next_of_cycles_everything():
    skin = tonearm.SKINS[0]
    seen = set()
    for _ in range(len(tonearm.SKINS)):
        skin = tonearm.next_of(skin)
        seen.add(skin["id"])
    assert len(seen) == len(tonearm.SKINS)


TESTS = (
    test_skins_have_required_keys,
    test_pick_is_deterministic_and_config_wins,
    test_pick_varies_across_songs,
    test_next_of_cycles_everything,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
