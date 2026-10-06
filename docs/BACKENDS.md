# 音箱后端（`speakers/`）

## 一句话架构

`speakers/` 里每个后端只做三件事：

1. **读**播放状态（`now_playing()`：歌名、歌手、封面、进度、状态）；
2. **控**（播放 / 暂停 / 切歌 / 拖进度 / 音量；只有用户点了才会发）；
3. **订阅**事件（UPnP/GENA，seek 后能瞬间同步）。

支持哪些操作由后端的 `capabilities` 声明，界面据此隐藏不支持的按钮。
主程序只认识 `Backend` / `NowPlaying` 这套统一接口，不关心对面是什么设备。

```text
speakers/
  base.py       Backend、NowPlaying、capabilities、公共小工具
  http.py       HTTP 小工具（统一 UA、下载封面）
  log.py        日志（滚动文件 + 控制台）
  discovery.py  SSDP 局域网发现（Sonos + DLNA 一起找）
  sonos.py      Sonos 后端
  upnp.py       通用 DLNA / UPnP-AV 后端
  smtc.py       Windows 系统媒体会话后端（电脑自己播放时读）
```

配置里对应的字段：

| 字段 | 说明 |
| --- | --- |
| `speaker_type` | `auto`（默认）/ `sonos` / `upnp` / `smtc`（将来还有 `macos` / `listen`） |
| `speaker_host` | 音箱 IP；留空则启动时自动发现（`smtc` 不需要） |
| `speaker_name` | 想固定某台设备时填它的房间名 / 友好名 |
| `speaker_location` | 仅 upnp 需要：设备描述 URL，如 `http://192.168.1.20:49152/description.xml`（发现一次后记下来，重连更快） |

> 也可以完全不管配置：托盘菜单 → **选择音箱** 里会列出搜到的设备（同名设备带 IP 区分），
> 点一下就切换；Windows 上装了 `smtc` 依赖的话，菜单里还会有「本机媒体会话」一项。

## 现状

| kind | 状态 | 说明 |
| --- | --- | --- |
| `sonos` | 已支持 | Sonos 全系，含多房间 / 立体声配对（跟随协调器） |
| `upnp` | 已支持 | 通用 DLNA / UPnP-AV 渲染器：WiiM、HEOS（Denon / Marantz）、MusicCast（雅马哈）、Bluesound、Volumio、VLC / foobar2000 的 UPnP 输出等 |
| `smtc` | 已支持（Windows） | 系统媒体会话：**电脑自己播放**时读（含电脑 AirPlay 投给 HomePod）。依赖：在仓库目录 `pip install -e ".[smtc]"`；没有音量控制（系统音量自管） |
| `macos` | 计划中 | macOS Now Playing（MediaRemote） |
| `listen` | 计划中 | 麦克风 + 音频指纹（任何音箱都能用，见下） |

## HomePod / AirPlay 的现实

先说结论：**HomePod 没法像 Sonos 那样从网络上直接读播放状态。**

- AirPlay 2 的元数据是私有（加密）协议，不对外开放；
- HomePod 也没有 DLNA / UPnP 接口，SSDP 里根本发现不到它。

所以只有这三条路：

### 0. 最省事：同时投送给局域网里的一台 Sonos / DLNA 音箱（推荐）

iPhone / iPad 的 AirPlay 支持**多选输出**：把「HomePod mini + 局域网里的 Sonos（或任何
DLNA 音箱）」同时勾上，两边同步出声。这样 HomePod 负责放音，**Sonos 负责把歌名歌手
报给 LyriCast** —— 就完全不需要识别/猜歌了，歌词和进度都是准的。
（反过来也成立：任何能被 LyriCast 读到的音箱，都可以当 HomePod 的“元数据代理”。）

### 1. 电脑自己播放时，读系统媒体会话

Apple Music / Spotify 桌面端播放 → AirPlay 投给 HomePod。这时歌名歌手在电脑的系统媒体会话里：
Windows 用 SMTC（本项目的 `smtc` 后端）、macOS 用 MediaRemote（计划中），都能读到。

限制：必须**从电脑发起播放**。手机直接 AirPlay 给 HomePod 时，电脑什么都不知道（走第 0 条）。

### 2. 麦克风 + 音频指纹

电脑麦克风听音箱在放什么，用音频指纹识别出歌。任何音箱都能用，包括 HomePod。

限制：

- 电脑得能听清（同一房间、环境不吵、音箱音量别太小）；
- 识别有几秒延迟，歌词位置对不齐 → 周期性重新识别 + 手动偏移（`lyrics_offset_sec`）校正；
- 切歌瞬间会慢半拍。

对应可选依赖 `.[listen]`（`sounddevice` + `shazamio`），目前是路线图，还没实现。

### 3. 手机侧快捷指令 POST 当前歌曲

快捷指令 + 个人自动化，把当前播放的歌 POST 到本机。能用，但依赖用户自己折腾，
而且拿到的经常是「开始播放时」的歌而不是实时的。不推荐，仅作兜底。

## 如何写一个新后端

1. 复制 `speakers/upnp.py`（最通用）或任意现有后端当模板，新建 `speakers/mybox.py`；
2. 继承 `Backend`，定好 `kind`（和配置里的 `speaker_type` 一致）；
3. 声明 `capabilities`：`CAN_CONTROL` / `CAN_SEEK` / `CAN_VOLUME` / `CAN_EVENTS` / `CAN_COORDINATOR`，只声明真能做的；
4. 实现 `now_playing()`（必须）；`get_transport_state()`、`get_volume()` 按需；
5. 控制方法（`play` / `pause` / `next_track` / `seek` / `set_volume` …）按需覆写，不支持就用基类默认（抛 `NotSupported`，界面不会调用）；
6. 需要事件订阅就实现 `event_urls()`；多房间设备实现 `coordinator()`；
7. 在 `speakers/__init__.py` 的 `_BACKENDS` 里注册：`"mybox": ("speakers.mybox", "MyBoxBackend")`；
8. 写测试：mock 掉 HTTP 响应（放 `tests/`），别在测试里连真设备；
9. 在本文档「现状」表里补一行。

设备能用 SSDP 发现的话，再给 `discovery.py` 的 `M_SEARCH_STS` 加一条 ST（可选）。

## 已知限制

- **元数据各家不齐**：有的没有封面 URL，有的没有专辑名，有的把「歌手 - 歌名」塞进一个字段（`split_title_artist()` 兜底拆）；
- **DLNA 音量服务可能缺失**：没有 RenderingControl 的设备 `get_volume()` 返回 -1，界面不显示音量；
- **RelTime 粒度**：部分设备进度只有 1 秒粒度，轮询时看着一跳一跳（`relclock.py` 会在两次校正之间平滑推算）；
- **事件订阅不保证**：有的设备 GENA 事件地址残缺或私有，会退回轮询，seek 后同步慢几秒；
- **待机 / 空闲**：设备待机时可能读不到状态或超时，界面显示为空；
- **AirPlay / 蓝牙**：读不到（见上），不要指望。
