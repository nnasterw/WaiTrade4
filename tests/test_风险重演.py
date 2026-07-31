from __future__ import annotations

from decimal import Decimal

from wt4.风险 import 权益点, 风险规则, 核验权益曲线, 计算初始风险


def test_初始风险包含滑点与双边佣金() -> None:
    风险 = 计算初始风险(
        入场价=Decimal("100"), 止损价=Decimal("90"), 手数=Decimal("2"),
        每价格单位价值=Decimal("1"), 双边佣金=Decimal("3"), 开仓压力滑点价格=Decimal("1"),
    )
    assert 风险 == Decimal("25")


def test_权益回撤触线即为硬失败() -> None:
    结果 = 核验权益曲线(
        [权益点("2025.01.01T00:00:00", Decimal("300"), Decimal("300")),
         权益点("2025.01.01T01:00:00", Decimal("300"), Decimal("225"))],
        风险规则(),
    )
    assert "最大权益回撤" in 结果.硬失败

from wt4.风险 import 计算当日亏损, 核验风险限额


def test_日损以服务器日初权益计入浮亏并剔除入金() -> None:
    损失 = 计算当日亏损(Decimal("300"), Decimal("285"), Decimal("20"))
    assert 损失 == Decimal("35")


def test_单笔和开放风险不能越过各自上限() -> None:
    失败 = 核验风险限额(
        当前权益=Decimal("300"), 日初权益=Decimal("300"), 单笔初始风险=Decimal("10"), 开放初始风险=Decimal("16"),
        当日亏损=Decimal("31"), 规则=风险规则(),
    )
    assert set(失败) == {"单笔风险超过候选上限", "开放初始风险超过上限", "当日亏损达到上限"}
