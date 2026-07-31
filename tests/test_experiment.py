from __future__ import annotations

from datetime import date

import pytest

from wt4.experiment import 实验输入, 核验正式策略验收单期, 核验正式策略验收批次
from wt4.窗口 import 生成验收窗口


def test_相同规范输入生成稳定且顺序无关的实验身份() -> None:
    左 = 实验输入(
        策略实现提交="abc123",
        二进制哈希="bin",
        参数={"风险": 2.7, "周期": "M5"},
        数据指纹="ticks",
        成本快照="cost",
        合约规格="contract",
        mt5版本="5.0",
        建模方式=4,
        起始日="2024.01.01",
        结束日="2024.12.31",
        分区="开发",
    )
    右 = 实验输入(
        策略实现提交="abc123",
        二进制哈希="bin",
        参数={"周期": "M5", "风险": 2.7},
        数据指纹="ticks",
        成本快照="cost",
        合约规格="contract",
        mt5版本="5.0",
        建模方式=4,
        起始日="2024.01.01",
        结束日="2024.12.31",
        分区="开发",
    )

    assert 左.身份 == 右.身份
    assert len(左.身份) == 64


def _正式输入(开始日: str, 结束日: str, 分区: str, **覆盖: object) -> 实验输入:
    默认 = dict(
        策略实现提交="abc123", 二进制哈希="bin", 参数={"风险": 3}, 数据指纹="ticks",
        成本快照="cost", 合约规格="BTCUSDm", mt5版本="5.0", 建模方式=4,
        起始日=开始日, 结束日=结束日, 分区=分区, 正式策略验收=True,
        交易品种="BTCUSDm", 初始资金="300",
    )
    默认.update(覆盖)
    return 实验输入(**默认)


def test_正式策略验收批次必须绑定BTC_300美元与四个连续半年周期() -> None:
    窗口 = 生成验收窗口(date(2026, 7, 31))
    批次 = tuple(
        _正式输入(开始.isoformat(), 结束.isoformat(), f"周期{索引}")
        for 索引, (开始, 结束) in enumerate(窗口.周期, start=1)
    )

    核验正式策略验收批次(批次, 窗口)


def test_正式策略验收批次拒绝非BTC_非300或缺失周期() -> None:
    窗口 = 生成验收窗口(date(2026, 7, 31))
    批次 = [
        _正式输入(开始.isoformat(), 结束.isoformat(), f"周期{索引}")
        for 索引, (开始, 结束) in enumerate(窗口.周期, start=1)
    ]
    批次[2] = _正式输入("2025-07-01", "2025-12-31", "周期3", 交易品种="ETHUSDm")

    with pytest.raises(ValueError, match="BTC"):
        核验正式策略验收批次(tuple(批次), 窗口)

    with pytest.raises(ValueError, match="四个连续半年周期"):
        核验正式策略验收批次(tuple(批次[:3]), 窗口)


@pytest.mark.parametrize(
    ("覆盖", "错误"),
    [
        ({"交易品种": "ETHUSDm"}, "BTC"),
        ({"合约规格": "ETHUSDm"}, "BTC"),
        ({"初始资金": "1000"}, "300"),
        ({"建模方式": 1}, "Model 4"),
        ({"起始日": "2024.7.1"}, "ISO"),
        ({"起始日": "2024-12-31", "结束日": "2024-07-01"}, "区间"),
    ],
)
def test_正式策略验收单期拒绝降低固定边界(覆盖: dict[str, object], 错误: str) -> None:
    默认 = {"开始日": "2024-07-01", "结束日": "2024-12-31"}
    默认.update(覆盖)
    with pytest.raises(ValueError, match=错误):
        核验正式策略验收单期(_正式输入(**默认, 分区="单期"))
