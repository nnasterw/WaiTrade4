from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def _月初(年: int, 月: int) -> date:
    return date(年, 月, 1)


def _前移月份(日期: date, 月数: int) -> date:
    序号 = 日期.year * 12 + 日期.month - 1 - 月数
    return _月初(序号 // 12, 序号 % 12 + 1)


def _月末(月初: date) -> date:
    下月 = _前移月份(月初, -1)
    return date.fromordinal(下月.toordinal() - 1)


@dataclass(frozen=True)
class 验收窗口:
    周期一: tuple[date, date]
    周期二: tuple[date, date]
    周期三: tuple[date, date]
    周期四: tuple[date, date]

    @property
    def 周期(self) -> tuple[tuple[date, date], tuple[date, date], tuple[date, date], tuple[date, date]]:
        return (self.周期一, self.周期二, self.周期三, self.周期四)


def 生成验收窗口(截至日: date) -> 验收窗口:
    """以截至日前一个完整自然月为末月，冻结连续24个月的四个半年周期。"""
    最近完整月月初 = _前移月份(_月初(截至日.year, 截至日.month), 1)
    起始月 = _前移月份(最近完整月月初, 23)
    周期二开始月 = _前移月份(最近完整月月初, 17)
    周期三开始月 = _前移月份(最近完整月月初, 11)
    周期四开始月 = _前移月份(最近完整月月初, 5)
    return 验收窗口(
        周期一=(起始月, _月末(_前移月份(周期二开始月, 1))),
        周期二=(周期二开始月, _月末(_前移月份(周期三开始月, 1))),
        周期三=(周期三开始月, _月末(_前移月份(周期四开始月, 1))),
        周期四=(周期四开始月, _月末(最近完整月月初)),
    )
