from __future__ import annotations

from decimal import Decimal

from wt4.评分 import 评分原料, 生成评分卡


def test_评分卡只产出原料与等级限制不伪造分段() -> None:
    卡 = 生成评分卡(
        评分原料(
            样本外净收益=Decimal("15"), 压力净收益=Decimal("4"), 成本保留率=Decimal("0.4"),
            最大回撤=Decimal("0.12"), 最大单笔贡献=Decimal("0.2"),
            移除最佳月后压力期望=Decimal("1"), 月度正收益比例=Decimal("0.6"),
            证据完整=True, 订单异常数=0,
        )
    )
    assert 卡.总分 is None
    assert 卡.最高状态 == "候选"
    assert "成本保留率" in 卡.指标


def test_集中度仅保存为评分原料等待基线池校准() -> None:
    卡 = 生成评分卡(
        评分原料(
            样本外净收益=Decimal("15"), 压力净收益=Decimal("4"), 成本保留率=Decimal("0.4"),
            最大回撤=Decimal("0.12"), 最大单笔贡献=Decimal("0.8"),
            移除最佳月后压力期望=Decimal("-1"), 月度正收益比例=Decimal("0.6"),
            证据完整=True, 订单异常数=0,
        )
    )
    assert 卡.最高状态 == "观察"
    assert "收益集中度异常" not in 卡.等级限制原因


def test_未校准的集中度本身不限制候选状态() -> None:
    卡 = 生成评分卡(
        评分原料(
            样本外净收益=Decimal("15"), 压力净收益=Decimal("4"), 成本保留率=Decimal("0.4"),
            最大回撤=Decimal("0.12"), 最大单笔贡献=Decimal("0.8"),
            移除最佳月后压力期望=Decimal("1"), 月度正收益比例=Decimal("0.6"),
            证据完整=True, 订单异常数=0,
        )
    )
    assert 卡.最高状态 == "候选"
