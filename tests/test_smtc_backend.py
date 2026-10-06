# -*- coding: utf-8 -*-
"""SmtcBackend 的离线测试:用假 SMTC 会话验证读 / 状态映射 / 控制 / 封面缓存。

不碰真实系统媒体会话,也不要求机器上有歌在放;没装 winrt 依赖的环境
(CI 的 Linux/macOS)打印 SKIP 并正常退出。

跑法(项目根目录):
    python tests/test_smtc_backend.py     # 直接跑,顺序执行并打印 ALL PASSED
    pytest tests/test_smtc_backend.py     # 也能被收集(缺依赖时整模块 skip)
"""

import asyncio
import contextlib
import datetime
import os
import sys
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest import mock

# 直接运行时脚本目录是 tests/,得手动把项目根塞进 import 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 没装 pywinrt(或不在 Windows)时优雅跳过:CI 要能过,不能报错
_IMPORT_ERROR = None
try:
    import winrt.windows.media.control      # noqa: F401
    import winrt.windows.storage.streams    # noqa: F401
except Exception as exc:
    _IMPORT_ERROR = exc

if _IMPORT_ERROR is not None:
    _SKIP_MSG = ("SKIP tests/test_smtc_backend.py: 未安装 pywinrt 依赖(%s);"
                 "Windows 上可在仓库目录执行 pip install -e \".[smtc]\"" % _IMPORT_ERROR)
    print(_SKIP_MSG)
    if __name__ == "__main__":
        sys.exit(0)
    try:
        import pytest
        pytest.skip(_SKIP_MSG, allow_module_level=True)
    except ImportError:
        raise SystemExit(0)

from speakers import smtc                                        # noqa: E402
from speakers.base import CAN_CONTROL, CAN_SEEK, NotSupported    # noqa: E402
from speakers.smtc import SmtcBackend                            # noqa: E402

# --------------------------------------------------------------------------- #
# 假数据:固定值,断言与之一一对应
# --------------------------------------------------------------------------- #
TITLE = "夜空中最亮的星"
ARTIST = "逃跑计划"
ALBUM = "世界"
APP_ID = "AppleInc.AppleMusicWin_8wekyb3d8bbwe!AppleMusic"
POSITION = datetime.timedelta(seconds=65.5)
DURATION = datetime.timedelta(seconds=210.0)
ART_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


class FakeStatus(object):
    """GlobalSystemMediaTransportControlsSessionPlaybackStatus 的替身。

    真实枚举带 .name(pywinrt 投影成 IntEnum),后端按 .name 映射。
    """

    def __init__(self, name):
        self.name = name


class FakeTimeline(object):
    def __init__(self, position, end_time):
        self.position = position            # 真实类型是 datetime.timedelta
        self.end_time = end_time


class FakePlaybackInfo(object):
    def __init__(self, status):
        self.playback_status = status


class FakeProps(object):
    def __init__(self, title, artist, album, thumbnail):
        self.title = title
        self.artist = artist
        self.album_title = album
        self.thumbnail = thumbnail


class FakeStream(object):
    """IRandomAccessStream 的替身:后端用 Buffer + read_async 读流。"""

    def __init__(self, data):
        self._data = data
        self._pos = 0
        self.closed = False

    @property
    def size(self):
        return len(self._data)

    async def read_async(self, buffer, count, options):
        chunk = self._data[self._pos:self._pos + count]
        self._pos += len(chunk)
        buffer.length = len(chunk)
        memoryview(buffer).cast("B")[:len(chunk)] = chunk
        return buffer

    def close(self):
        self.closed = True


class FakeThumbnail(object):
    """IRandomAccessStreamReference 的替身:记录开了几次流。"""

    def __init__(self, data):
        self.data = data
        self.open_count = 0

    async def open_read_async(self):
        self.open_count += 1
        return FakeStream(self.data)


class BrokenThumbnail(object):
    """打不开的封面流(异常兜底用)。"""

    async def open_read_async(self):
        raise OSError("thumbnail stream gone")


class FakeSession(object):
    def __init__(self, title=TITLE, artist=ARTIST, album=ALBUM,
                 position=POSITION, duration=DURATION, status="PLAYING",
                 thumbnail=None, app_id=APP_ID):
        self.title = title
        self.artist = artist
        self.album = album
        self.position = position
        self.duration = duration
        self.status = status
        self.thumbnail = thumbnail
        self.app_id = app_id
        self.calls = []                 # 收到的控制调用名
        self.seek_arg = None
        self.accept_controls = True     # False = try_* 返回 False

    async def try_get_media_properties_async(self):
        return FakeProps(self.title, self.artist, self.album, self.thumbnail)

    def get_timeline_properties(self):
        return FakeTimeline(self.position, self.duration)

    def get_playback_info(self):
        return FakePlaybackInfo(FakeStatus(self.status))

    @property
    def source_app_user_model_id(self):
        return self.app_id

    async def _control(self, name):
        self.calls.append(name)
        return self.accept_controls

    async def try_play_async(self):
        return await self._control("play")

    async def try_pause_async(self):
        return await self._control("pause")

    async def try_skip_next_async(self):
        return await self._control("next")

    async def try_skip_previous_async(self):
        return await self._control("previous")

    async def try_change_playback_position_async(self, position):
        self.seek_arg = position
        return await self._control("seek")


class FakeManager(object):
    def __init__(self, current=None, sessions=None, sessions_error=None):
        self._current = current
        self._sessions = list(sessions or [])
        self._sessions_error = sessions_error

    def get_current_session(self):
        return self._current

    def get_sessions(self):
        if self._sessions_error is not None:
            raise self._sessions_error
        return self._sessions


# --------------------------------------------------------------------------- #
# 测试脚手架
# --------------------------------------------------------------------------- #
def _run_inline(coro, timeout=5.0):
    """runner 替身:假对象都是普通协程,直接 asyncio.run 跑掉。"""
    return asyncio.run(coro)


@contextlib.contextmanager
def fake_env(manager):
    """把模块级 runner 和 SmtcBackend._manager() 换成假实现,得到离线后端。"""
    async def _fake_manager(self):
        return manager

    with mock.patch.object(smtc, "run", _run_inline), \
            mock.patch.object(SmtcBackend, "_manager", _fake_manager):
        yield SmtcBackend("")


_TICK = datetime.timedelta(microseconds=1)


def _to_ticks(value):
    """把 seek 收到的参数换算成 100ns ticks,与「12.5s = 125000000」对照。

    pywinrt 3.x 把 WinRT TimeSpan 投影成 datetime.timedelta(实测传 int 会被
    TypeError 拒绝),timedelta 精度到微秒,1 微秒 = 10 ticks,换算无损。
    """
    if isinstance(value, datetime.timedelta):
        return (value // _TICK) * 10
    return int(value)


# --------------------------------------------------------------------------- #
# 测试
# --------------------------------------------------------------------------- #
def test_runner_executes_coroutine():
    """真实的常驻 runner(守护线程 + run_forever)能同步跑完协程。"""
    async def add(a, b):
        await asyncio.sleep(0)
        return a + b

    assert smtc.run(add(2, 3)) == 5


def test_runner_timeout_raises():
    """超时往上抛(并取消后台操作)。"""
    async def forever():
        await asyncio.sleep(30)

    try:
        smtc.run(forever(), timeout=0.05)
    except FutureTimeoutError:
        pass
    else:
        raise AssertionError("runner 超时应抛 TimeoutError")


def test_now_playing_fields():
    session = FakeSession()
    with fake_env(FakeManager(current=session)) as be:
        np = be.now_playing()
        assert np.title == TITLE, np.title
        assert np.artist == ARTIST, np.artist
        assert np.album == ALBUM, np.album
        assert np.position == 65.5, np.position
        assert np.duration == 210.0, np.duration
        assert np.state == "PLAYING", np.state
        assert np.uri == APP_ID, np.uri
        assert np.raw == {"session_app": APP_ID}, np.raw
        assert np.album_art == "", np.album_art    # SMTC 没有封面 URL


def test_status_mapping():
    """PLAYING / PAUSED / STOPPED 映射成统一状态串,其它一律 ""。"""
    cases = {
        "PLAYING": "PLAYING",
        "PAUSED": "PAUSED_PLAYBACK",
        "STOPPED": "STOPPED",
        "CHANGING": "",
        "CLOSED": "",
        "OPENED": "",
    }
    for raw_name, expected in cases.items():
        with fake_env(FakeManager(current=FakeSession(status=raw_name))) as be:
            assert be.now_playing().state == expected, raw_name


def test_controls_and_seek():
    session = FakeSession()
    with fake_env(FakeManager(current=session)) as be:
        be.play()
        be.pause()
        be.next_track()
        be.previous_track()
        assert session.calls == ["play", "pause", "next", "previous"], session.calls

        be.seek(12.5)
        assert session.calls[-1] == "seek"
        # pywinrt 3.x 的 TimeSpan 投影是 datetime.timedelta,换算回 100ns ticks
        # 恰好是 12.5s = 125000000(测试要求里的那个数)
        assert isinstance(session.seek_arg, datetime.timedelta), session.seek_arg
        assert _to_ticks(session.seek_arg) == 125000000, session.seek_arg


def test_control_false_is_silent():
    """try_* 返回 False = 会话不接受该指令,静默忽略,不抛异常。"""
    session = FakeSession()
    session.accept_controls = False
    with fake_env(FakeManager(current=session)) as be:
        assert be.play() is False
        assert be.seek(1.0) is False


def test_no_session():
    """没有会话:读接口给空 NowPlaying,控制接口抛 RuntimeError。"""
    with fake_env(FakeManager(current=None, sessions=[])) as be:
        np = be.now_playing()
        assert np.empty and np.state == "", np

        for call in (be.play, be.pause, be.next_track, be.previous_track,
                     lambda: be.seek(1.0)):
            try:
                call()
            except RuntimeError as exc:
                assert "没有活动的媒体会话" in str(exc), exc
            else:
                raise AssertionError("没有会话时控制应抛 RuntimeError")


def test_fallback_picks_playing_session():
    """焦点不在播放器上时,从会话列表里挑 playback_status 为 PLAYING 的。"""
    paused = FakeSession(title="暂停的歌", status="PAUSED")
    playing = FakeSession(title="在播的歌", status="PLAYING")
    mgr = FakeManager(current=None, sessions=[paused, playing])
    with fake_env(mgr) as be:
        assert be.now_playing().title == "在播的歌"


def test_sessions_unavailable_degrades():
    """get_sessions() 枚举依赖可选包 winrt-Windows.Foundation.Collections:
    没装时只降级成「没有会话」,不能让轮询崩。"""
    mgr = FakeManager(current=None, sessions_error=ModuleNotFoundError(
        "No module named 'winrt.windows.foundation.collections'"))
    with fake_env(mgr) as be:
        assert be.now_playing().empty


def test_thumbnail_bytes_and_cache():
    thumb = FakeThumbnail(ART_BYTES)
    session = FakeSession(thumbnail=thumb)
    with fake_env(FakeManager(current=session)) as be:
        first = be.now_playing()
        assert first.album_art == ""
        assert first.raw["art_bytes"] == ART_BYTES
        assert thumb.open_count == 1

        second = be.now_playing()           # 同一首歌:吃缓存,不再开流
        assert second.raw["art_bytes"] == ART_BYTES
        assert thumb.open_count == 1

        session.title = "换了一首"           # 切歌:缓存失效,重新读
        third = be.now_playing()
        assert third.raw["art_bytes"] == ART_BYTES
        assert thumb.open_count == 2


def test_thumbnail_none_reads_nothing():
    session = FakeSession(thumbnail=None)
    with fake_env(FakeManager(current=session)) as be:
        np = be.now_playing()
        assert np.title == TITLE
        assert "art_bytes" not in np.raw


def test_thumbnail_failure_swallowed():
    """封面流打不开只丢封面,标题/状态照常返回。"""
    session = FakeSession(thumbnail=BrokenThumbnail())
    with fake_env(FakeManager(current=session)) as be:
        np = be.now_playing()
        assert np.title == TITLE
        assert "art_bytes" not in np.raw


def test_defaults_and_capabilities():
    be = SmtcBackend("ignored-host")        # host 对本机会话没意义
    assert be.kind == "smtc"
    assert be.capabilities == frozenset({CAN_CONTROL, CAN_SEEK})
    assert be.name == "本机媒体会话"
    try:
        be.set_volume(50)
    except NotSupported:
        pass
    else:
        raise AssertionError("SMTC 不支持音量,应由基类抛 NotSupported")


def test_missing_dependency_message():
    """缺依赖在构造时抛 RuntimeError,并告诉用户装什么。"""
    with mock.patch.object(smtc, "_IMPORT_ERROR", ImportError("no winrt")):
        try:
            SmtcBackend("")
        except RuntimeError as exc:
            msg = str(exc)
            assert ".[smtc]" in msg, msg
            assert "winrt-Windows.Media.Control" in msg, msg
        else:
            raise AssertionError("缺依赖时构造应抛 RuntimeError")


TESTS = (
    test_runner_executes_coroutine,
    test_runner_timeout_raises,
    test_now_playing_fields,
    test_status_mapping,
    test_controls_and_seek,
    test_control_false_is_silent,
    test_no_session,
    test_fallback_picks_playing_session,
    test_sessions_unavailable_degrades,
    test_thumbnail_bytes_and_cache,
    test_thumbnail_none_reads_nothing,
    test_thumbnail_failure_swallowed,
    test_defaults_and_capabilities,
    test_missing_dependency_message,
)


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print("OK  %s" % fn.__name__)
    print("ALL PASSED (%d tests)" % len(TESTS))
