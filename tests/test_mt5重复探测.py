from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from wt4.mt5报告 import MT5报告摘要
from wt4.mt5重复探测 import 单实例MT5重复探测器
from wt4.编排 import 实验状态, 执行结果


def _报告(成交号: int = 1) -> MT5报告摘要:
    return MT5报告摘要("EA", "BTCUSDm", "M1", "2025.01.01", "2025.01.02", Decimal("300"), "real ticks", Decimal("100"), Decimal("1"), 1, Decimal("1.1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), (), ())


def test_两次归档且严格报告相同才通过(tmp_path: Path) -> None:
    报告 = {"首次": _报告(), "再次": _报告()}
    探测 = 单实例MT5重复探测器(
        lambda _: 执行结果(实验状态.已归档, {}, {}),
        lambda 轮次: tmp_path / 轮次,
        lambda 路径: 报告[路径.name],
    ).执行()

    assert 探测.报告完整 is True
    assert 探测.逐笔一致 is True
    assert 探测.通过 is True


def test_任一报告不一致或解析失败均拒绝(tmp_path: Path) -> None:
    报告 = {"首次": _报告(), "再次": MT5报告摘要("EA", "BTCUSDm", "M1", "2025.01.01", "2025.01.02", Decimal("300"), "real ticks", Decimal("100"), Decimal("2"), 1, Decimal("1.1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), (), ())}
    探测 = 单实例MT5重复探测器(
        lambda _: 执行结果(实验状态.已归档, {}, {}), lambda 轮次: tmp_path / 轮次, lambda 路径: 报告[路径.name]
    ).执行()

    assert 探测.报告完整 is True
    assert 探测.逐笔一致 is False
    assert 探测.通过 is False
