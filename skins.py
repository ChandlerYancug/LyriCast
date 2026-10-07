# -*- coding: utf-8 -*-
"""每首歌的彩胶记忆：用户为某首歌挑过的彩胶会被记住。

规则（托盘菜单「换一张彩胶」与 `M` 键都走这套）：

- 用户在哪首歌里换了彩胶 → 记进 `config.json` 的 `"song_skins"`；
- 切到别的歌**不会自动乱换**：没有记忆的歌用全局选择
  （`vinyl_material`，也就是用户上一次挑的那款）；
- 再放回那首歌唱过的歌 → 自动恢复当时为它挑的彩胶。

存储说明：放在 `config.json` 而不是 `cache/` —— 清空歌词/封面缓存时
不会把皮肤选择一起清掉。最多记 `MAX_ENTRIES` 首，超出丢最早的。
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
