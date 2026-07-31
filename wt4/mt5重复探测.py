from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wt4.mt5报告 import MT5报告摘要
from wt4.编排 import 实验状态, 执行结果


@dataclass(frozen=True)
class 单实例重复结果:
    首次: 执行结果
    再次: 执行结果
    报告完整: bool
    逐笔一致: bool

    @property
    def 通过(self) -> bool:
        return (
            self.首次.状态 is 实验状态.已归档
            and self.再次.状态 is 实验状态.已归档
            and self.报告完整
            and self.逐笔一致
        )


class 单实例MT5重复探测器:
    """在同一隔离实例顺序复跑两次，拒绝将任何解析失败视为一致。"""

    def __init__(
        self,
        执行函数: Callable[[str], 执行结果],
        报告路径: Callable[[str], Path],
        报告解析器: Callable[[Path], MT5报告摘要],
    ) -> None:
        self._执行函数 = 执行函数
        self._报告路径 = 报告路径
        self._报告解析器 = 报告解析器

    def 执行(self) -> 单实例重复结果:
        首次 = self._执行函数("首次")
        再次 = self._执行函数("再次")
        if 首次.状态 is not 实验状态.已归档 or 再次.状态 is not 实验状态.已归档:
            return 单实例重复结果(首次, 再次, False, False)
        try:
            首次报告 = self._报告解析器(self._报告路径("首次"))
            再次报告 = self._报告解析器(self._报告路径("再次"))
        except Exception:
            return 单实例重复结果(首次, 再次, False, False)
        # ``MT5报告摘要`` 已排除展示生成时间，只保留报告的身份、统计、
        # Orders 与 Deals。整体相等故同时证明逐笔、订单与汇总可重演。
        return 单实例重复结果(首次, 再次, True, 首次报告 == 再次报告)
