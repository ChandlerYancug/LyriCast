# -*- coding: utf-8 -*-
"""歌词填充时长的估算与核验。

卡拉OK 白色填充应该尽量贴着“真实演唱区间”走，但 LRC 只给了
行首时间戳，很多行的时间戳到人声开始之间还有一段空白（上句
唱完、间奏入点），直接按「行首 -> 下一行」整段滚会出现：

  * 后跟长间奏时滚得特别慢（整段被拉长）；
  * 人声还没进，白色就从行首开始滚（提前）。

这里按字数估一个“正常演唱时长”，让填充**贴着行尾向后对齐**：

  * 演唱一般唱到下一行时间戳附近为止（句尾对齐）；
  * 行首到演唱开始之间的空白（间奏/停顿）先不滚；
  * 作词/作曲这类元信息行不做滚动填充，直接铺满。
"""

import re

# ---- Sonos RelTime 同步参数 -------------------------------------------------
# 首选：边沿时钟（relclock.py）——把整秒读数的每次跳变当成“位置跨过
# 整数”的实测信号，直接推导精确位置（main.py 会以精确值推给界面）。
# 以下参数只用于边沿尚未就绪（刚启动 / seek 后几秒）时的兜底：
# 读数 n 代表真实位置在 [n, n+1)，且轮询发现的时机大约落在窗口开头
# 半个采样周期处——注意不能加 0.5s（窗口中点）：轮询周期与 1 秒整除时
# 采样相位是锁定的，中点补偿会造成 0.25~0.5s 的系统性超前（实测“还
# 没唱就先滚”），所以兜底也只补“半个采样周期”的经验值。
REL_MID = 0.13       # 兜底补偿（≈半个轮询周期）
SYNC_PULL = 0.75     # 误差超过该值才纠偏（迟滞，滤掉读数抖动）
SYNC_SNAP = 1.5      # 误差超过该值直接对齐（seek / 切歌）
SYNC_RATE = 0.25     # 纠偏时每次读数收敛的比例

_CREDIT_RE = re.compile(
    r"^\s*(作词|作曲|编曲|制作人|制作|录音|混音|母带|监制|出品|发行|"
    r"策划|统筹|企划|词|曲|"
    r"written by|produced by|composed by|lyrics by|music by)\s*[:：]",
    re.I,
)


def fill_units(text):
    """粗估一句歌词的“发声量”：中文/全角 1.5，其它 0.5，空白 0.3。"""
    units = 0.0
    for ch in text or "":
        if ch.isspace():
            units += 0.3
        elif ord(ch) > 0x2E80:          # CJK、日文、全角标点
            units += 1.5
        else:
            units += 0.5
    return units


def est_duration(text):
    """估算这句的正常演唱时长（秒）。"""
    return 0.25 + fill_units(text) * 0.16


def is_credit(text):
    """元信息行（作词/作曲/制作…）：不适合做滚动填充。"""
    return bool(_CREDIT_RE.match(text or ""))


def fill_window(text, span):
    """返回 (delay, dur)：填充在行内 delay 秒后开始、持续 dur 秒。

    演唱时长取估算值（乘 1.25 缓冲），但不超过真实间隔；
    多出来的空白全部放在句首不滚，使填充以行尾结束。
    """
    est = est_duration(text)
    dur = min(span, max(1.0, est * 1.25))
    delay = max(0.0, span - dur)
    return delay, dur


def fill_frac(text, elapsed, span, end_rel=None, words=None):
    """行内已过去 elapsed 秒（相对行首）时的填充进度 0~1。

    end_rel 是这行的真实演唱时长（如 Apple TTML 的 begin/end），
    有则精确按它走；没有就退回按字数的估算（LRC 只有行首时间戳）。

    words 为逐词时间 [(begin_rel, end_rel, 文本)...]（Apple 逐词歌词），
    有则按词内线性插值算出已唱字符量，填充最贴近真人节奏。
    """
    if span <= 0.2:
        return 0.0
    if words:
        return _frac_from_words(words, elapsed)
    if is_credit(text):
        return 1.0
    if end_rel is not None and end_rel > 0.2:
        return min(1.0, max(0.0, elapsed / min(end_rel, span)))
    delay, dur = fill_window(text, span)
    if dur <= 0.2:
        return 0.0
    return min(1.0, max(0.0, (elapsed - delay) / dur))


def relative_words(words, times):
    """把逐词绝对时间转成相对行首：words[i] 对应 times[i]。"""
    out = []
    for i, ws in enumerate(words or ()):
        t0 = times[i] if i < len(times) else 0.0
        out.append([(b - t0, e - t0, w) for (b, e, w) in ws])
    return out


def _frac_from_words(words, elapsed):
    """按逐词时间把 elapsed 换算成字符进度（宽度用 fill_units 加权，
    中英混排时比纯字符数更接近像素比例）。"""
    total = 0.0
    for _, _, w in words:
        total += fill_units(w)
    if total <= 0.0:
        return 0.0
    done = 0.0
    for b, e, w in words:
        u = fill_units(w)
        if e <= b:
            if elapsed >= e:
                done += u
            continue
        if elapsed >= e:
            done += u
        elif elapsed <= b:
            break
        else:
            done += u * (elapsed - b) / (e - b)
            break
    return min(1.0, max(0.0, done / total))
