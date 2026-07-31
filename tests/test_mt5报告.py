from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from wt4.mt5报告 import MT5报告错误, 报告期望, 解析MT5报告
from wt4.风险 import 重演MT5已实现余额, 重演MT5成交风险
from wt4.验收 import 从MT5报告构造验收输入


def _期望() -> 报告期望:
    return 报告期望("WaiTrade_OB", "BTCUSDm", "M1", "2025.02.01", "2025.03.01", Decimal("300.00"))


def _报告(*, 初始资金: str = "300.00", 额外结果: str = "") -> str:
    return f'''<html><body>
<table>
<tr><td>Expert:</td><td>WaiTrade_OB</td></tr><tr><td>Symbol:</td><td>BTCUSDm</td></tr>
<tr><td>Period:</td><td>M1 (2025.02.01 - 2025.03.01)</td></tr><tr><td>Initial Deposit:</td><td>{初始资金}</td></tr>
<tr><td>History Quality:</td><td>100% real ticks</td></tr><tr><td>Total Net Profit:</td><td>12.50</td></tr>
<tr><td>Balance Drawdown Maximal:</td><td>0.00 (0.00%)</td></tr><tr><td>Equity Drawdown Maximal:</td><td>11.00 (3.50%)</td></tr>
<tr><td>Profit Factor:</td><td>1.25</td></tr><tr><td>Total Trades:</td><td>1</td></tr><tr><td>Total Deals:</td><td>2</td></tr>{额外结果}
</table>
<table><tr><td>Orders</td></tr><tr><td>Open Time</td><td>Order</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S / L</td><td>T / P</td><td>Time</td><td>State</td><td>Comment</td></tr>
<tr><td>2025.02.02 13:36:28</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>0.00</td><td>99063.02</td><td></td><td>2025.02.02 13:36:28</td><td>filled</td><td>x</td></tr>
<tr><td>Deals</td></tr>
<tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td><td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td></tr>
<tr><td>2025.02.01 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td><td></td><td></td><td>0.00</td><td>0.00</td><td>300.00</td><td>300.00</td><td></td></tr>
<tr><td>2025.02.02 13:36:28</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>2</td><td>0.00</td><td>0.00</td><td>0.00</td><td>300.00</td><td>x</td></tr>
<tr><td>2025.02.02 13:56:28</td><td>3</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98875.00</td><td>3</td><td>0.00</td><td>0.00</td><td>12.50</td><td>312.50</td><td>x</td></tr>
</table></body></html>'''


def _写报告(tmp_path: Path, 内容: str) -> Path:
    路径 = tmp_path / "报告.html"
    路径.write_bytes(b"\xff\xfe" + 内容.encode("utf-16le"))
    return 路径


def test_严格解析报告及orders明细(tmp_path: Path) -> None:
    结果 = 解析MT5报告(_写报告(tmp_path, _报告()), _期望())

    assert 结果.净利润 == Decimal("12.50")
    assert 结果.最大余额回撤比例 == Decimal("0")
    assert 结果.最大权益回撤比例 == Decimal("0.035")
    assert 结果.订单[0].订单号 == 2
    assert 结果.成交[-1].余额 == Decimal("312.50")
    验收输入 = 从MT5报告构造验收输入(
        结果,
        声明建模方式=4,
        压力封存净收益=Decimal("1"),
        极端压力风险通过=True,
        输入工件完整=True,
        治理通过=True,
        已实现余额重演=重演MT5已实现余额(结果),
        成交风险重演=重演MT5成交风险(结果),
        逐tick权益证据完整=True,
    )
    assert 验收输入.封存净收益 == Decimal("12.50")
    assert 验收输入.已实现余额重演通过
    assert not 验收输入.权益风险证据完整


def test_拒绝无bom或非utf16le报告(tmp_path: Path) -> None:
    路径 = tmp_path / "报告.html"
    路径.write_text(_报告(), encoding="utf-8")

    with pytest.raises(MT5报告错误, match="UTF-16LE"):
        解析MT5报告(路径, _期望())


def test_重复冲突字段会拒绝(tmp_path: Path) -> None:
    内容 = _报告(额外结果="<tr><td>Total Trades:</td><td>2</td></tr>")

    with pytest.raises(MT5报告错误, match="重复且冲突"):
        解析MT5报告(_写报告(tmp_path, 内容), _期望())


def test_中文报告只采集受控摘要字段(tmp_path: Path) -> None:
    内容 = _报告().replace("Expert:", "专家:").replace("Symbol:", "交易品种:").replace("Period:", "期间:")
    内容 = 内容.replace("Initial Deposit:", "初始入金:").replace("History Quality:", "质量历史:")
    内容 = 内容.replace("Total Net Profit:", "总净盈利:").replace("Profit Factor:", "盈利因子:")
    内容 = 内容.replace("Total Trades:", "交易总计:").replace("Total Deals:", "总成交:")
    内容 = 内容.replace("Balance Drawdown Maximal:", "最大结余亏损:")
    内容 = 内容.replace("Equity Drawdown Maximal:", "最大净值亏损:").replace("100% real ticks", "100%真实报价")
    # 参数区存在同名业务标签，但它不属于摘要白名单，不能污染 Symbol。
    内容 = 内容.replace("</table>\n<table><tr><td>Orders", "<tr><td>交易品种:</td><td>参数区的值</td></tr></table>\n<table><tr><td>Orders")

    结果 = 解析MT5报告(_写报告(tmp_path, 内容), _期望())

    assert 结果.品种 == "BTCUSDm"
    assert 结果.建模方式 == "real ticks"


def test_报告身份不匹配会拒绝(tmp_path: Path) -> None:
    with pytest.raises(MT5报告错误, match="身份"):
        解析MT5报告(_写报告(tmp_path, _报告(初始资金="301.00")), _期望())


def test_deals余额变化不守恒会拒绝(tmp_path: Path) -> None:
    内容 = _报告().replace("<td>312.50</td><td>x</td></tr>", "<td>312.49</td><td>x</td></tr>")

    with pytest.raises(MT5报告错误, match="余额变化"):
        解析MT5报告(_写报告(tmp_path, 内容), _期望())
