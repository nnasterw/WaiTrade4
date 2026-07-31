from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class 评分原料:
    样本外净收益: Decimal
    压力净收益: Decimal
    成本保留率: Decimal
    最大回撤: Decimal
    最大单笔贡献: Decimal
    移除最佳月后压力期望: Decimal
    月度正收益比例: Decimal
    证据完整: bool
    订单异常数: int


@dataclass(frozen=True)
class 评分卡:
    指标: dict[str, Any]
    总分: None
    最高状态: str
    等级限制原因: list[str]


def 生成评分卡(原料: 评分原料) -> 评分卡:
    限制: list[str] = []
    if not 原料.证据完整:
        限制.append("证据不完整")
    if 原料.订单异常数:
        限制.append("存在订单异常")
    if 原料.移除最佳月后压力期望 <= 0:
        限制.append("移除最佳月后压力期望非正")
    if 原料.最大单笔贡献 >= Decimal("0.50"):
        限制.append("收益集中度异常")
    最高状态 = "观察" if 限制 else "候选"
    指标: dict[str, Any] = {
        "样本外净收益": 原料.样本外净收益,
        "压力净收益": 原料.压力净收益,
        "成本保留率": 原料.成本保留率,
        "最大权益回撤": 原料.最大回撤,
        "最大单笔贡献": 原料.最大单笔贡献,
        "移除最佳月后压力期望": 原料.移除最佳月后压力期望,
        "月度正收益比例": 原料.月度正收益比例,
        "订单异常数": 原料.订单异常数,
    }
    return 评分卡(指标, None, 最高状态, 限制)
