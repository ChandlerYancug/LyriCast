# -*- coding: utf-8 -*-
"""打包 Windows 免安装版（PyInstaller，onedir）。

用法（项目根目录，建议在 .venv 里）：

    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\python dev/build_exe.py

产物：`dist/LyriCast/`（里面 `LyriCast.exe` + 依赖，整个文件夹就是"绿色版"）。
CI（.github/workflows/release.yml）打 tag 时会自动跑这个脚本，并把
`dist/LyriCast/` 里的内容压成一个 zip 传上 Release。

放进 exe 的额外资源（`--add-data`）：
- `fonts/`      随包字体（开箱即用的观感）
- `icon.ico`    任务栏/窗口图标
- `dev/make_shortcut.ps1`  「开机自启」要用的建快捷方式脚本
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("需要先安装 PyInstaller：python -m pip install pyinstaller")
        return 1
    os.chdir(BASE)
    sep = ";" if sys.platform == "win32" else ":"
    args = [
        "main.py",
        "--name", "LyriCast",
        "--noconfirm", "--clean",
        "--windowed",                                    # 不弹控制台
        "--icon", "icon.ico",
        "--add-data", "fonts" + sep + "fonts",
        "--add-data", "icon.ico" + sep + ".",
        "--add-data", "dev/make_shortcut.ps1" + sep + "dev",
        # 音箱后端是“动态 import”加载的（speakers/__init__.py 里的注册表），
        # PyInstaller 静态分析看不到，必须显式收集
        "--collect-submodules", "speakers",
        # 凭证读取同样是动态 import 的，显式带上（含各家浏览器的子模块）
        "--hidden-import", "browser_cookie3",
        "--collect-submodules", "browser_cookie3",
        "--exclude-module", "pytest",
        "--exclude-module", "ruff",
        "--exclude-module", "PIL.ImageQt",
    ]
    print("PyInstaller " + " ".join(args))
    pyi.run(args)
    exe = os.path.join(BASE, "dist", "LyriCast", "LyriCast.exe")
    if os.path.exists(exe):
        print("完成：%s" % exe)
        print("整个 dist/LyriCast 文件夹就是免安装版（可压缩后分发）。")
        return 0
    print("没找到产物，看看上面的日志。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
