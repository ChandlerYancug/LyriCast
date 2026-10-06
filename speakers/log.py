# -*- coding: utf-8 -*-
"""日志：滚动文件 + 控制台（有终端时）。

为什么不用 print：开源后“读不到曲目 / 连不上音箱”这类问题必须能靠一份日志定位。
日志落在用户目录（不是仓库里，避免污染与泄露）：

    Windows   %LOCALAPPDATA%\\LyriCast\\logs\\lyricast.log
    其它平台   ~/.lyricast/logs/lyricast.log
    （可用环境变量 LYRICAST_LOG_DIR 覆盖；托盘菜单里有“打开日志文件夹”）

- 单文件 1 MB、保留 3 份（RotatingFileHandler），长期挂着也不会撑爆磁盘；
- 控制台只在 stderr 存在时挂（pythonw 启动时没有，自动跳过）；
- urllib3 / requests / PIL 压到 WARNING，避免噪音把关键信息埋掉；
- 未捕获异常走 excepthook 记一条 CRITICAL，方便用户直接把日志发出来。
"""

import logging
import logging.handlers
import os
import sys
import traceback

_APP_DIR = "LyriCast"          # 用户目录下的文件夹名（与 APP_NAME 保持一致）
_LOG_NAME = "lyricast.log"
_SETUP_DONE = False


def log_dir():
    """日志目录（可用 LYRICAST_LOG_DIR 覆盖，方便绿色版/便携使用）。"""
    env = os.environ.get("LYRICAST_LOG_DIR")
    if env:
        return env
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, _APP_DIR, "logs")
    return os.path.join(os.path.expanduser("~"), ".lyricast", "logs")


def log_path():
    return os.path.join(log_dir(), _LOG_NAME)


def setup(level=logging.INFO, to_file=True):
    """安装日志处理器；重复调用只生效一次。返回日志文件路径（可能为空）。"""
    global _SETUP_DONE
    root = logging.getLogger()
    if _SETUP_DONE:
        return log_path()
    _SETUP_DONE = True
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname).1s %(name)s: %(message)s", "%m-%d %H:%M:%S")

    path = ""
    if to_file:
        try:
            os.makedirs(log_dir(), exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_path(), maxBytes=1_000_000, backupCount=3,
                encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)      # 文件里留全量，控制台只留 INFO
            root.addHandler(fh)
            path = log_path()
        except Exception:
            path = ""

    # 有控制台才挂 StreamHandler（run.bat 有；pythonw 双击没有）
    if getattr(sys, "stderr", None) is not None:
        try:
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            sh.setLevel(level)
            root.addHandler(sh)
        except Exception:
            pass

    for noisy in ("urllib3", "requests", "PIL", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("lyricast").info(
        "日志已启动（文件：%s）", path or "未启用")
    return path


def get_logger(name):
    """取 logger；名字统一加 lyricast. 前缀，方便过滤。"""
    if name and not name.startswith("lyricast"):
        name = "lyricast." + name
    return logging.getLogger(name or "lyricast")


def install_excepthook():
    """未捕获异常也写进日志（不然 pythonw 下闪退什么都没有）。"""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            logging.getLogger("lyricast").critical(
                "未捕获异常:\n%s", "".join(
                    traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        try:
            prev(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = hook
