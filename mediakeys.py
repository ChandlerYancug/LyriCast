# -*- coding: utf-8 -*-
"""全局按键支持：媒体键（播放/暂停、上一首、下一首）+ 音量键接管。

媒体键：用 RegisterHotKey + Qt 原生事件过滤器，零依赖、全局生效。
代价：注册期间这几个键会被本程序接管（系统/其它 App 收不到），
做成了托盘里的开关，默认开启，随时可关。

音量键（音量+/-/静音）：系统不允许 RegisterHotKey 抢占，改用
低级键盘钩子（WH_KEYBOARD_LL）拦截。只有当本程序决定接管
（如已连上支持音量控制的音箱）时才吞掉按键，否则原样放行给系统。
"""

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# 热键 id -> 动作（动作名和播放器控制条共用一套）
_HOTKEYS = (
    (1, VK_MEDIA_NEXT_TRACK, "next"),
    (2, VK_MEDIA_PREV_TRACK, "prev"),
    (3, VK_MEDIA_STOP, "pause"),
    (4, VK_MEDIA_PLAY_PAUSE, "toggle"),
)


class MediaKeyFilter(QAbstractNativeEventFilter):
    """把全局多媒体键转成回调。"""

    def __init__(self, hwnd, callback):
        super().__init__()
        self.hwnd = int(hwnd)
        self.callback = callback
        self._registered = []

    # ---- 注册 / 注销 ---------------------------------------------------- #
    def register(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.unregister()
        for hotkey_id, vk, _action in _HOTKEYS:
            ok = user32.RegisterHotKey(
                wintypes.HWND(self.hwnd), hotkey_id, MOD_NOREPEAT, vk)
            if ok:
                self._registered.append(hotkey_id)
        return len(self._registered)

    def unregister(self):
        if not self._registered:
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            for hotkey_id in self._registered:
                user32.UnregisterHotKey(wintypes.HWND(self.hwnd), hotkey_id)
        except Exception:
            pass
        self._registered = []

    @property
    def count(self):
        return len(self._registered)

    # ---- 事件 ---------------------------------------------------------- #
    def nativeEventFilter(self, event_type, message):
        try:
            et = bytes(event_type)
        except Exception:
            et = b""
        if b"windows" not in et:
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        except Exception:
            return False, 0
        if msg.message != WM_HOTKEY:
            return False, 0
        hotkey_id = int(msg.wParam)
        for hid, _vk, action in _HOTKEYS:
            if hid == hotkey_id:
                try:
                    self.callback(action)
                except Exception:
                    pass
                return True, 0
        return False, 0


def available():
    """本机是否支持（能成功注册一组热键）。"""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ok = user32.RegisterHotKey(None, 9, MOD_NOREPEAT, VK_MEDIA_PLAY_PAUSE)
        if ok:
            user32.UnregisterHotKey(None, 9)
        return bool(ok)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 音量键：低级键盘钩子（系统不允许 RegisterHotKey 抢占音量键）
# --------------------------------------------------------------------------- #
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class VolumeKeyHook:
    """拦下键盘音量键（音量+/音量-/静音）转给回调。

    回调形如 ``callback(action) -> bool``，action 为
    "vol_up" / "vol_down" / "mute"；返回 True 表示吞掉该按键
    （系统主音量不变）。

    注意：
      - 回调运行在安装线程的消息派发里，**必须立即返回**
        （实际动作应交给定时器/线程去聚合处理）；
      - 安装钩子的线程必须有消息循环（Qt 主线程满足）。
    """

    _ACTIONS = {
        VK_VOLUME_UP: "vol_up",
        VK_VOLUME_DOWN: "vol_down",
        VK_VOLUME_MUTE: "mute",
    }

    def __init__(self, callback):
        self.callback = callback
        self._hook = None
        self._proc = None          # 保持回调引用，防止被 GC

    @property
    def active(self):
        return bool(self._hook)

    def install(self):
        if self._hook:
            return True
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hookproc_t = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int,
                wintypes.WPARAM, wintypes.LPARAM)

            def _proc(code, wparam, lparam):
                if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    try:
                        kb = ctypes.cast(
                            lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                        action = self._ACTIONS.get(int(kb.vkCode))
                        if action is not None and self.callback(action):
                            return 1               # 吞掉：不改系统音量
                    except Exception:
                        pass
                return user32.CallNextHookEx(None, code, wparam, lparam)

            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.SetWindowsHookExW.argtypes = (
                ctypes.c_int, hookproc_t, wintypes.HANDLE, wintypes.DWORD)
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = (
                wintypes.HHOOK, ctypes.c_int,
                wintypes.WPARAM, wintypes.LPARAM)
            user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)

            proc = hookproc_t(_proc)
            hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
            if not hook:
                return False
            self._proc = proc
            self._hook = hook
            return True
        except Exception:
            self._hook = None
            self._proc = None
            return False

    def uninstall(self):
        if not self._hook:
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        self._hook = None
        self._proc = None
