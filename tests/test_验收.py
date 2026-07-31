from __future__ import annotations

from decimal import Decimal

from wt4.验收 import 验收输入, 评估硬门槛


def test_压力封存亏损无法被总收益补偿() -> None:
    结果 = 评估硬门槛(
        验收输入(
            建模方式=4,
            封存净收益=Decimal("100"),
            压力封存净收益=Decimal("-1"),
            极端压力风险通过=True,
            输入工件完整=True,
            治理通过=True,
        )
    )
    assert not 结果.通过
    assert "压力封存样本外为非正" in 结果.失败原因


def test_非真实tick模型不得验收() -> None:
    结果 = 评估硬门槛(
        验收输入(3, Decimal("1"), Decimal("1"), True, True, True)
    )
    assert "必须使用Model 4 / Real Ticks" in 结果.失败原因

from wt4.验收 import 核验风险证据
from wt4.风险 import 权益点


def test_ea与独立重演权益偏差过大时不可验收() -> None:
    结果 = 核验风险证据(
        [权益点("t", Decimal("300"), Decimal("300"))],
        [权益点("t", Decimal("300"), Decimal("299"))],
        Decimal("0.1"),
    )
    assert 结果 == ["EA权益快照与独立重演不一致"]
