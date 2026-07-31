from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wt4.mt5报告 import MT5报告摘要


@dataclass(frozen=True)
class 风险规则:
    最大权益回撤: Decimal = Decimal("0.25")
    单笔风险上限: Decimal = Decimal("0.03")
    绝对单笔风险上限: Decimal = Decimal("0.05")
    开放风险上限: Decimal = Decimal("0.05")
    单日亏损上限: Decimal = Decimal("0.10")


@dataclass(frozen=True)
class 权益点:
    时间: str
    余额: Decimal
    权益: Decimal


@dataclass(frozen=True)
class 权益核验结果:
    最大回撤: Decimal
    硬失败: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class 已实现余额重演结果:
    曲线: tuple[权益点, ...]
    最大回撤金额: Decimal
    最大回撤比例: Decimal
    失败原因: tuple[str, ...]

    @property
    def 通过(self) -> bool:
        return not self.失败原因


def 计算初始风险(*, 入场价: Decimal, 止损价: Decimal, 手数: Decimal, 每价格单位价值: Decimal, 双边佣金: Decimal, 开仓压力滑点价格: Decimal) -> Decimal:
    if 手数 <= 0 or 每价格单位价值 <= 0 or 双边佣金 < 0 or 开仓压力滑点价格 < 0:
        raise ValueError("风险输入必须有效且非负")
    距离 = abs(入场价 - 止损价) + 开仓压力滑点价格
    if 距离 <= 0:
        raise ValueError("必须具有有效服务器止损")
    return 距离 * 手数 * 每价格单位价值 + 双边佣金


def 核验权益曲线(权益曲线: list[权益点], 规则: 风险规则) -> 权益核验结果:
    if not 权益曲线:
        raise ValueError("权益曲线不能为空")
    峰值 = 权益曲线[0].权益
    最大回撤 = Decimal("0")
    for 点 in 权益曲线:
        if 点.权益 <= 0:
            最大回撤 = Decimal("1")
            break
        峰值 = max(峰值, 点.权益)
        最大回撤 = max(最大回撤, (峰值 - 点.权益) / 峰值)
    硬失败 = ["最大权益回撤"] if 最大回撤 >= 规则.最大权益回撤 else []
    return 权益核验结果(最大回撤, 硬失败)


def 重演MT5已实现余额(报告: MT5报告摘要) -> 已实现余额重演结果:
    """按 Deals 的余额字段重演已实现曲线，不把它误作逐 tick 权益重演。"""
    if not 报告.成交:
        raise ValueError("成交明细不能为空")
    曲线 = tuple(权益点(成交.时间, 成交.余额, 成交.余额) for 成交 in 报告.成交)
    峰值 = 曲线[0].余额
    最大回撤金额 = Decimal("0")
    最大回撤比例 = Decimal("0")
    for 点 in 曲线:
        if 点.余额 <= 0:
            raise ValueError("已实现余额不得为非正")
        峰值 = max(峰值, 点.余额)
        回撤金额 = 峰值 - 点.余额
        最大回撤金额 = max(最大回撤金额, 回撤金额)
        最大回撤比例 = max(最大回撤比例, 回撤金额 / 峰值)

    失败: list[str] = []
    if 曲线[0].余额 != 报告.初始资金:
        失败.append("Deals初始余额与报告初始资金不一致")
    if 曲线[-1].余额 != 报告.初始资金 + 报告.净利润:
        失败.append("Deals终余额与报告净利润不一致")
    if 最大回撤金额 != 报告.最大余额回撤金额:
        失败.append("已实现最大余额回撤金额与报告不一致")
    # MT5 将百分比展示为小数点后二位百分比，容忍其显示舍入但不容忍实质差异。
    if abs(最大回撤比例 - 报告.最大余额回撤比例) > Decimal("0.00005"):
        失败.append("已实现最大余额回撤比例与报告不一致")
    return 已实现余额重演结果(曲线, 最大回撤金额, 最大回撤比例, tuple(失败))


def 计算当日亏损(日初权益: Decimal, 当前权益: Decimal, 当日出入金净额: Decimal = Decimal("0")) -> Decimal:
    """计算以日初权益为基准、已剔除当日净入金的权益损失。

    ``当日出入金净额`` 为正表示净入金、为负表示净出金。
    """
    if 日初权益 <= 0:
        raise ValueError("日初权益必须为正")
    return max(Decimal("0"), 日初权益 - (当前权益 - 当日出入金净额))


def 核验风险限额(*, 当前权益: Decimal, 日初权益: Decimal, 单笔初始风险: Decimal, 开放初始风险: Decimal, 当日亏损: Decimal, 规则: 风险规则) -> list[str]:
    if 当前权益 <= 0:
        return ["账户权益非正"]
    失败: list[str] = []
    if 单笔初始风险 > 当前权益 * 规则.单笔风险上限:
        失败.append("单笔风险超过候选上限")
    if 单笔初始风险 > 当前权益 * 规则.绝对单笔风险上限:
        失败.append("单笔风险超过绝对上限")
    if 开放初始风险 > 当前权益 * 规则.开放风险上限:
        失败.append("开放初始风险超过上限")
    if 当日亏损 >= 日初权益 * 规则.单日亏损上限:
        失败.append("当日亏损达到上限")
    return 失败
