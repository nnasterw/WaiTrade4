from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from wt4.experiment import 实验输入
from wt4.评分 import (
    从已归档实验构造基线样本,
    基线样本,
    校准评分标尺,
    评分原料,
    生成评分卡,
)
from wt4.账本 import 追加式账本
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


def test_基线并列导致三档退化时不得伪造总分() -> None:
    原料 = _原料(1)
    标尺 = 校准评分标尺([
        基线样本(f"tied-{编号}", 原料, 硬门槛结果([]))
        for 编号 in range(5)
    ])

    assert set(标尺.退化指标) == {指标[0] for 指标 in __import__("wt4.评分", fromlist=["_评分指标"])._评分指标}
    卡 = 生成评分卡(原料, 标尺, 硬门结果=硬门槛结果([]))
    assert 卡.总分 is None
    assert 卡.最高状态 == "观察"
    assert "评分标尺三档退化" in 卡.等级限制原因[0]
    assert 卡.指标["评分标尺退化指标"] == list(标尺.退化指标)


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


def _正式基线输入(编号: int, *, 正式策略验收: bool = True) -> 实验输入:
    return 实验输入(
        策略实现提交=f"baseline-{编号}", 二进制哈希="a" * 64, 参数={},
        数据指纹="data", 成本快照="cost", 合约规格="BTCUSDm",
        mt5版本="MT5", 建模方式=4, 起始日="2024-01-01",
        结束日="2024-06-30", 分区="正式验收", 正式策略验收=正式策略验收,
        交易品种="BTCUSDm", 初始资金="300",
    )


def _封存评分基线(
    tmp_path: Path, 编号: int = 1, *, 正式策略验收: bool = True,
) -> tuple[追加式账本, Path, 实验输入]:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    输入 = _正式基线输入(编号, 正式策略验收=正式策略验收)
    工件根目录 = tmp_path / "工件"
    工件目录 = 工件根目录 / 输入.身份
    工件目录.mkdir(parents=True)
    验收结果 = {
        "评分基线": {
            "版本": 1,
            "验收硬门通过": True,
            "原料": {
                "样本外净收益": "10", "压力净收益": "2", "成本保留率": "0.5",
                "最大回撤": "0.1", "最大单笔贡献": "0.2",
                "移除最佳月后压力期望": "1", "月度正收益比例": "0.6",
                "证据完整": True, "订单异常数": 0,
            },
        }
    }
    (工件目录 / "验收结果.json").write_text(json.dumps(验收结果, ensure_ascii=False), encoding="utf-8")
    哈希 = {"验收结果.json": sha256((工件目录 / "验收结果.json").read_bytes()).hexdigest()}
    (工件目录 / "工件清单.json").write_text(
        json.dumps({"版本": 1, "工件哈希": 哈希}, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    账本哈希 = {**哈希, "工件清单.json": sha256((工件目录 / "工件清单.json").read_bytes()).hexdigest()}
    账本.追加(输入.身份, "已创建", {"输入": json.loads(输入.规范内容())})
    账本.追加(输入.身份, "已归档", {"工件目录": str(工件目录.resolve()), "工件哈希": 账本哈希})
    return 账本, 工件根目录, 输入


def test_评分基线只能从正式验收的账本归档及哈希构造(tmp_path: Path) -> None:
    账本, 工件根目录, 输入 = _封存评分基线(tmp_path)

    样本 = 从已归档实验构造基线样本(账本, 工件根目录, 输入.身份)

    assert 样本.实验身份 == 输入.身份
    assert 样本.硬门结果.通过
    assert 样本.原料.样本外净收益 == Decimal("10")


def test_评分基线拒绝归档工件被篡改或非正式验收(tmp_path: Path) -> None:
    账本, 工件根目录, 输入 = _封存评分基线(tmp_path)
    (工件根目录 / 输入.身份 / "验收结果.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="哈希"):
        从已归档实验构造基线样本(账本, 工件根目录, 输入.身份)

    账本, 工件根目录, 输入 = _封存评分基线(tmp_path / "非正式", 2, 正式策略验收=False)

    with pytest.raises(ValueError, match="正式策略验收"):
        从已归档实验构造基线样本(账本, 工件根目录, 输入.身份)
