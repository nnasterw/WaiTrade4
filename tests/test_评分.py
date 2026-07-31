from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from wt4.评分 import 基线样本, 校准评分标尺, 评分原料, 生成评分卡
from wt4.验收 import 硬门槛结果


def _原料(编号: int) -> 评分原料:
    return 评分原料(
        样本外净收益=Decimal(编号 * 10), 压力净收益=Decimal(编号),
        成本保留率=Decimal(编号) / Decimal(10), 最大回撤=Decimal(10 - 编号) / Decimal(100),
        最大单笔贡献=Decimal(10 - 编号) / Decimal(100),
        移除最佳月后压力期望=Decimal(编号), 月度正收益比例=Decimal(编号) / Decimal(10),
        证据完整=True, 订单异常数=0,
    )


def _基线样本(编号: int) -> 基线样本:
    return 基线样本(f"baseline-{编号}", _原料(编号), 硬门槛结果([]))


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
    assert 卡.最高状态 == "观察"
    assert "验收硬门未通过" in 卡.等级限制原因
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
    assert 卡.最高状态 == "观察"


def test_评分仅在完整代表性基线池校准后产生三档分数() -> None:
    标尺 = 校准评分标尺([_基线样本(编号) for 编号 in range(1, 6)])

    卡 = 生成评分卡(_原料(5), 标尺, 硬门结果=硬门槛结果([]))

    assert 卡.总分 == 14
    assert 卡.最高状态 == "优先人工复核"
    assert 卡.指标["评分标尺身份"] == 标尺.标尺身份
    assert set(卡.指标["三档分项"].values()) == {2}


def test_相同基线池重排不改变标尺身份和分界() -> None:
    正序 = [_基线样本(编号) for 编号 in range(1, 6)]
    正序标尺 = 校准评分标尺(正序)
    倒序标尺 = 校准评分标尺(list(reversed(正序)))

    assert 倒序标尺.标尺身份 == 正序标尺.标尺身份
    assert 倒序标尺.基线身份 == 正序标尺.基线身份
    assert 倒序标尺.三档分界 == 正序标尺.三档分界


def test_不完整或过小的基线池不能校准伪精确分数() -> None:
    try:
        校准评分标尺([_基线样本(编号) for 编号 in range(1, 5)])
    except ValueError as 异常:
        assert "五个" in str(异常)
    else:
        raise AssertionError("过小基线池不得生成评分标尺")

    异常原料 = replace(_原料(5), 订单异常数=1)
    try:
        校准评分标尺([
            *[_基线样本(编号) for 编号 in range(1, 5)],
            基线样本("baseline-5", 异常原料, 硬门槛结果([])),
        ])
    except ValueError as 异常:
        assert "订单异常" in str(异常)
    else:
        raise AssertionError("不完整基线不得生成评分标尺")


def test_未通过验收硬门的基线和候选不得得到排序状态() -> None:
    基线池 = [_基线样本(编号) for 编号 in range(1, 5)]
    基线池.append(基线样本("baseline-5", _原料(5), 硬门槛结果(["示例失败"])))
    try:
        校准评分标尺(基线池)
    except ValueError as 异常:
        assert "硬门通过" in str(异常)
    else:
        raise AssertionError("未过硬门的基线不得校准标尺")

    标尺 = 校准评分标尺([_基线样本(编号) for 编号 in range(1, 6)])
    卡 = 生成评分卡(_原料(5), 标尺)
    assert 卡.最高状态 == "观察"
    assert "验收硬门未通过" in 卡.等级限制原因
