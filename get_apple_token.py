# -*- coding: utf-8 -*-
"""一键更新 Apple Music 凭证（am_token.txt）——命令行版。

图形界面版的入口在应用里：托盘菜单 →「Apple Music 凭证（逐词/翻译）…」→
「自动获取」，效果完全一样，不用碰命令行。

Apple 的歌词接口需要你登录后的 media-user-token（有效期几个月）。
过期后重新在浏览器登录 https://music.apple.com，再运行本脚本即可刷新。

说明：
  - 依次尝试从 Chrome / Edge / Firefox 里读（浏览器先登录 music.apple.com）；
  - 部分新版浏览器会加密 cookie（读不到时），那就手动取：
    浏览器 F12 -> Application -> Cookies -> https://music.apple.com
    -> 复制 media-user-token 的值 -> 保存到 am_token.txt
  - 只读取 music.apple.com 这一个 cookie，不碰其它数据；
  - exe（打包版）模式下 am_token.txt 在 %LOCALAPPDATA%\\LyriCast\\ 里。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

try:                                    # 中文 Windows 默认 GBK:输出流切 UTF-8
    from utf8mode import ensure_utf8
    ensure_utf8()
except Exception:
    pass


def main():
    try:
        import apple_music
    except Exception as exc:
        print("无法导入项目模块（在项目根目录下运行本脚本）：%r" % (exc,))
        return 1

    token, logs = apple_music.find_browser_token()
    for line in logs:
        print(line)
    if not token:
        print("没找到凭证：先登录 https://music.apple.com 再运行本脚本，"
              "或手动从 F12 复制 media-user-token 到 am_token.txt")
        return 1
    if not apple_music.save_user_token(token):
        print("写入失败：%s" % apple_music.TOKEN_FILE)
        return 1
    print("已保存到 %s" % apple_music.TOKEN_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
