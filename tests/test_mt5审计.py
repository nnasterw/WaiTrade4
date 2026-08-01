from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from wt4.mt5审计 import MT5审计错误, 转换MT5审计CSV
from wt4.正式验收工件 import 读取开仓风险工件, 读取逐tick权益工件


def test_转换MT5审计CSV保留每tick毫秒时间并生成正式工件(tmp_path: Path) -> None:
    权益原始 = tmp_path / "权益.csv"
    风险原始 = tmp_path / "风险.csv"
    权益输出 = tmp_path / "逐tick权益.json"
    风险输出 = tmp_path / "开仓风险.json"
    权益原始.write_text(
        "time,balance,equity\n2025.02.02 13:36:28.001,300.00,300.00\n2025.02.02 13:36:28.002,300.00,299.50\n",
        encoding="utf-8",
    )
    风险原始.write_text(
        "deal_id,time,equity,initial_risk,open_initial_risk\n2,2025.02.02 13:36:28,299.50,8.00,8.00\n",
        encoding="utf-8",
    )

    转换MT5审计CSV(权益原始, 风险原始, 权益输出, 风险输出)

    权益 = 读取逐tick权益工件(权益输出)
    风险 = 读取开仓风险工件(风险输出)
    assert [点.权益 for 点 in 权益] == [Decimal("300.00"), Decimal("299.50")]
    assert 风险[0].成交号 == 2


def test_转换MT5审计CSV拒绝表头和金额不完整(tmp_path: Path) -> None:
    权益原始 = tmp_path / "权益.csv"
    风险原始 = tmp_path / "风险.csv"
    权益原始.write_text("时间,余额\n2025.02.02 13:36:28.001,300.00\n", encoding="utf-8")
    风险原始.write_text("deal_id,time,equity,initial_risk,open_initial_risk\n", encoding="utf-8")

    with pytest.raises(MT5审计错误, match="表头"):
        转换MT5审计CSV(权益原始, 风险原始, tmp_path / "权益.json", tmp_path / "风险.json")


def test_转换MT5审计CSV拒绝非递增tick和覆盖已有工件(tmp_path: Path) -> None:
    权益原始 = tmp_path / "权益.csv"
    风险原始 = tmp_path / "风险.csv"
    权益输出 = tmp_path / "权益.json"
    风险输出 = tmp_path / "风险.json"
    权益原始.write_text(
        "time,balance,equity\n2025.02.02 13:36:28.002,300,300\n2025.02.02 13:36:28.001,300,300\n",
        encoding="utf-8",
    )
    风险原始.write_text("deal_id,time,equity,initial_risk,open_initial_risk\n", encoding="utf-8")

    with pytest.raises(MT5审计错误, match="严格递增"):
        转换MT5审计CSV(权益原始, 风险原始, 权益输出, 风险输出)

    权益输出.write_text("{}", encoding="utf-8")
    with pytest.raises(MT5审计错误, match="已存在"):
        转换MT5审计CSV(权益原始, 风险原始, 权益输出, 风险输出)
