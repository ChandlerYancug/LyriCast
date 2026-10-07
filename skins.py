# -*- coding: utf-8 -*-
"""每首歌的彩胶记忆：一首歌定下的颜色（自动配的、手动换的）会被记住。

规则（自动配见 `vinyl.for_cover_color`，手动换见托盘菜单「换一张彩胶」与 `M` 键）：

- 自动配 / 手动换的结果 → 记进 `config.json` 的 `"song_skins"`；
- 再放回这首歌 → 直接恢复上次的颜色，不会再重新选；
- 手动换只影响这一首，其它没记住的歌继续按各自封面主色自动配。

存储说明：放在 `config.json` 而不是 `cache/` —— 清空歌词/封面缓存时
不会把颜色选择一起清掉。最多记 `MAX_ENTRIES` 首，超出丢最早的。
"""

MAX_ENTRIES = 500
_TABLE_KEY = "song_skins"


def track_key(title, artist):
    """一首歌的键（和歌词缓存同一口径：歌名|歌手）。"""
    return "%s|%s" % ((title or "").strip(), (artist or "").strip())


def _table(cfg):
    t = cfg.get(_TABLE_KEY)
    if not isinstance(t, dict):
        t = {}
        cfg[_TABLE_KEY] = t
    return t


def recall(cfg, key):
    """这首歌记住的选择 -> {"vinyl": id}；没记过返回空 dict。"""
    if not key:
        return {}
    item = _table(cfg).get(key)
    return dict(item) if isinstance(item, dict) else {}


def remember(cfg, key, vinyl=None):
    """记下这首歌的彩胶选择；超过上限丢最早的。"""
    if not key or not vinyl:
        return
    t = _table(cfg)
    item = dict(t.get(key) or {})
    item["vinyl"] = vinyl
    t.pop(key, None)                 # 重新插入 → 变成“最新”
    t[key] = item
    while len(t) > MAX_ENTRIES:
        t.pop(next(iter(t)))
