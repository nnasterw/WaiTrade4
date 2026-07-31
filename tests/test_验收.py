from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from wt4.验收 import 验收输入, 评估硬门槛
from wt4.验收 import 从MT5报告构造验收输入
from wt4.风险 import 重演MT5已实现余额, 重演MT5成交风险, 重演逐tick日内权益风险
from tests.test_风险重演 import _报告


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
    assert "Deals已实现余额独立重演未通过" in 结果.失败原因
    assert "逐tick权益与开放风险证据不完整" in 结果.失败原因

from wt4.验收 import 核验风险证据
from wt4.风险 import 权益点


def test_ea与独立重演权益偏差过大时不可验收() -> None:
    结果 = 核验风险证据(
        [权益点("t", Decimal("300"), Decimal("300"))],
        [权益点("t", Decimal("300"), Decimal("299"))],
        Decimal("0.1"),
    )
    assert 结果 == ["EA权益快照与独立重演不一致"]


def test_报告权益回撤触及红线即使其他布尔参数为真也不能验收() -> None:
    报告 = _报告()
    报告 = replace(报告, 最大权益回撤比例=Decimal("0.25"))
    输入 = 从MT5报告构造验收输入(
        报告, 声明建模方式=4, 压力封存净收益=Decimal("1"), 极端压力风险通过=True,
        输入工件完整=True, 治理通过=True, 已实现余额重演=重演MT5已实现余额(报告),
        成交风险重演=重演MT5成交风险(报告), 逐tick权益证据完整=True,
    )

    assert "报告最大权益回撤达到红线" in 评估硬门槛(输入).失败原因


def test_报告已实现日损失达到十百分比红线不能验收() -> None:
    报告 = _报告()
    成交 = (
        报告.成交[0],
        报告.成交[1].__class__(
            "2025.01.01 01:00:00", 2, "BTCUSDm", "buy", "out", Decimal("0.01"), Decimal("1"), 2,
            Decimal("0"), Decimal("0"), Decimal("-30"), Decimal("270"), "",
        ),
        报告.成交[2].__class__(
            "2025.01.01 02:00:00", 3, "BTCUSDm", "sell", "out", Decimal("0.01"), Decimal("1"), 3,
            Decimal("0"), Decimal("0"), Decimal("35"), Decimal("305"), "",
        ),
    )
    报告 = replace(报告, 最大余额回撤金额=Decimal("30"), 最大余额回撤比例=Decimal("0.1"), 成交=成交)
    输入 = 从MT5报告构造验收输入(
        报告, 声明建模方式=4, 压力封存净收益=Decimal("1"), 极端压力风险通过=True,
        输入工件完整=True, 治理通过=True, 已实现余额重演=重演MT5已实现余额(报告),
        成交风险重演=重演MT5成交风险(报告), 逐tick权益证据完整=True,
    )

    assert "Deals已实现日损失达到上限" in 评估硬门槛(输入).失败原因


def test_逐tick日内权益浮亏触及十百分比红线不能验收() -> None:
    报告 = _报告()
    输入 = 从MT5报告构造验收输入(
        报告, 声明建模方式=4, 压力封存净收益=Decimal("1"), 极端压力风险通过=True,
        输入工件完整=True, 治理通过=True, 已实现余额重演=重演MT5已实现余额(报告),
        成交风险重演=重演MT5成交风险(报告), 逐tick权益证据完整=True,
        逐tick日内权益风险=重演逐tick日内权益风险([
            权益点("2025.01.01 00:00:00", Decimal("300"), Decimal("300")),
            权益点("2025.01.01 12:00:00", Decimal("300"), Decimal("270")),
            权益点("2025.01.01 23:00:00", Decimal("305"), Decimal("305")),
        ]),
    )

    assert "逐tick日内权益亏损达到上限" in 评估硬门槛(输入).失败原因
