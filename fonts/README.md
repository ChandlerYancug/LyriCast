# fonts/（随包字体）

**clone 下来就能用**：这个目录里的字体都是 **SIL Open Font License (OFL) 开源字体**，
可以随仓库分发；程序启动时会自动注册它们，不需要你装任何东西。

| 文件 | 字体 | 用途 | 许可 |
| --- | --- | --- | --- |
| `Inter-*.ttf`（Regular / Medium / SemiBold / Bold / Black） | [Inter](https://github.com/rsms/inter) | 拉丁文字（歌词正文、标题、数字） | OFL 1.1，见 `LICENSE-Inter.txt` |
| `NotoSansHans-*.otf`（Regular / Bold / Black） | 思源黑体 / Noto Sans CJK 简体子集（Noto Sans S Chinese） | 中文回退 | OFL 1.1，见 `LICENSE-NotoSansSC.txt` |

字重怎么用：歌词正文 / 翻译 / 标题都是 **Black（900）**，歌名下方的小字是
**Bold / SemiBold**，悬浮条的非当前行是 **Regular** —— 和原版的观感一致。

## 想要“原版那味”：SF Pro Display（可选，不随仓库分发）

原版拉丁字体是 Apple 的 **SF Pro Display**（有版权，不能公开再分发）。
如果你已经有它（自行从 Apple 官方渠道获取），把它放进这个目录或装到系统即可 ——
字体链里 SF Pro 的优先级高于 Inter，放进去就会自动生效；**不要把它提交到仓库**
（`.gitignore` 已经挡了 `fonts/SF-Pro-*`）。

## 换字体

`config.json` 里：

- `font_family`：拉丁字体名（默认 `SF Pro Display`，没有就自动落到随包的 Inter）
- `cjk_font`：中文回退字体名（默认 `Noto Sans SC`；随包的思源子集族名是
  `Noto Sans S Chinese`，两者都在链里，装哪个用哪个）

字体链按「家族名逐级点名 + 按字重回退」工作：缺哪个字重就自动降一档，
缺失整个字体就回退到下一个家族，不会报错。

## 嫌仓库大？

三个中文字体文件约 25 MB（主要是汉字字库本身），不想带就删掉
`NotoSansHans-*.otf`，中文会自动用系统字体（Windows 微软雅黑 / macOS 苹方等）。
