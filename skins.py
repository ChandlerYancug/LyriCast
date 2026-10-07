# -*- coding: utf-8 -*-
"""每首歌的彩胶记忆：**手动换过**的彩胶会被记住。

规则（见 `vinyl.for_cover_color` 与托盘菜单「换一张彩胶」/ `M` 键）：

- 没换过的歌：按封面主色自动配（色调定色系、按歌名在色系里固定挑一款）——
  同一个封面、同一首歌永远同色，不必存；
- 用户手动换过的歌：记进 `config.json` 的 `"song_skins"`，下次放这首直接恢复；
- 手动换只影响这一首，其它没记住的歌继续按各自封面自动配。

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
    """这首歌记住的手动选择 -> {"vinyl": id, "manual": True}；没记过返回空。"""
    if not key:
        return {}
    item = _table(cfg).get(key)
    return dict(item) if isinstance(item, dict) else {}


def remember(cfg, key, vinyl=None):
    """记下这首歌手动换的彩胶；超过上限丢最早的。"""
    if not key or not vinyl:
        return
    t = _table(cfg)
    item = dict(t.get(key) or {})
    item["vinyl"] = vinyl
    item["manual"] = True            # 标记：手动换的（不会被迁移清掉）
    t.pop(key, None)                 # 重新插入 → 变成“最新”
    t[key] = item
    while len(t) > MAX_ENTRIES:
        t.pop(next(iter(t)))


def migrate(cfg):
    """旧格式升级（v1.0）：只保留“能证明是手动换过”的彩胶。

    老版本把自动配的结果也存了进来，和手动换的混在一起、无法区分；
    旧版手动换过唱臂的条目一定带 `arm`，以它为准 ——
    其余条目清掉，改由 `vinyl.for_cover_color` 重新实时配。
    保留下来的会打上 `manual` 标记（幂等：再跑不会误会成自动的）。
    返回清掉的条目数（在内存里改 cfg，随下次存档生效）。
    """
    t = cfg.get(_TABLE_KEY)
    if not isinstance(t, dict):
        return 0
    removed = 0
    for key in list(t.keys()):
        item = t.get(key)
        if not isinstance(item, dict):
            t.pop(key, None)                   # 脏数据
            removed += 1
            continue
        vinyl_id = item.get("vinyl")
        keep = bool(vinyl_id) and bool(item.get("manual") or item.get("arm"))
        if keep:
            t[key] = {"vinyl": vinyl_id, "manual": True}
        else:
            t.pop(key, None)
            removed += 1
    return removed
