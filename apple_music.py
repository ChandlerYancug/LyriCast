# -*- coding: utf-8 -*-
"""Apple Music 歌词源：TTML 格式，每行带精确的起止时间（官方数据）。

凭证（两个都要）：
  1. developer token：网页端公开的 JWT，本模块自动抓取并缓存 30 分钟；
  2. media-user-token：你登录 Apple Music 后的凭证，放在项目目录 am_token.txt
     （过期后重新登录网页版 music.apple.com，再把 cookie 里的值更新进去）。

歌词接口只在「账号所在区」可用（storefront，如 in），可用 config.json 的
apple_storefront 指定；缺省自动查询账号区。

返回结构与其它源一致，另加两个字段：
  ends  —— 每行结束时间（秒），填充进度用它精确对齐（不再是估算）；
  words —— 有 syllable-lyrics（逐词）时每行 [(开始秒, 词)]，没有则为 None。
"""

import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

import lyrics          # 复用相似度 / 占位检测 / 翻译合并（本模块延迟导入，无循环）
from speakers import paths as app_paths

TOKEN_FILE = app_paths.token_path()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_API = "https://amp-api.music.apple.com"
_PAGES = "https://music.apple.com/us/browse"
_NS = "{http://www.w3.org/ns/ttml}"
_XM = "{http://music.apple.com/lyric-ttml-internal}"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")

_dev = {"token": "", "ts": 0.0}       # developer token 内存缓存
_DEV_TTL = 1800.0                     # 30 分钟
_sf = {"value": ""}                   # storefront 内存缓存

_SESS_DIRECT = requests.Session()      # 直连（绕过系统代理）
_SESS_DIRECT.trust_env = False
_SESS_PROXY = requests.Session()       # 回退：跟随系统代理


def _get(url, headers=None, params=None, timeout=8):
    """GET 优先直连；网络层失败时回退系统代理一次。

    部分用户的系统代理设置会残留（代理软件已关闭），requests 默认
    跟随系统代理会直接连不上，而 Apple 接口国内直连可用。
    """
    try:
        return _SESS_DIRECT.get(url, headers=headers, params=params,
                                timeout=timeout)
    except requests.RequestException as exc_direct:
        try:
            return _SESS_PROXY.get(url, headers=headers, params=params,
                                   timeout=timeout)
        except requests.RequestException:
            raise exc_direct


# --------------------------------------------------------------------------- #
# 凭证
# --------------------------------------------------------------------------- #
def _load_user_token():
    try:
        with io.open(TOKEN_FILE, encoding="utf-8") as fp:
            return fp.read().strip()
    except OSError:
        return ""


def save_user_token(token):
    """把 media-user-token 写进 am_token.txt（exe 模式下在用户目录）。"""
    token = (token or "").strip()
    if not token:
        return False
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with io.open(TOKEN_FILE, "w", encoding="utf-8") as fp:
            fp.write(token)
        return True
    except OSError:
        return False


def find_browser_token():
    """从浏览器里读 media-user-token（不启动任何其它进程）。

    返回 (token, 说明列表)。GUI 的“自动获取”和 get_apple_token.py
    共用这一份逻辑；应用内调用不会出现命令行窗口。
    """
    logs = []
    try:
        import browser_cookie3 as bc
    except ImportError:
        return "", ["缺少 browser_cookie3（装依赖时会一起装上）"]

    def _cookies(fn, label):
        try:
            return fn(domain_name="music.apple.com")
        except TypeError:                # 旧版没有 domain_name 参数
            return fn()
        except Exception as exc:
            logs.append("[%s] 打不开 cookie：%s" % (label, exc))
            return None

    for fn, label in ((bc.chrome, "Chrome"), (bc.edge, "Edge"),
                      (bc.firefox, "Firefox")):
        cj = _cookies(fn, label)
        if cj is None:
            continue
        seen = 0
        for c in cj:
            if "music.apple.com" in (c.domain or ""):
                seen += 1
                if c.name == "media-user-token" and c.value:
                    logs.append("[%s] 找到 media-user-token（%d 字符）"
                                % (label, len(c.value)))
                    return c.value, logs
        logs.append("[%s] 没有 media-user-token（该域 cookie 数：%d）"
                    % (label, seen))
    return "", logs


def _fetch_dev_token(timeout=8):
    try:
        r = _get(_PAGES, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        tokens = _JWT.findall(r.text)
        if not tokens:
            for u in re.findall(r'src="(/assets/[^"]+\.js)"', r.text)[:4]:
                js = _get("https://music.apple.com" + u,
                          headers={"User-Agent": UA},
                          timeout=timeout).text
                tokens = _JWT.findall(js)
                if tokens:
                    break
        return tokens[0] if tokens else ""
    except requests.RequestException:
        return ""


def _dev_token(timeout=8):
    if _dev["token"] and time.time() - _dev["ts"] < _DEV_TTL:
        return _dev["token"]
    tok = _fetch_dev_token(timeout)
    if tok:
        _dev["token"] = tok
        _dev["ts"] = time.time()
    return tok or _dev["token"]       # 抓取失败就先用旧的（可能还没过期）


def _headers(user, dev):
    return {
        "Authorization": "Bearer " + dev,
        "media-user-token": user,
        "Origin": "https://music.apple.com",
        "Referer": "https://music.apple.com/",
        "User-Agent": UA,
    }


def _storefront(headers, timeout=8):
    if _sf["value"]:
        return _sf["value"]
    sf = ""
    try:
        with io.open(app_paths.config_path(), encoding="utf-8") as fp:
            sf = (json.load(fp).get("apple_storefront") or "").strip()
    except (OSError, ValueError):
        sf = ""
    if not sf:
        try:
            r = _get(_API + "/v1/me/storefront", headers=headers,
                     timeout=timeout)
            if r.status_code == 200:
                sf = ((r.json().get("data") or [{}])[0].get("id") or "").strip()
        except (requests.RequestException, ValueError):
            sf = ""
    _sf["value"] = sf or "in"
    return _sf["value"]


# --------------------------------------------------------------------------- #
# TTML 解析
# --------------------------------------------------------------------------- #
def _parse_time(value):
    """TTML 时间："8.222" / "1:01.842" -> 秒。"""
    if not value:
        return None
    value = value.strip()
    try:
        if ":" in value:
            mm, rest = value.rsplit(":", 1)
            return int(mm) * 60 + float(rest)
        return float(value)
    except ValueError:
        return None


def _element_text(el):
    """元素内部全部文本（含嵌套 span，如背景和声），不含自身 tail。"""
    return "".join(el.itertext())


def parse_ttml(ttml):
    """TTML -> (lines, ends, words, trs)。

    lines: [(begin, text)]；ends: [end...]；
    words: [[(begin, end, 词)...]...] 或 None（逐词，来自 syllable-lyrics）；
    trs:   [译文...] 与 lines 等长（subtitle 翻译）；`replacement` 型
           译文（简繁转换等）已在内部直接替换主行文本。
    """
    try:
        root = ET.fromstring(ttml)
    except ET.ParseError:
        return [], [], None, []
    body = root.find(".//" + _NS + "body")
    if body is None:
        return [], [], None, []

    lines, ends, words, keys = [], [], [], []
    any_words = False
    for p in body.iter(_NS + "p"):
        begin = _parse_time(p.get("begin"))
        if begin is None:
            continue
        end = _parse_time(p.get("end"))
        spans = list(p.iter(_NS + "span"))
        wlist = []
        if spans:
            parts = []
            if p.text:
                parts.append(p.text)
            for sp in spans:
                chunk = _element_text(sp)
                parts.append(chunk)
                if sp.tail:
                    parts.append(sp.tail)      # 词间空格等在 tail 里
                if not chunk:
                    continue
                wlist.append((_parse_time(sp.get("begin")),
                              _parse_time(sp.get("end")), chunk))
            text = "".join(parts)
        else:
            text = p.text or ""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if wlist:
            # 缺 begin/end 的用前后词或行时间回填
            fixed = []
            cursor = begin
            for b, e, w in wlist:
                if b is None:
                    b = cursor
                fixed.append([b, e, w])
                cursor = b
            for j in range(len(fixed)):
                if fixed[j][1] is None:
                    fixed[j][1] = (fixed[j + 1][0] if j + 1 < len(fixed)
                                   else (end if end is not None else fixed[j][0]))
            wlist = [(b, e, w) for b, e, w in fixed]
            any_words = True
        lines.append((begin, text))
        ends.append(end if end is not None else begin)
        words.append(wlist)
        keys.append(p.get(_XM + "key") or "")

    # 译文：<translation xml:lang="zh-..."><text for="L1">...</text>
    trs = [""] * len(lines)
    key_idx = {k: i for i, k in enumerate(keys) if k}
    trans_map, trans_type = {}, ""
    for tr in root.iter(_XM + "translation"):
        lang = (tr.get(_XML_LANG) or "").lower()
        mp = {}
        for tx in tr.iter(_XM + "text"):
            k = tx.get("for") or ""
            if k:
                mp[k] = re.sub(r"\s+", " ", _element_text(tx)).strip()
        if not any(mp.values()):
            continue
        if lang.startswith("zh") or not trans_map:
            trans_map, trans_type = mp, (tr.get("type") or "")
        if lang.startswith("zh"):
            break
    if trans_map:
        if trans_type == "replacement":
            for k, v in trans_map.items():
                i = key_idx.get(k)
                if i is not None and v:
                    lines[i] = (lines[i][0], v)
        else:
            for k, v in trans_map.items():
                i = key_idx.get(k)
                if i is not None and v:
                    trs[i] = v
    return lines, ends, (words if any_words else None), trs


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
def _search(title, artist, storefront, headers, timeout, limit=8):
    term = ("%s %s" % (title, artist)).strip()
    r = _get(_API + "/v1/catalog/%s/search" % storefront,
             headers=headers,
             params={"term": term, "types": "songs", "limit": limit},
             timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("apple: token rejected (%d)" % r.status_code)
    if r.status_code != 200:
        return []
    try:
        data = ((r.json().get("results") or {}).get("songs") or {}).get("data")
    except ValueError:
        return []
    return data or []


def _rank(songs, title, artist, duration):
    def dur_of(song):
        ms = (song.get("attributes") or {}).get("durationInMillis")
        return float(ms) / 1000.0 if ms else None

    def score(song):
        attrs = song.get("attributes") or {}
        d = dur_of(song)
        err = abs(d - duration) if (d and duration) else 6.0
        return (err
                + (1.0 - lyrics._sim(attrs.get("name"), title)) * 10.0
                + (1.0 - lyrics._sim(attrs.get("artistName"), artist)) * 3.0)

    return sorted(songs, key=score)


def _fetch_attributes(song_id, storefront, headers, timeout):
    r = _get(_API + "/v1/catalog/%s/songs/%s/lyrics" % (storefront, song_id),
             headers=headers,
             params={"l[lyrics]": "zh-Hans", "extend": "ttmlLocalizations"},
             timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("apple: token rejected (%d)" % r.status_code)
    if r.status_code != 200:
        return None
    try:
        data = r.json().get("data") or []
    except ValueError:
        return None
    if not data:
        return None
    return data[0].get("attributes") or None


def _fetch_syllable(song_id, storefront, headers, timeout):
    """逐词歌词独立端点；没有该资源时返回 None。"""
    r = _get(_API + "/v1/catalog/%s/songs/%s/syllable-lyrics"
             % (storefront, song_id),
             headers=headers,
             params={"l[lyrics]": "zh-Hans", "extend": "ttmlLocalizations"},
             timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("apple: token rejected (%d)" % r.status_code)
    if r.status_code != 200:
        return None
    try:
        data = r.json().get("data") or []
    except ValueError:
        return None
    if not data:
        return None
    attrs = data[0].get("attributes") or None
    return attrs


def _pick_ttml(attrs):
    """取 attrs 里的 TTML 正文；主字段为空时回退本地化（部分资源只在本地化里）。"""
    ttml = attrs.get("ttml")
    if ttml:
        return ttml
    loc = attrs.get("ttmlLocalizations")
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        low = {str(k).lower(): v for k, v in loc.items()}
        for lang in ("en-us", "en-gb", "en", "zh-hans", "zh"):
            if low.get(lang):
                return low[lang]
        for v in loc.values():
            if v:
                return v
    return ""


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def from_apple_music(title, artist, album=None, duration=None, timeout=8,
                     max_candidates=3):
    if not title:
        return None
    user = _load_user_token()
    if not user:
        return None
    dev = _dev_token(timeout)
    if not dev:
        return None
    headers = _headers(user, dev)
    storefront = _storefront(headers, timeout)

    songs = _search(title, artist, storefront, headers, timeout)
    for song in _rank(songs, title, artist, duration)[:max_candidates]:
        # 优先逐词（syllable-lyrics），拿不到再退普通逐行（lyrics）。
        attrs = _fetch_syllable(song["id"], storefront, headers, timeout)
        lines, ends, words, trs = [], [], None, []
        if attrs:
            lines, ends, words, trs = parse_ttml(_pick_ttml(attrs))
            if not lines or lyrics._looks_placeholder([t for _, t in lines]):
                attrs = None
        if attrs is None:
            attrs = _fetch_attributes(song["id"], storefront, headers, timeout)
            if not attrs:
                continue
            lines, ends, words, trs = parse_ttml(_pick_ttml(attrs))
            if not lines or lyrics._looks_placeholder([t for _, t in lines]):
                continue
        rows = [(t, txt, (trs[i] if i < len(trs) else ""))
                for i, (t, txt) in enumerate(lines)]
        return {"synced": True, "lines": rows, "ends": ends, "words": words,
                "plain": [], "source": "apple"}
    return None
