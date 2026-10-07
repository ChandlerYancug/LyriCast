# -*- coding: utf-8 -*-
"""歌词 / 封面磁盘缓存。

同一首歌再放时直接读本地，秒出，不用等网络（也不用再"黑一会"）。

目录结构：
    cache/
      lyrics/<key>.json     {"ts": 时间戳, "result": 歌词结果 或 null}
      art/<key>.img         封面原图

- 缓存 key 用「歌名 / 歌手 / 时长」做摘要（时长按 5 秒取整，
  既容得下上报误差，也能区分不同版本）；
- "没搜到"也会缓存（默认 7 天），避免每次都白跑一轮接口；
- 封面缓存最多保留 300 张，超出按最久未用淘汰。
"""

import hashlib
import io
import json
import os
import re
import time

from speakers import paths as app_paths

# exe 模式在用户目录（%LOCALAPPDATA%\LyriCast\cache）；源码运行就在项目里
CACHE_DIR = app_paths.cache_dir()
LYRICS_DIR = os.path.join(CACHE_DIR, "lyrics")
ART_DIR = os.path.join(CACHE_DIR, "art")

NEGATIVE_TTL = 7 * 24 * 3600      # “没找到”保留 7 天
ART_MAX_FILES = 300               # 封面最多缓存张数
_CACHE_VERSION = "5"              # 核验/解析逻辑升级时 +1，旧缓存自动失效
                                  # v5：丢掉网易云开头的“作词/作曲/编曲…”制作人员行

_WS = re.compile(r"\s+")


def _norm(text):
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return _WS.sub(" ", text.strip().lower())


def _key(*parts):
    raw = "|".join(_norm(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _ensure_dirs():
    for d in (LYRICS_DIR, ART_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 歌词
# --------------------------------------------------------------------------- #
def lyrics_key(title, artist, album="", duration=0.0):
    try:
        # 按 5 秒取整：既容得下上报误差，又能区分不同版本（通常差 10 秒以上）
        dur = int(round(float(duration) / 5.0) * 5) if duration else 0
    except (TypeError, ValueError):
        dur = 0
    return _key(title, artist, dur, _CACHE_VERSION)


def load_lyrics(title, artist, album="", duration=0.0):
    """命中返回歌词 dict；已知没有则返回 {}；完全没缓存返回 None。"""
    path = os.path.join(LYRICS_DIR,
                        lyrics_key(title, artist, album, duration) + ".json")
    try:
        with io.open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:
        return None
    result = data.get("result")
    if result is None:
        if time.time() - float(data.get("ts") or 0) > NEGATIVE_TTL:
            return None               # 过期了，重新搜一次
        return {}
    return result


def save_lyrics(title, artist, album, duration, result):
    _ensure_dirs()
    path = os.path.join(LYRICS_DIR,
                        lyrics_key(title, artist, album, duration) + ".json")
    try:
        with io.open(path, "w", encoding="utf-8") as fp:
            json.dump({"ts": time.time(), "result": result},
                      fp, ensure_ascii=False)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 封面
# --------------------------------------------------------------------------- #
def art_key(title, artist, album=""):
    # 同一张专辑的封面是同一张，所以优先用 专辑|歌手
    if album:
        return _key(artist, album)
    return _key(title, artist)


def load_art(title, artist, album=""):
    key = art_key(title, artist, album)
    for ext in (".img", ".jpg", ".png"):
        path = os.path.join(ART_DIR, key + ext)
        try:
            if os.path.isfile(path):
                with open(path, "rb") as fp:
                    data = fp.read()
                if data:
                    return data
        except OSError:
            pass
    return None


def save_art(title, artist, album, data):
    if not data:
        return
    _ensure_dirs()
    path = os.path.join(ART_DIR, art_key(title, artist, album) + ".img")
    try:
        with open(path, "wb") as fp:
            fp.write(data)
    except OSError:
        return
    _prune_art()


def _prune_art():
    try:
        files = [os.path.join(ART_DIR, n) for n in os.listdir(ART_DIR)]
        files = [p for p in files if os.path.isfile(p)]
        if len(files) <= ART_MAX_FILES:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[:len(files) - ART_MAX_FILES]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 杂项
# --------------------------------------------------------------------------- #
def _count(d):
    try:
        return len([n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))])
    except OSError:
        return 0


def _size(d):
    total = 0
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                total += os.path.getsize(p)
    except OSError:
        pass
    return total


def stats():
    return {
        "lyrics": _count(LYRICS_DIR),
        "art": _count(ART_DIR),
        "bytes": _size(LYRICS_DIR) + _size(ART_DIR),
    }


def clear():
    removed = 0
    for d in (LYRICS_DIR, ART_DIR):
        try:
            for n in os.listdir(d):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed
