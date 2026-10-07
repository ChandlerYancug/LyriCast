# -*- coding: utf-8 -*-
"""歌词获取：网易云音乐（中文歌覆盖好）+ LRCLIB（欧美歌覆盖好）。

统一返回结构：
    {
        "synced": True/False,          # 是否有逐行时间轴
        "lines": [(t, text, trans)],   # synced 时 t 为秒；否则 t 无意义
        "plain": [str, ...],           # 无时间轴时的整段歌词
        "source": "netease" / "lrclib",
    }
"""

import re

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"

TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
OFFSET_RE = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.I)
META_RE = re.compile(r"^\[(ti|ar|al|by|re|ve|length):.*\]$", re.I)

# 网易云对“拿不到词”的歌会返回占位文本（最常见的一行“纯音乐，请欣赏”），
# 这不是歌词，需要核验掉。
_PLACEHOLDER_RE = re.compile(
    u"纯音乐|純音樂|请欣赏|請欣賞|没有填词|沒有填詞|暂无歌词|暫無歌詞|"
    u"no lyrics|instrumental",
    re.I,
)

# OST / 专辑类歌曲，网易云会把制作人员表放在歌词最前面（"作词 : …"）；
# 这不是歌词，会让界面看起来完全乱掉，开头的这类行要丢掉。
_CREDIT_RE = re.compile(
    u"^\\s*(作词|作曲|编曲|制作人|监制|出品|发行|录音师?|混音师?|母带|指挥家|"
    u"吉他|贝斯|低音吉他|鼓|鼓手|键盘|钢琴|弦乐|和声|人声|配唱|演唱|合声|"
    u"produced by|composer|lyricist|arranged by|mixed by|mastered by|"
    u"guitar|bass|drums?|piano|strings|vocals?)\\s*[:：]",
    re.I,
)


def _strip_credits(rows, max_drop=12):
    """丢掉开头的“作词/作曲/编曲/指挥家…”制作人员行（最多丢 max_drop 行）。"""
    i = 0
    while i < len(rows) and i < max_drop and _CREDIT_RE.match(rows[i][1]):
        i += 1
    return rows[i:] if i else rows


# --------------------------------------------------------------------------- #
# LRC 解析
# --------------------------------------------------------------------------- #
def parse_lrc(text):
    """LRC 文本 -> [(time_sec, text), ...]，按时间排序，丢弃空行。"""
    if not text:
        return []
    m = OFFSET_RE.search(text)
    offset = int(m.group(1)) / 1000.0 if m else 0.0

    rows = []
    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw or META_RE.match(raw.strip()):
            continue
        stamps = list(TIME_RE.finditer(raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        if not content:
            continue
        for st in stamps:
            mm, ss = int(st.group(1)), int(st.group(2))
            frac = st.group(3)
            t = mm * 60 + ss
            if frac:
                t += int(frac) / (1000.0 if len(frac) == 3 else 100.0)
            rows.append((t + offset, content))

    rows.sort(key=lambda x: x[0])
    return rows


def _attach_translation(orig, trans):
    """把翻译按时间就近合并到原文行上。"""
    if not trans:
        return [(t, txt, "") for t, txt in orig]

    out = []
    j = 0
    for t, txt in orig:
        best, best_d = "", 1.0
        while j < len(trans) and trans[j][0] < t - 1.0:
            j += 1
        for k in (j, j + 1):
            if 0 <= k < len(trans):
                d = abs(trans[k][0] - t)
                if d < best_d:
                    best, best_d = trans[k][1], d
        out.append((t, txt, best))
    return out


def _dedup_same_text(rows):
    """去掉连续重复行（很多 LRC 会重复）。"""
    out = []
    for row in rows:
        if out and out[-1][0] == row[0] and out[-1][1] == row[1]:
            continue
        out.append(row)
    return out


def _looks_placeholder(texts):
    """判断一组歌词行是不是“纯音乐，请欣赏”之类的占位文本。

    真歌词极少只有两三行，且正常歌词基本不会出现这些词；
    只有行数很少时命中关键词才判为占位，避免误杀。
    """
    rows = [t for t in (texts or []) if t and t.strip()]
    if not rows or len(rows) > 3:
        return False
    return bool(_PLACEHOLDER_RE.search(" ".join(rows)))


# --------------------------------------------------------------------------- #
# 网易云音乐
# --------------------------------------------------------------------------- #
_NETEASE_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
}


def _netease_candidates(title, artist, duration=None, timeout=8):
    """搜索并返回候选歌曲（按时长/歌名/歌手核验，最像的排前面）。"""
    url = "https://music.163.com/api/search/get/web"
    data = {
        "s": ("%s %s" % (title, artist)).strip(),
        "type": 1,
        "offset": 0,
        "limit": 10,
    }
    r = requests.post(url, data=data, headers=_NETEASE_HEADERS, timeout=timeout)
    r.raise_for_status()
    songs = ((r.json().get("result") or {}).get("songs")) or []
    if not songs:
        return []
    return _ranked_candidates(songs, title, artist, duration)


def _ranked_candidates(songs, title, artist, duration):
    """按时长误差 + 歌名/歌手相似度给候选排序。"""

    def dur_of(song):
        for key in ("duration", "dt"):
            if song.get(key):
                return float(song[key]) / 1000.0
        return None

    def score(song):
        d = dur_of(song)
        err = abs(d - duration) if (d and duration) else 6.0
        arts = song.get("artists") or song.get("ar") or []
        arts_name = " ".join((a or {}).get("name") or "" for a in arts)
        return (err
                + (1.0 - _sim(song.get("name"), title)) * 10.0
                + (1.0 - _sim(arts_name, artist)) * 3.0)

    return sorted(songs, key=score)


def _netease_lyrics(song_id, timeout=8):
    url = "https://music.163.com/api/song/lyric"
    params = {"id": song_id, "lv": -1, "kv": -1, "tv": -1}
    r = requests.get(url, params=params, headers=_NETEASE_HEADERS, timeout=timeout)
    r.raise_for_status()
    js = r.json()
    lrc = ((js.get("lrc") or {}).get("lyric")) or ""
    tlrc = ((js.get("tlyric") or {}).get("lyric")) or ""
    return lrc, tlrc


def from_netease(title, artist, album=None, duration=None, timeout=8,
                 max_candidates=3):
    """取网易云歌词；占位文本（纯音乐等）会被核验掉，换下一个候选。"""
    songs = _netease_candidates(title, artist, duration, timeout)
    for song in songs[:max_candidates]:
        lrc, tlrc = _netease_lyrics(song["id"], timeout)
        orig = _strip_credits(parse_lrc(lrc))
        if not orig or _looks_placeholder([t for _, t in orig]):
            continue
        trans = parse_lrc(tlrc)
        lines = _dedup_same_text(_attach_translation(orig, trans))
        return {"synced": True, "lines": lines, "plain": [],
                "source": "netease"}
    return None


# --------------------------------------------------------------------------- #
# LRCLIB
# --------------------------------------------------------------------------- #
_LRCLIB = "https://lrclib.net/api"


def from_lrclib(title, artist, album=None, duration=None, timeout=8):
    params = {"artist_name": artist or "", "track_name": title or ""}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = int(round(duration))

    js = None
    try:
        r = requests.get(
            _LRCLIB + "/get", params=params,
            headers={"User-Agent": UA}, timeout=timeout,
        )
        if r.status_code == 200:
            js = r.json()
    except Exception:
        js = None

    if js is None:
        try:
            q = ("%s %s" % (title, artist)).strip()
            r = requests.get(
                _LRCLIB + "/search", params={"q": q},
                headers={"User-Agent": UA}, timeout=timeout,
            )
            if r.status_code == 200 and r.json():
                js = r.json()[0]
        except Exception:
            js = None

    if not js:
        return None

    synced = js.get("syncedLyrics") or ""
    plain = js.get("plainLyrics") or ""

    if synced:
        lines = _dedup_same_text(_attach_translation(parse_lrc(synced), []))
        if lines and not _looks_placeholder([t for _, t, _ in lines]):
            return {"synced": True, "lines": lines, "plain": [], "source": "lrclib"}

    if plain:
        rows = [ln.strip() for ln in plain.splitlines() if ln.strip()]
        if rows and not _looks_placeholder(rows):
            return {"synced": False, "lines": [], "plain": rows, "source": "lrclib"}
    return None


# --------------------------------------------------------------------------- #
# 查询串变体（非标准歌曲常常带括号/后缀/多歌手，直接用会搜不到）
# --------------------------------------------------------------------------- #
_BRACKET_RE = re.compile(
    u"[(\uff08\\[\u3010][^)\uff09\\]\u3011]*[)\uff09\\]\u3011]")
_SUFFIX_RE = re.compile(
    u"\\s*[-\u2013\u2014]\\s*(live|remaster(ed)?|radio edit|acoustic|"
    u"instrumental|demo|version|mix|feat\\..*|现场|翻自|伴奏|纯音乐).*$",
    re.I,
)
_ARTIST_SPLIT_RE = re.compile(u"[,&/\uff0c\u3001;]| feat\\.? | ft\\.? ", re.I)


def _clean(text):
    if not text:
        return ""
    t = _BRACKET_RE.sub(u" ", text)
    t = _SUFFIX_RE.sub(u" ", t)
    return re.sub(r"\s+", u" ", t).strip()


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _sim(a, b):
    """两个名字的粗糙相似度：相等 1.0，互相包含 0.6，其它 0。"""
    na, nb = _norm(_clean(a or "")), _norm(_clean(b or ""))
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.6
    return 0.0


def _variants(title, artist):
    """依次尝试的查询串，从精确到宽松。"""
    t0 = (title or "").strip()
    a0 = (artist or "").strip()
    a_first = _ARTIST_SPLIT_RE.split(a0)[0].strip() if a0 else ""
    cands = [
        (t0, a0),
        (_clean(t0), a0),
        (_clean(t0), _clean(a0)),
        (_clean(t0), a_first),
        (_clean(t0), ""),
    ]
    out, seen = [], set()
    for t, a in cands:
        key = (t, a)
        if t and key not in seen:
            seen.add(key)
            out.append((t, a))
    return out[:4]


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def _provider_funcs():
    """可用的歌词源；Apple 依赖可选模块/凭证，缺了就静默跳过。"""
    funcs = {"netease": from_netease, "lrclib": from_lrclib}
    try:
        from apple_music import from_apple_music
        funcs["apple"] = from_apple_music
    except ImportError:
        pass
    return funcs


def fetch_ex(title, artist, album=None, duration=None,
             providers=("apple", "netease", "lrclib"), timeout=8):
    """返回 (result, had_error)。

    had_error=True 表示至少有一个源是“因为异常（网络/接口出错）”失败的，
    这时 result=None 不能当作“这首歌确实没有歌词”——调用方不该缓存它。
    """
    if not title:
        return None, False

    funcs = _provider_funcs()
    had_error = False
    for name in providers:
        fn = funcs.get(name)
        if fn is None:
            continue
        for q_title, q_artist in _variants(title, artist):
            try:
                res = fn(q_title, q_artist, album, duration, timeout)
            except Exception:
                had_error = True
                res = None
            if res:
                return res, had_error
    return None, had_error


def fetch(title, artist, album=None, duration=None,
          providers=("apple", "netease", "lrclib"), timeout=8):
    """兼容旧接口，只要结果。"""
    return fetch_ex(title, artist, album, duration, providers, timeout)[0]
