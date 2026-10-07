# -*- coding: utf-8 -*-
"""运行期路径：源码运行和 exe（PyInstaller）运行各自一套。

- **源码运行**（`python main.py` / run.bat）：
  只读资源与可写数据都在项目目录（config.json、am_token.txt、cache/ 都在仓库里，
  和以前完全一样，不惊动已有用户）。
- **exe 运行**（`LyriCast.exe`，PyInstaller 打包）：
  只读资源在打包目录（`sys._MEIPASS`：fonts/、icon.ico、dev/make_shortcut.ps1…），
  可写数据放用户目录 `%LOCALAPPDATA%\\LyriCast\\`（其它平台 `~/.lyricast/`）——
  和日志同一个地方；exe 换了位置、甚至放在只读目录里也能正常保存配置与缓存。
"""

import os
import sys

APP_DIR = "LyriCast"          # 用户目录下的文件夹名（与 APP_NAME / 日志保持一致）


def is_frozen():
    """是不是 PyInstaller 打出来的 exe。"""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """只读资源目录：fonts/、icon.ico 等（exe 内为解包目录）。"""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # speakers/paths.py -> 上上一级 = 项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """可写数据目录：config.json / am_token.txt / cache/（用户目录，exe 模式）。"""
    if not is_frozen():
        return bundle_dir()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIR)
    return os.path.join(os.path.expanduser("~"), "." + APP_DIR.lower())


def config_path():
    return os.path.join(data_dir(), "config.json")


def token_path():
    return os.path.join(data_dir(), "am_token.txt")


def cache_dir():
    return os.path.join(data_dir(), "cache")


def fonts_dir():
    return os.path.join(bundle_dir(), "fonts")


def icon_path():
    return os.path.join(bundle_dir(), "icon.ico")


def shortcut_ps1():
    """创建快捷方式用的脚本（源码在 dev/ 下；exe 里由打包脚本带进去）。"""
    return os.path.join(bundle_dir(), "dev", "make_shortcut.ps1")


def import_token_if_missing():
    """另一处有 am_token.txt 就搬过来（只搬一次，不覆盖现有的）。

    常见场景：源码版配好的凭证，换 exe 版跑时不用重配（反之亦然），
    或者把 am_token.txt 放在 exe 旁边当便携版。返回搬来的源路径（没搬则空）。
    """
    dst = token_path()
    if os.path.exists(dst):
        return ""
    cands = []
    if is_frozen():
        cands.append(os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)), "am_token.txt"))
    else:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or ""
            if base:
                cands.append(os.path.join(base, APP_DIR, "am_token.txt"))
        cands.append(os.path.join(os.path.expanduser("~"),
                                  "." + APP_DIR.lower(), "am_token.txt"))
    for src in cands:
        try:
            if not os.path.isfile(src):
                continue
            with open(src, "r", encoding="utf-8") as fp:
                data = fp.read().strip()
            if not data:
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fp:
                fp.write(data)
            return src
        except OSError:
            continue
    return ""
