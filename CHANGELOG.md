# 更新记录

写法：每个发布版本一段，点明"用户能感知的改动"。GitHub 的
[Releases](https://github.com/ChandlerYancug/LyriCast/releases) 页与此同步。
两个通道：正式版（数字版本号）与 **调试版**（tag 带 `debug`，发布为 pre-release，不覆盖正式版）。

## v0.3.1（2026-10-07）

打包与分发：**Windows 免安装版（exe）**。

- 新增 PyInstaller 打包脚本 `dev/build_exe.py`，产物 `dist/LyriCast/`（绿色版，双击即用）
- 新增 GitHub Actions 发布流水线（`.github/workflows/release.yml`）：打 `v*` tag
  自动构建 exe 并挂到对应 Release；tag 里带 `debug` 的发布为 pre-release（调试版）
- exe 模式下可写数据（`config.json` / `am_token.txt` / `cache/`）放到
  `%LOCALAPPDATA%\LyriCast\`（和日志同一处），exe 放哪都能正常保存；
  源码运行仍是项目目录，老用户无感
- 「自动获取 Apple 凭证」改为**应用内直接读浏览器 cookie**（不再启动外部命令，
  exe 里也能用）；命令行脚本 `get_apple_token.py` 保留给源码用户
- exe 里同样随包字体 / 图标 / 开机自启（快捷方式指向 exe 自己）
- 修复打包后“找不到音箱后端”的问题（后端是动态加载的，需要在包内静态标记）

## v0.3.0（2026-10-07）

首个正式发布：从"只支持 Sonos"泛化为**任何局域网音箱**，
并按照实际使用的反馈打磨了黑胶播放器的皮肤与启动体验。

### 新增

- **唱臂皮肤（6 支）**：碳纤维（宝碟风，默认）/ 香槟金 / 镜面铬 S 形 /
  午夜蓝 / 象牙白·玫瑰金 / 胡桃木·黄铜。托盘菜单「换一支唱臂」或播放器里按 `N` 轮换
- **每首歌的皮肤记忆**：切歌不再自动乱换 —— 没记过的歌用你上一次挑的那款；
  你在某首歌里挑过的彩胶 / 唱臂会被记住，再放这首歌自动恢复（存在 `config.json` 的
  `song_skins`，最多 500 首）
- **手动输入音箱 IP**（托盘菜单）：完全绕过 SSDP 搜索；防火墙 / VPN 挡住组播时的兜底
- **Apple Music 凭证一键获取**：托盘菜单「Apple Music 凭证」→「自动获取」，
  或双击 `get_apple_token.bat`（逐词歌词与翻译需要）
- `run-console.bat`（要看实时日志时用）与托盘「查看运行日志（记事本）」
- 断线自动重新发现音箱；滚动日志（托盘→打开日志文件夹）；托盘里直接切换音箱

### 改进

- 可插拔音箱后端：Sonos（含多房间）/ 通用 DLNA-UPnP / Windows 系统媒体会话（SMTC）
- SSDP 发现改为多轮重发（Wi-Fi 丢包容错）
- 启动完全静默（`pythonw`，无黑色控制台窗口）
- 任务栏图标固定为 LyriCast（不再是 Python 图标）
- 全屏：修掉 Windows 11 圆角 / 描边导致的屏幕边缘细白边
- 中文 Windows 编码：输出统一切 UTF-8，不再 GBK 乱码；
  `run.bat` / `debug.bat` 改纯 ASCII（GBK 系统下 cmd 解析不再错乱），缺 Python 有明确提示
- 依赖装进项目内 `.venv`（`run.bat` 自动创建），不污染系统 Python；
  `requirements.txt` 去掉非 ASCII 注释、新增国内镜像提示

### 修复（含 0.2 阶段）

- 歌词左边被裁切；翻译"汇聚"动画卡顿；中英混排时翻译英文偏上 / 句末下跳
- 全屏播放器：翻译折行时不再压住下一句歌词
