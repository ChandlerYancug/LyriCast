# -*- coding: utf-8 -*-
"""RelTime 台阶边沿时钟：把 Sonos 的整秒读数校准成精确播放位置。

背景：Sonos 的 `GetPositionInfo` 只报**向下取整的整秒**（读数 n 代表真实
位置在 [n, n+1)）。任何"猜测补偿"都会踩到两个坑：

  * 补偿取窗口中点（+0.5s）会系统性超前——因为轮询周期与 1 秒整除时
    采样相位是**锁定**的，读数总是在窗口早期被发现，于是歌词"还没唱
    就先滚"；
  * 补偿取太小（如 +0.13s）在另外一种相位下又会永久滞后半拍。

本模块不再猜：把每次读数 **n -> n+1 的跳变**当成"位置刚跨过整数"的
物理信号（台阶边沿）。边沿必然发生在两次轮询之间，取两次采样时刻的
中点作为边沿时刻 t_edge，就有

    t_edge - n ≈ b（常数：PC 时钟与歌曲位置的相位差）

多个边沿的 b 平均后，实时位置直接由 `pos(t) = t - b` 给出。整秒取整
和采样相位造成的系统偏差就被消掉了，剩下的只有亚采样间隔的估计噪声
（轮询在 263ms 附近还会使边沿相位逐圈漂移，平均后进一步收敛）。

暂停时位置冻结，用 `_freeze` 保持画面停在精确点上；恢复后先从冻结
位置起跑，同时重新收集边沿（暂停前后的时钟映射不同，旧样本作废）。
"""

import time

WINDOW = 8          # 边沿样本滑窗长度
MIN_SAMPLES = 3     # 至少多少个边沿才认为 b 可信
MAX_GAP = 1.2       # 两次采样间隔超过这个值就不当边沿（中间断过）

class RelTimeEdgeClock:
    """喂入整秒读数，输出校准后的精确位置。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._last_sec = None
        self._prev_ts = None
        self._edges = []
        self._freeze = None
        self._was_playing = False
        self._resume_ts = None
        self._resume_pos = None

    def update(self, sec, playing, now=None):
        """喂入一个整秒读数，返回 (position, precise)。

        precise=True 表示 position 由边沿时钟实测推导，应直接采信；
        precise=False 表示只有原始整秒读数（刚启动 / seek 后不久），
        调用方应使用自己的兜底补偿。
        """
        now = time.monotonic() if now is None else now
        sec = float(sec)
        prev = self._prev_ts

        # 读数发生变化才处理（同一秒的重复轮询不用重复算）
        if self._last_sec is None or sec != self._last_sec:
            step = sec - self._last_sec if self._last_sec is not None else 0.0
            gap = now - prev if prev is not None else 99.0
            if (playing and self._last_sec is not None and prev is not None
                    and abs(step - 1.0) < 0.25 and 0.0 < gap < MAX_GAP):
                # 恰好跨过一秒：记一条带权边沿样本。慢轮询（间隔大）的
                # 中点误差随间隔成比例放大，权重取 1/gap²——用物理时钟
                # 跨度衡量这次读数该被信任多少（AMLL 同思路）。
                t_edge = (prev + now) * 0.5
                w = 1.0 / max(gap, 0.05) ** 2
                self._edges.append((t_edge - sec, w))
                if len(self._edges) > WINDOW:
                    self._edges.pop(0)
            elif (self._last_sec is not None and abs(step - 1.0) >= 0.25
                    and not self._plausible(step, gap)):
                # 与流逝时间对不上的大跳（seek / 换歌）：旧样本作废。
                # 只是漏采了几次（Δ 仍≈流逝时间）时不清校准。
                self._edges.clear()
                self._freeze = None
                self._resume_pos = None
            self._last_sec = sec

        if playing:
            if not self._was_playing:
                # 刚从暂停恢复（或首帧）：先从冻结位置接续起跑
                self._resume_ts = ((prev + now) * 0.5 if prev is not None
                                   else now)
                self._resume_pos = self._freeze
                self._was_playing = True
            derived = None
            if len(self._edges) >= MIN_SAMPLES:
                b = (sum(s * w for s, w in self._edges)
                     / sum(w for _, w in self._edges))
                derived = now - b
            elif (self._resume_pos is not None
                  and self._resume_ts is not None):
                derived = self._resume_pos + (now - self._resume_ts)
            if derived is not None and sec + 0.2 <= derived <= sec + 1.2:
                self._freeze = derived
                result = (derived, True)
            else:
                result = (sec, False)
        else:
            # 暂停：保持画面冻结在精确点上
            if self._was_playing:
                self._edges.clear()
                self._was_playing = False
            if (self._freeze is not None
                    and sec + 0.3 <= self._freeze <= sec + 1.3):
                result = (self._freeze, True)
            else:
                result = (sec, False)

        self._prev_ts = now
        return result

    @staticmethod
    def _plausible(step, gap):
        """这次读数跳变是否与流逝的物理时间相容。

        正常播放时位置推进 ≈ 流逝时间（整秒取整最多差 1s）；漏采样会
        一次前进 2 秒左右，也落在容差内。真正的 seek / 换歌会让两者
        差出很远，只有那种情况才值得清掉已有校准。
        """
        if gap >= 99.0:
            return False
        return abs(step - gap) <= 1.05
