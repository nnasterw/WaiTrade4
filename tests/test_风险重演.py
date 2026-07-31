from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from wt4.风险 import 权益点, 风险规则, 核验权益曲线, 计算初始风险
from wt4.mt5报告 import 成交明细, MT5报告摘要
from wt4.风险 import 重演MT5已实现余额, 重演MT5成交风险


def _报告(*, 余额回撤金额: Decimal = Decimal("10")) -> MT5报告摘要:
    成交 = (
        成交明细("2025.01.01 00:00:00", 1, "", "balance", "", None, None, None, Decimal("0"), Decimal("0"), Decimal("300"), Decimal("300"), ""),
        成交明细("2025.01.01 01:00:00", 2, "BTCUSDm", "buy", "out", Decimal("0.01"), Decimal("1"), 2, Decimal("0"), Decimal("0"), Decimal("-10"), Decimal("290"), ""),
        成交明细("2025.01.01 02:00:00", 3, "BTCUSDm", "sell", "out", Decimal("0.01"), Decimal("1"), 3, Decimal("0"), Decimal("0"), Decimal("15"), Decimal("305"), ""),
    )
    return MT5报告摘要("EA", "BTCUSDm", "M1", "2025.01.01", "2025.01.02", Decimal("300"), "real ticks", Decimal("1"), Decimal("5"), 2, Decimal("1"), 余额回撤金额, Decimal("0.0333"), Decimal("12"), Decimal("0.04"), (), 成交)


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


def test_deals可独立重演已实现余额且不冒充权益曲线() -> None:
    结果 = 重演MT5已实现余额(_报告())

    assert 结果.通过
    assert [点.余额 for 点 in 结果.曲线] == [Decimal("300"), Decimal("290"), Decimal("305")]
    assert 结果.最大回撤金额 == Decimal("10")
    assert 结果.最大回撤比例 == Decimal("0.03333333333333333333333333333")


def test_deals回撤与报告不一致不能通过() -> None:
    结果 = 重演MT5已实现余额(_报告(余额回撤金额=Decimal("9")))

    assert "已实现最大余额回撤金额与报告不一致" in 结果.失败原因


def test_deals能重演净持仓和已实现日损失但拒绝臆造开放风险() -> None:
    结果 = 重演MT5成交风险(_报告())

    assert [快照.净手数 for 快照 in 结果.持仓快照] == [Decimal("0"), Decimal("0.01"), Decimal("0")]
    assert 结果.已实现日损失 == {"2025-01-01": Decimal("10")}
    assert 结果.日初余额 == {"2025-01-01": Decimal("300")}
    assert not 结果.开放风险证据完整
    assert 结果.持仓快照[1].开放初始风险 is None
    assert "服务器止损" in 结果.持仓快照[1].原因


def test_已实现日损失按每日开盘余额而非全期初始资金核验() -> None:
    报告 = _报告()
    成交 = (*报告.成交, 成交明细(
        "2025.01.02 01:00:00", 4, "BTCUSDm", "buy", "out", Decimal("0.01"), Decimal("1"), 4,
        Decimal("0"), Decimal("0"), Decimal("-31"), Decimal("274"), "",
    ))
    结果 = 重演MT5成交风险(replace(报告, 成交=成交))

    assert 结果.日初余额["2025-01-02"] == Decimal("305")
    assert 结果.已实现日损失["2025-01-02"] == Decimal("31")

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
