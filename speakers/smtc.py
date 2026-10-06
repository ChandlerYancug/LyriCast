# -*- coding: utf-8 -*-
"""Windows 系统媒体会话(SMTC)后端:跟随「这台电脑自己在放什么」。

SMTC(System Media Transport Controls)就是音量面板上那块媒体控件背后的
系统服务,它只登记**本机应用**的播放会话:Apple Music、Spotify、浏览器
标签页等。所以这个后端覆盖的是「电脑自己在播」,也包括「电脑 AirPlay /
蓝牙投给 HomePod」——声音从音箱出来,但播放会话仍在本机,元数据、进度、
封面都读得到。

为什么手机 AirPlay 抓不到:手机直接投给 HomePod 时,音频根本不经过这台
电脑,Windows 里不存在对应的媒体会话,SMTC 自然什么都读不到;那种场景
要靠音箱自己的协议(UPnP/Sonos)或麦克风指纹,与这个后端无关。

依赖(缺了会在构造 SmtcBackend 时抛 RuntimeError,并提示装,在仓库目录里执行):
    pip install -e ".[smtc]"
或(任意目录,直接装底层包):
    pip install winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Storage.Streams

pywinrt 的媒体会话 API 全是 async:模块里只放一个常驻事件循环(守护线程
+ run_forever),所有调用经模块级 `run()` 同步等待,避免每次轮询都新建
事件循环。
"""

import asyncio
import datetime
import threading
from concurrent.futures import TimeoutError as _FutureTimeout
from typing import Any, cast

from .base import CAN_CONTROL, CAN_SEEK, Backend, NowPlaying

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
    )
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    _IMPORT_ERROR = None
except Exception as _exc:      # ImportError / OSError:漏装包或 WinRT 运行时缺 DLL
    # cast 只是让类型检查器别再对「延迟导入」报 Optional,构造期已拦截缺依赖
    GlobalSystemMediaTransportControlsSessionManager = cast(Any, None)
    Buffer = cast(Any, None)
    InputStreamOptions = cast(Any, None)
    _IMPORT_ERROR = _exc

_MISSING_DEPS_MSG = (
    "缺少 Windows 系统媒体会话(SMTC)依赖:%s\n"
    "请安装(在 LyriCast 仓库目录里):pip install -e \".[smtc]\"\n"
    "或直接装底层包:pip install winrt-Windows.Media.Control"
    " winrt-Windows.Foundation winrt-Windows.Storage.Streams"
)

_TIMEOUT = 5.0
_TICKS_PER_SECOND = 10000000    # WinRT TimeSpan 在 ABI 层的单位:100 纳秒
_READ_CHUNK = 64 << 10          # 读封面流的分块大小
_MAX_ART_BYTES = 8 << 20        # 封面不可能有 8 MiB,异常流别把内存吃光


# --------------------------------------------------------------------------- #
# 事件循环:pywinrt 是 async API,后端对外是同步接口
# --------------------------------------------------------------------------- #
class _AsyncLoopRunner(object):
    """常驻事件循环(首次使用时在守护线程里启动)。

    SMTC 轮询约 4 次/秒,每次都 asyncio.run() 新建/销毁 loop 既慢又没必要,
    所以整个模块共用一个 loop,用 run_coroutine_threadsafe 丢任务进去。
    """

    def __init__(self):
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def _loop_thread(self):
        loop = self._loop
        if loop is None:            # 防御:线程启动前 loop 一定已赋值
            return
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop_thread, name="smtc-async", daemon=True)
                self._thread.start()
            return self._loop

    def run(self, coro, timeout=_TIMEOUT):
        """同步等待 coroutine 完成;超时/底层异常原样向上抛。"""
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
        try:
            return future.result(timeout)
        except _FutureTimeout:
            future.cancel()     # 别让超时的操作在后台 loop 里越堆越多
            raise


_runner = _AsyncLoopRunner()


def run(coro, timeout=_TIMEOUT):
    """模块级入口(测试替换这一个函数即可让全部调用离开真实事件循环)。"""
    return _runner.run(coro, timeout)


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _span_to_seconds(value):
    """WinRT 时间量 -> 秒。

    PyWinRT 把 TimeSpan 投影成 datetime.timedelta(实测传 int 会被拒绝);
    这里顺手兜住老版本直接给 100ns ticks 的情况,单位换算只写这一处。
    """
    if value is None:
        return 0.0
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    return float(value) / _TICKS_PER_SECOND


def _seconds_to_span(seconds):
    """秒 -> WinRT TimeSpan 参数(seek 用,timedelta 才是 pywinrt 要的类型)。"""
    return datetime.timedelta(seconds=max(0.0, float(seconds)))


_STATE_MAP = {
    "PLAYING": "PLAYING",
    "PAUSED": "PAUSED_PLAYBACK",
    "STOPPED": "STOPPED",
    # CLOSED / OPENED / CHANGING 及未知值都映射成 ""(未知状态)
}


def _playback_name(session):
    """会话的原始播放状态名(PLAYING/PAUSED/…),读不到返回空串。"""
    try:
        return getattr(session.get_playback_info().playback_status, "name", "")
    except Exception:
        return ""


async def _read_stream_bytes(stream):
    """IRandomAccessStream -> bytes;空流返回 None,异常由调用方兜。"""
    size = min(int(stream.size), _MAX_ART_BYTES)
    if size <= 0:
        return None
    data = bytearray()
    try:
        while len(data) < size:
            want = min(_READ_CHUNK, size - len(data))
            chunk = Buffer(want)
            filled = await stream.read_async(chunk, want,
                                             InputStreamOptions.NONE)
            got = int(getattr(filled, "length", 0))
            if got <= 0:
                break
            data += bytes(filled)[:got]
    finally:
        try:
            stream.close()
        except Exception:
            pass
    return bytes(data) or None


# --------------------------------------------------------------------------- #
# 后端
# --------------------------------------------------------------------------- #
class SmtcBackend(Backend):
    """本机 Windows 媒体会话(细节见模块 docstring)。"""

    kind = "smtc"
    capabilities = frozenset({CAN_CONTROL, CAN_SEEK})   # SMTC 没有音量/事件

    def __init__(self, host="", name="", location=""):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(_MISSING_DEPS_MSG % _IMPORT_ERROR)
        # SMTC 永远指本机,host/location 只是占位(保持各后端统一的构造签名)
        super().__init__(host, name=name or "本机媒体会话", location=location)
        self._art_key = None        # 封面缓存对应的 (title, artist)
        self._art_bytes = None      # 封面缓存(同一首歌不重复开流读)

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def now_playing(self):
        return run(self._now_playing_async())

    async def _now_playing_async(self):
        session = await self._current_session()
        if session is None:
            return NowPlaying()     # 没会话:调用方显示「未读到曲目信息」
        props = await session.try_get_media_properties_async()
        title = getattr(props, "title", "") or ""
        artist = getattr(props, "artist", "") or ""
        album = getattr(props, "album_title", "") or ""
        timeline = session.get_timeline_properties()
        app_id = session.source_app_user_model_id or ""
        raw = {"session_app": app_id}    # type: dict
        art = await self._album_art_async(props, title, artist)
        if art:
            raw["art_bytes"] = art  # SMTC 的封面没有 URL,只能把字节交给调用方
        return NowPlaying(
            title=title,
            artist=artist,
            album=album,
            album_art="",
            position=_span_to_seconds(getattr(timeline, "position", None)),
            duration=_span_to_seconds(getattr(timeline, "end_time", None)),
            uri=app_id,
            state=_STATE_MAP.get(_playback_name(session), ""),
            raw=raw,
        )

    async def _album_art_async(self, props, title, artist):
        """封面 bytes,按 (title, artist) 记忆化。

        轮询约 4 次/秒,同一首歌每次 open_read_async + 读流太浪费。
        读失败/没有封面返回 None,且不缓存失败结果(下一轮还会再试)。
        """
        key = (title, artist)
        if self._art_bytes is not None and key == self._art_key:
            return self._art_bytes
        thumbnail = getattr(props, "thumbnail", None) if props is not None else None
        if thumbnail is None:
            return None
        try:
            stream = await thumbnail.open_read_async()
            data = await _read_stream_bytes(stream)
        except Exception:
            return None             # 封面是锦上添花,读不到不该影响歌词/状态
        if data:
            self._art_key = key
            self._art_bytes = data
        return data

    async def _manager(self):
        """取会话管理器(测试把它换成假 manager)。

        每次调用都重新 request_async,不缓存:SMTC 会话随各应用启停而变,
        缓存的 manager 可能一直握着已经退出的应用;request_async 只是取一份
        当前快照,4 次/秒的轮询完全吃得消。
        """
        return await GlobalSystemMediaTransportControlsSessionManager.request_async()

    async def _current_session(self):
        """当前焦点会话;焦点不在播放器上时,退而挑一个正在播的。"""
        manager = await self._manager()
        session = manager.get_current_session()
        if session is not None:
            return session
        try:
            for candidate in manager.get_sessions():
                if _playback_name(candidate) == "PLAYING":
                    return candidate
        except Exception:
            # get_sessions() 返回 IVectorView,枚举需要可选依赖
            # winrt-Windows.Foundation.Collections;没装它时这里抛
            # ModuleNotFoundError。只影响「没有焦点会话」时的兜底挑选,
            # 当作没有会话处理,轮询不能因此崩掉。
            pass
        return None

    # ------------------------------------------------------------------ #
    # 控(界面按 capabilities 决定是否显示按钮)
    # ------------------------------------------------------------------ #
    def _call_control(self, method_name, *args):
        """把一次控制操作丢进事件循环。

        try_* 返回 False = 该应用/流不接受这个指令(比如直播不能 seek):
        静默忽略(界面不该为此弹错),返回值交给调用方参考。
        """
        async def job():
            session = await self._current_session()
            if session is None:
                raise RuntimeError("没有活动的媒体会话")
            result = getattr(session, method_name)(*args)
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)

        return run(job())

    def play(self):
        return self._call_control("try_play_async")

    def pause(self):
        return self._call_control("try_pause_async")

    def next_track(self):
        return self._call_control("try_skip_next_async")

    def previous_track(self):
        return self._call_control("try_skip_previous_async")

    def seek(self, seconds):
        return self._call_control("try_change_playback_position_async",
                                  _seconds_to_span(seconds))
