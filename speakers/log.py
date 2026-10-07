# -*- coding: utf-8 -*-
"""日志：默认安静，排查时再开。

日常使用不写日志文件（保持简洁）；开源后「读不到曲目 / 连不上音箱」这类问题
要靠一份日志定位，托盘菜单勾「记录运行日志（排查用）」即可开启
（写滚动文件 + DEBUG），之后「打开日志文件夹」把文件发到 Issues。

    文件位置  Windows  %LOCALAPPDATA%\\LyriCast\\logs\\lyricast.log
             其它平台  ~/.lyricast/logs/lyricast.log
    （可用环境变量 LYRICAST_LOG_DIR 覆盖）

- 文件日志：单文件 1 MB、保留 3 份（RotatingFileHandler），开着不管也不会撑爆磁盘；
- 控制台：只在有终端时挂（run-console.bat 有；pythonw / exe 双击没有），
  所以平时既没有黑框也没有日志噪音；
- urllib3 / requests / charset_normalizer / PIL / asyncio 压到 WARNING，避免噪音；
- 未捕获异常：开着日志时记一条 CRITICAL；没开日志时也在崩溃这一刻把
  traceback 追加进同一个文件（否则 pythonw 下闪退就什么都查不到），
  正常运行期间不会写任何东西。
"""

import logging
import logging.handlers
import os
import sys
import time
import traceback

_APP_DIR = "LyriCast"          # 用户目录下的文件夹名（与 APP_NAME 保持一致）
_LOG_NAME = "lyricast.log"
_SETUP_DONE = False
_FILE_HANDLER = None
_FMT = logging.Formatter(
    "%(asctime)s %(levelname).1s %(name)s: %(message)s", "%m-%d %H:%M:%S")
_NOISY = ("urllib3", "requests", "charset_normalizer", "PIL", "asyncio")


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


def file_log_enabled():
    """文件日志开没开（托盘勾选状态用）。"""
    return _FILE_HANDLER is not None


def set_file_log(enabled):
    """开关文件日志（随时可切）。返回当前日志文件路径（关了就为空串）。"""
    global _FILE_HANDLER
    root = logging.getLogger()
    if enabled and _FILE_HANDLER is None:
        try:
            os.makedirs(log_dir(), exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_path(), maxBytes=1_000_000, backupCount=3,
                encoding="utf-8")
            fh.setFormatter(_FMT)
            fh.setLevel(logging.DEBUG)      # 文件里留全量
            root.addHandler(fh)
            _FILE_HANDLER = fh
            logging.getLogger("lyricast").info("日志已开启（%s）", log_path())
        except Exception:
            _FILE_HANDLER = None
    elif not enabled and _FILE_HANDLER is not None:
        root.removeHandler(_FILE_HANDLER)
        try:
            _FILE_HANDLER.close()
        except Exception:
            pass
        _FILE_HANDLER = None
    return log_path() if _FILE_HANDLER is not None else ""


def setup(level=logging.INFO, to_file=False):
    """安装日志处理器；重复调用只生效一次。返回日志文件路径（没开则为空）。

    `to_file=True`（托盘里预先勾了「记录运行日志」）一开始就写文件；
    否则只压第三方噪音 + 有终端时打控制台。
    """
    global _SETUP_DONE
    root = logging.getLogger()
    if _SETUP_DONE:
        return log_path() if _FILE_HANDLER is not None else ""
    _SETUP_DONE = True
    root.setLevel(logging.DEBUG)

    if to_file:
        set_file_log(True)

    # 有控制台才挂 StreamHandler（run-console.bat 有；pythonw 双击没有）
    if getattr(sys, "stderr", None) is not None:
        try:
            sh = logging.StreamHandler()
            sh.setFormatter(_FMT)
            sh.setLevel(level)
            root.addHandler(sh)
        except Exception:
            pass

    for noisy in _NOISY:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_path() if _FILE_HANDLER is not None else ""


def get_logger(name):
    """取 logger；名字统一加 lyricast. 前缀，方便过滤。"""
    if name and not name.startswith("lyricast"):
        name = "lyricast." + name
    return logging.getLogger(name or "lyricast")


def _write_crash(text):
    """没开文件日志时的兜底：崩溃这一刻把 traceback 追加进日志文件。"""
    try:
        os.makedirs(log_dir(), exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as fp:
            fp.write(text)
    except Exception:
        pass


def install_excepthook():
    """未捕获异常也写进日志（不然 pythonw 下闪退什么都没有）。"""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            detail = "".join(traceback.format_exception(exc_type, exc, tb))
            if file_log_enabled():
                logging.getLogger("lyricast").critical("未捕获异常:\n%s", detail)
            else:
                _write_crash("%s C lyricast: 未捕获异常:\n%s\n" % (
                    time.strftime("%m-%d %H:%M:%S"), detail))
        except Exception:
            pass
        try:
            prev(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = hook
