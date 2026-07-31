from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable

from wt4.mt5后台 import MT5后台进程


@dataclass(frozen=True)
class 中断无污染结果:
    被中断返回码: int | None
    未中断返回码: int | None
    被中断已退出: bool
    被中断时仍运行: bool
    未中断完成: bool

    @property
    def 通过(self) -> bool:
        return self.被中断时仍运行 and self.被中断已退出 and self.未中断完成


class 两实例中断探测器:
    """只中断本轮甲进程组，并验证乙不受影响地完成。"""

    def __init__(self, 启动甲: Callable[[], MT5后台进程], 启动乙: Callable[[], MT5后台进程]) -> None:
        self._启动甲 = 启动甲
        self._启动乙 = 启动乙

    def 执行(self, 启动宽限秒: float, 未中断超时秒: int, 第二实例启动间隔秒: float = 2) -> 中断无污染结果:
        if 启动宽限秒 <= 0 or 未中断超时秒 <= 0 or 第二实例启动间隔秒 < 0:
            raise ValueError("中断探测的启动宽限与超时必须为正")
        甲 = self._启动甲()
        # 两个独立 Prefix 仍共享本机环回地址。先让甲完成本地 Agent
        # 端口登记，乙即可按 MT5 的常规探测逻辑占用下一可用端口，避免
        # 二者在同一瞬间竞争 3000 而产生伪失败。
        sleep(第二实例启动间隔秒)
        乙 = self._启动乙()
        截止 = monotonic() + 启动宽限秒
        while monotonic() < 截止:
            if 甲.快照().状态 == "已退出" or 乙.快照().状态 == "已退出":
                break
            sleep(0.1)
        被中断时仍运行 = 甲.快照().状态 == "运行中"
        # 不使用全局 wineserver/pkill；该调用只向甲创建的进程组发信号。
        甲.终止自有进程组()
        甲返回码 = 甲.等待(10)
        乙返回码 = 乙.等待(未中断超时秒)
        if 乙返回码 is None:
            乙.终止自有进程组()
            乙返回码 = 乙.等待(10)
        return 中断无污染结果(
            甲返回码, 乙返回码, 甲.快照().状态 == "已退出", 被中断时仍运行, 乙返回码 == 0
        )
