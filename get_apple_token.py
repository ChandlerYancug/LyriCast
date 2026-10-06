# -*- coding: utf-8 -*-
"""一键更新 Apple Music 凭证（am_token.txt）。

Apple 的歌词接口需要你登录后的 media-user-token（有效期几个月）。
过期后重新在浏览器登录 https://music.apple.com，再运行本脚本即可刷新。

说明：
  - 依次尝试从 Chrome / Edge / Firefox 里读；
  - 部分新版浏览器会加密 cookie（读不到时），那就手动取：
    浏览器 F12 -> Application -> Cookies -> https://music.apple.com
    -> 复制 media-user-token 的值 -> 保存到本目录 am_token.txt
  - 本脚本只读取 music.apple.com 这一个 cookie，不碰其它数据。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "am_token.txt")
DOMAIN = "music.apple.com"
NAME = "media-user-token"

try:                                    # 中文 Windows 默认 GBK:输出流切 UTF-8
    from utf8mode import ensure_utf8
    ensure_utf8()
except Exception:
    pass


def load(fn):
    try:
        return fn(domain_name=DOMAIN)
    except TypeError:
        return fn()


def try_one(fn, label):
    try:
        cj = load(fn)
    except Exception as e:
        print("[%s] 打不开 cookie 库: %s" % (label, e))
        return None
    seen = 0
    for c in cj:
        if DOMAIN in (c.domain or ""):
            seen += 1
            if c.name == NAME and c.value:
                return c.value
    print("[%s] 没有 %s（该域 cookie 数：%d）" % (label, NAME, seen))
    return None


def main():
    try:
        import browser_cookie3 as bc
    except ImportError:
        print("需要先安装：python -m pip install browser_cookie3")
        return 1
    token = None
    for fn, label in ((bc.chrome, "Chrome"), (bc.edge, "Edge"),
                      (bc.firefox, "Firefox")):
        token = try_one(fn, label)
        if token:
            print("[%s] 找到 media-user-token（长度 %d，开头 %s...）"
                  % (label, len(token), token[:12]))
            break
    if not token:
        print("没找到凭证：先登录 https://music.apple.com 再运行本脚本，"
              "或手动从 F12 复制 media-user-token 到 am_token.txt")
        return 1
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(token)
    print("已保存到 am_token.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
