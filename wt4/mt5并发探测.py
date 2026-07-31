from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from wt4.mt5报告 import MT5报告摘要
from wt4.编排 import 实验状态, 执行结果


@dataclass(frozen=True)
class 并发探测结果:
    串行结果: dict[str, 执行结果]
    并行结果: dict[str, 执行结果]
    串行墙钟秒: float
    并行墙钟秒: float
    两实例逐笔一致: bool
    并发失败率为零且有效提速: bool

    @property
    def 加速比(self) -> float:
        return self.串行墙钟秒 / self.并行墙钟秒 if self.并行墙钟秒 > 0 else 0.0


class 两实例MT5并发探测器:
    """在已校验的完全隔离实例上比较串行与并行。

    执行函数必须各自只写入传入暂存目录；这样超时的清理职责仍留在
    ``单实例MT5探测执行器``，不会碰另一实例或系统中既有 Wine 进程。
    """

    def __init__(
        self,
        执行函数: dict[str, Callable[[Path], 执行结果]],
        报告解析器: Callable[[Path], MT5报告摘要],
        最低加速比: float = 1.10,
    ) -> None:
        if set(执行函数) != {"甲", "乙"}:
            raise ValueError("并发探测必须且只能包含甲、乙两个隔离实例")
        if 最低加速比 <= 1:
            raise ValueError("最低加速比必须大于 1，避免把计时噪声当作并发能力")
        self._执行函数 = 执行函数
        self._报告解析器 = 报告解析器
        self._最低加速比 = 最低加速比

    def 执行(self, 根目录: Path) -> 并发探测结果:
        if not 根目录.is_dir():
            raise ValueError(f"并发探测根目录不存在: {根目录}")
        串行结果, 串行秒 = self._串行执行(根目录)
        并行结果, 并行秒 = self._并行执行(根目录)
        逐笔一致 = self._逐笔一致(串行结果, 并行结果, 根目录)
        全部成功 = all(
            结果.状态 is 实验状态.已归档
            for 结果 in (*串行结果.values(), *并行结果.values())
        )
        有效提速 = 并行秒 > 0 and 串行秒 / 并行秒 >= self._最低加速比
        return 并发探测结果(
            串行结果, 并行结果, 串行秒, 并行秒, 逐笔一致, 全部成功 and 有效提速
        )

    def _串行执行(self, 根目录: Path) -> tuple[dict[str, 执行结果], float]:
        起点 = monotonic()
        结果 = {名称: self._运行一项("串行", 名称, 根目录) for 名称 in ("甲", "乙")}
        return 结果, monotonic() - 起点

    def _并行执行(self, 根目录: Path) -> tuple[dict[str, 执行结果], float]:
        起点 = monotonic()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="wt4-mt5") as 线程池:
            任务 = {名称: 线程池.submit(self._运行一项, "并行", 名称, 根目录) for 名称 in ("甲", "乙")}
            结果 = {名称: 任务[名称].result() for 名称 in ("甲", "乙")}
        return 结果, monotonic() - 起点

    def _运行一项(self, 方式: str, 名称: str, 根目录: Path) -> 执行结果:
        暂存目录 = 根目录 / 方式 / 名称
        暂存目录.mkdir(parents=True)
        return self._执行函数[名称](暂存目录)

    def _逐笔一致(
        self,
        串行结果: dict[str, 执行结果],
        并行结果: dict[str, 执行结果],
        根目录: Path,
    ) -> bool:
        基准成交: tuple[object, ...] | None = None
        for 名称 in ("甲", "乙"):
            if 串行结果[名称].状态 is not 实验状态.已归档 or 并行结果[名称].状态 is not 实验状态.已归档:
                return False
            try:
                串行报告 = self._报告解析器(根目录 / "串行" / 名称 / "报告.html")
                并行报告 = self._报告解析器(根目录 / "并行" / 名称 / "报告.html")
            except Exception:
                return False
            # 只比较不可由报告生成时间等展示字段影响的成交事实。每个
            # 实例的串行/并行结果一致还不够，甲、乙也必须完全一致。
            if 串行报告.成交 != 并行报告.成交:
                return False
            if 基准成交 is None:
                基准成交 = 串行报告.成交
            elif 串行报告.成交 != 基准成交:
                return False
        return True
