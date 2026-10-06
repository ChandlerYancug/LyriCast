# -*- coding: utf-8 -*-
"""Apple Music 凭证的可视化配置窗口（托盘菜单 →「Apple Music 凭证」）。

两条路都在窗口内完成，**不需要命令行**：
- 「从浏览器自动获取」：后台线程读 Chrome / Edge / Firefox 的 cookie
  （browser_cookie3），带进度提示，结果直接显示在窗口里；
- 「手动粘贴」：把 `media-user-token` 的值贴进输入框，点「保存」。

保存后回调通知调用方（重抓歌词）。凭证文件位置由
`speakers.paths.token_path()` 决定（exe 模式在 %LOCALAPPDATA%\\LyriCast）。
"""

import os
import threading
import time

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

import apple_music
from speakers.http import APP_NAME

_COLOR_OK = "color: #7fd08a;"
_COLOR_WARN = "color: #e0b25c;"
_COLOR_ERR = "color: #e07c6c;"
_COLOR_IDLE = "color: #cfd6de;"


class TokenDialog(QDialog):
    auto_done = pyqtSignal(str, str)          # (token, 说明文本)

    def __init__(self, on_saved=None, logger=None):
        super().__init__(None)
        self._on_saved = on_saved
        self._log = logger
        self._busy = False

        self.setWindowTitle("%s · Apple Music 凭证" % APP_NAME)
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(
            "逐词歌词和中文翻译需要一次 Apple Music 凭证（有效期几个月）。\n"
            "下面两种方式任选一种，都在这个窗口里完成，不用命令行。", self)
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.status = QLabel(self)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.auto_btn = QPushButton("从浏览器自动获取（推荐）", self)
        self.auto_btn.clicked.connect(self._auto)
        lay.addWidget(self.auto_btn)

        sep = QLabel("— 或者手动粘贴 —", self)
        sep.setStyleSheet("color: #9aa3ad;")
        lay.addWidget(sep)

        row = QHBoxLayout()
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("把 media-user-token 的值粘贴到这里")
        self.save_btn = QPushButton("保存", self)
        self.save_btn.clicked.connect(self._save_paste)
        row.addWidget(self.edit, 1)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        help_lab = QLabel(
            "手动获取（最可靠）：浏览器登录 https://music.apple.com → F12 →\n"
            "Application → Cookies → https://music.apple.com → 复制\n"
            "media-user-token 的值（新版 Chrome / Edge 会加密 cookie，\n"
            "自动读取不了时就用这种方式）", self)
        help_lab.setStyleSheet("color: #9aa3ad; font-size: 11px;")
        help_lab.setWordWrap(True)
        lay.addWidget(help_lab)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        self.auto_done.connect(self._on_auto)
        self._refresh_status()

    # ------------------------------------------------------------------ #
    def _refresh_status(self):
        n, ts = self._token_state()
        if n:
            self.status.setText("当前状态：已配置（%d 字符，%s 保存）" % (n, ts))
            self.status.setStyleSheet(_COLOR_OK)
        else:
            self.status.setText(
                "当前状态：未配置（现在只有普通歌词，没有逐词和翻译）")
            self.status.setStyleSheet(_COLOR_WARN)

    @staticmethod
    def _token_state():
        path = apple_music.TOKEN_FILE
        try:
            with open(path, "r", encoding="utf-8") as fp:
                n = len(fp.read().strip())
            ts = time.strftime("%m-%d %H:%M",
                               time.localtime(os.path.getmtime(path)))
            return n, ts
        except OSError:
            return 0, ""

    def _set_busy(self, busy):
        self._busy = busy
        self.auto_btn.setEnabled(not busy)
        self.save_btn.setEnabled(not busy)
        self.edit.setEnabled(not busy)

    # ------------------------------------------------------------------ #
    def _auto(self):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在读取浏览器 cookie（Chrome / Edge / Firefox）…")
        self.status.setStyleSheet(_COLOR_IDLE)

        def work():
            try:
                token, logs = apple_music.find_browser_token()
            except Exception as exc:
                token, logs = "", ["读取失败：%r" % (exc,)]
            try:
                self.auto_done.emit(token, "\n".join(logs))
            except RuntimeError:              # 窗口已关闭
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_auto(self, token, logs):
        self._set_busy(False)
        if token and apple_music.save_user_token(token):
            if self._log:
                self._log.info("Apple 凭证已更新（%d 字符）", len(token))
            self.status.setText("✓ 已获取并保存（%d 字符），稍后自动关闭…"
                                % len(token))
            self.status.setStyleSheet(_COLOR_OK)
            self._finish()
            return
        self.status.setText("没拿到凭证：\n%s\n\n"
                            "新版 Chrome / Edge 的 cookie 有加密，读不到属正常——\n"
                            "按下方步骤手动复制，粘到上面输入框点「保存」即可。"
                            % (logs or ""))
        self.status.setStyleSheet(_COLOR_ERR)
        self.edit.setFocus()

    def _save_paste(self):
        token = self.edit.text().strip()
        if not token:
            self.status.setText("输入框是空的 —— 先把 media-user-token 粘贴进来。")
            self.status.setStyleSheet(_COLOR_WARN)
            return
        if len(token) < 20:
            self.status.setText("这段内容看起来太短，不像 media-user-token"
                                "（一般一百多字符），再检查一下？")
            self.status.setStyleSheet(_COLOR_WARN)
            return
        if apple_music.save_user_token(token):
            if self._log:
                self._log.info("Apple 凭证已保存（%d 字符）", len(token))
            self.status.setText("✓ 已保存（%d 字符），稍后自动关闭…" % len(token))
            self.status.setStyleSheet(_COLOR_OK)
            self._finish()
        else:
            self.status.setText("写入失败：%s" % apple_music.TOKEN_FILE)
            self.status.setStyleSheet(_COLOR_ERR)

    def _finish(self):
        """保存成功：通知外部重抓歌词，稍后自动关闭窗口。"""
        if self._on_saved:
            try:
                self._on_saved()
            except Exception:
                pass
        QTimer.singleShot(1100, self.accept)
