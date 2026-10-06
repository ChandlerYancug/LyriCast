# -*- coding: utf-8 -*-
"""把标准输出/错误输出切成 UTF-8（中文 Windows 的默认编码是 GBK）。

背景：GBK 系统上，Python 对「管道 / 重定向」的 stdout 默认用系统编码。
歌词、曲名、日志里一旦出现 GBK 表示不了的字符（特殊符号、日文、emoji），
轻则乱码，重则 `UnicodeEncodeError: 'gbk' codec can't encode character ...`。

做法：进程启动早期把 sys.stdout / sys.stderr 重设为 UTF-8：
  * Windows 控制台自 Python 3.6 起走 UTF-16 接口，设为 UTF-8 后中文与
    任意字符都能正确显示（与系统代码页无关）；
  * 输出到文件 / 管道时则产生 UTF-8 字节，不再依赖系统的 GBK；
  * 全程不做进程重启，run.bat / IDE / 双击 / 快捷方式都不受影响。

只改编码，不动缓冲等其它行为；任何异常都静默跳过，绝不影响启动。
"""

import sys


def ensure_utf8():
    """把 stdout / stderr 切成 UTF-8；已经是 UTF-8 时不做任何事。"""
    changed = False
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if stream is None:                 # pythonw：没有控制台
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc.replace("-", "") == "utf8":
                continue
            stream.reconfigure(encoding="utf-8", errors="replace")
            changed = True
        except Exception:                  # 流被替换过 / 不支持 reconfigure
            pass
    return changed
