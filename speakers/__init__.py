# -*- coding: utf-8 -*-
"""音箱后端注册表：发现设备 -> 打开后端 -> 统一读写。

    import speakers
    for d in speakers.discover():
        print(d["kind"], d["name"], d["ip"])
    be = speakers.open_backend("upnp", host="192.168.1.20",
                               location="http://192.168.1.20:49152/description.xml")
    print(be.now_playing())
"""

from . import discovery  # noqa: F401  （re-export：speakers.discovery）
from .base import (  # noqa: F401
    CAN_CONTROL,
    CAN_COORDINATOR,
    CAN_EVENTS,
    CAN_SEEK,
    CAN_VOLUME,
    Backend,
    NotSupported,
    NowPlaying,
    absolutize,
    split_title_artist,
)
from .http import (  # noqa: F401
    APP_NAME,
    APP_VERSION,
    UA,
    fetch_bytes,
    fmt_clock,
    parse_clock,
)
from .log import (  # noqa: F401
    file_log_enabled,
    get_logger,
    install_excepthook,
    log_dir,
    log_path,
    set_file_log,
    setup,
)

__all__ = [
    "discover", "open_backend", "backend_kinds", "fetch_album_art",
    "Backend", "NowPlaying", "NotSupported", "discovery",
    "CAN_CONTROL", "CAN_SEEK", "CAN_VOLUME", "CAN_EVENTS", "CAN_COORDINATOR",
    "APP_NAME", "APP_VERSION", "UA",
    "setup", "get_logger", "log_dir", "log_path", "install_excepthook",
    "set_file_log", "file_log_enabled",
]

# kind -> (模块名, 类名)；懒加载，某个后端缺依赖不影响其它后端
_BACKENDS = {
    "sonos": ("speakers.sonos", "SonosBackend"),
    "upnp": ("speakers.upnp", "UpnpBackend"),
    # Windows 系统媒体会话（电脑自己播放时读；需装 pyproject 的 smtc extra）
    "smtc": ("speakers.smtc", "SmtcBackend"),
    # 将来：
    # "macos": ("speakers.macos", "MacNowPlayingBackend"),
    # "listen": ("speakers.listen", "ListenBackend"),  # 麦克风 + 指纹
}

# 下面几行只是“静态标记”：真正的加载仍是上面注册表的懒加载，
# 但打包成 exe（PyInstaller 等）时静态分析看不到字符串里的模块名，
# 需要这样带一下；某个后端缺依赖（如 smtc 要 winrt）不影响其它后端。
try:                                    # noqa: SIM105
    from . import sonos                 # noqa: F401
except Exception:
    pass
try:                                    # noqa: SIM105
    from . import upnp                  # noqa: F401
except Exception:
    pass
try:                                    # noqa: SIM105
    from . import smtc                  # noqa: F401
except Exception:
    pass


def backend_kinds():
    """已安装可用的后端 kind 列表。"""
    out = []
    for kind in _BACKENDS:
        try:
            _load(kind)
            out.append(kind)
        except Exception:
            pass
    return out


def _load(kind):
    import importlib
    mod_name, cls_name = _BACKENDS[kind]
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def open_backend(kind, host, name="", location="", **kwargs):
    """打开一个后端。

    kind     "sonos" / "upnp" / …（配置里的 speaker_type；"auto" 由调用方先发现）
    host     设备 IP
    location 设备描述 URL（DLNA 需要；Sonos 可留空）
    """
    if kind == "auto":
        kind = "sonos" if not location else "upnp"
    cls = _load(kind)
    return cls(host, name=name, location=location, **kwargs)


def discover(timeout=3.0):
    """局域网发现（Sonos + 通用 DLNA 一起）。"""
    return discovery.discover(timeout=timeout)


def fetch_album_art(url, timeout=6.0):
    """统一下载封面（bytes 或 None）。"""
    return fetch_bytes(url, timeout=timeout)
