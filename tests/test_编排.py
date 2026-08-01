from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest

from wt4.experiment import 实验输入
from wt4.验收 import 验收输入
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.正式验收工件 import 完成正式验收风险桥接
from wt4.风险 import 风险限额快照, 重演风险限额, 权益点, 重演逐tick日内权益风险
from wt4.mt5后台 import MT5后台进程
from wt4.编排 import (
    中央单实例后台队列,
    中央实验编排器,
    后台任务状态,
    实验状态,
    执行结果,
    运行正式策略验收批次,
)
from wt4.账本 import 追加式账本


def _输入(参数: dict | None = None) -> 实验输入:
    return 实验输入(
        策略实现提交="abc", 二进制哈希="def", 参数=参数 or {}, 数据指纹="ticks",
        成本快照="cost", 合约规格="contract", mt5版本="5", 建模方式=4,
        起始日="2024.01.01", 结束日="2024.06.30", 分区="开发",
    )


def _正式输入(开始日: str, 结束日: str, 参数: dict | None = None) -> 实验输入:
    return 实验输入(
        策略实现提交="正式策略", 二进制哈希="正式二进制", 参数=参数 or {}, 数据指纹="ticks",
        成本快照="cost", 合约规格="BTCUSDm", mt5版本="5", 建模方式=4,
        起始日=开始日, 结束日=结束日, 分区="正式验收", 正式策略验收=True,
        交易品种="BTCUSDm", 初始资金="300",
    )


def _验收输入() -> 验收输入:
    return 验收输入(
        建模方式=4, 封存净收益=Decimal("10"), 压力封存净收益=Decimal("2"),
        极端压力风险通过=True, 输入工件完整=True, 治理通过=True,
        已实现余额重演通过=True, 权益风险证据完整=True,
        报告最大权益回撤比例=Decimal("0.1"), 日初余额={"2026-01-01": Decimal("300")},
        已实现日损失={"2026-01-01": Decimal("1")},
        逐tick日内权益风险=重演逐tick日内权益风险([
            权益点("2026.01.01 00:00:00", Decimal("300"), Decimal("300")),
        ]),
        风险限额重演=重演风险限额([
            风险限额快照("2026-01-01 00:00:00", Decimal("300"), Decimal("1"), Decimal("1")),
        ]),
    )


class _成功执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        报告 = 暂存目录 / "报告.txt"
        报告.write_text("mt5 evidence", encoding="utf-8")
        return 执行结果(
            实验状态.已归档,
            {报告.name: sha256(报告.read_bytes()).hexdigest()},
            {"净收益": 12, "硬门槛通过": True},
        )


class _失败执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        return 执行结果(实验状态.数据无效, {}, {"原因": "缺失真实 ticks"})


class _篡改输入执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        输入.参数["风险"] = 99
        输入.参数["嵌套"]["值"].append(99)
        return 执行结果(实验状态.数据无效, {}, {"原因": "用于验证输入快照"})


class _正式成功执行器:
    def __init__(self, *, 失败: bool = False, 缺少风险证据: bool = False) -> None:
        self.失败 = 失败
        self.缺少风险证据 = 缺少风险证据
        self.执行次数 = 0

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        self.执行次数 += 1
        开始日 = 输入.起始日.replace("-", ".")
        结束日 = 输入.结束日.replace("-", ".")
        第二个月 = (date.fromisoformat(输入.起始日) + timedelta(days=31)).strftime("%Y.%m.%d")
        报告 = 暂存目录 / "报告.html"
        报告.write_bytes(b"\xff\xfe" + f'''<html><body><table>
<tr><td>Expert:</td><td>WaiTrade_OB</td></tr><tr><td>Symbol:</td><td>BTCUSDm</td></tr>
<tr><td>Period:</td><td>M1 ({开始日} - {结束日})</td></tr><tr><td>Initial Deposit:</td><td>300.00</td></tr>
<tr><td>History Quality:</td><td>100% real ticks</td></tr><tr><td>Total Net Profit:</td><td>12.50</td></tr>
<tr><td>Balance Drawdown Maximal:</td><td>0.00 (0.00%)</td></tr><tr><td>Equity Drawdown Maximal:</td><td>11.00 (3.50%)</td></tr>
<tr><td>Profit Factor:</td><td>1.25</td></tr><tr><td>Total Trades:</td><td>1</td></tr><tr><td>Total Deals:</td><td>2</td></tr></table>
<table><tr><td>Orders</td></tr><tr><td>Open Time</td><td>Order</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S / L</td><td>T / P</td><td>Time</td><td>State</td><td>Comment</td></tr>
<tr><td>{开始日} 00:00:00</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>0.00</td><td>99063.02</td><td></td><td>{开始日} 00:00:00</td><td>filled</td><td>x</td></tr>
<tr><td>Deals</td></tr><tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td><td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td></tr>
<tr><td>{开始日} 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td><td></td><td></td><td>0.00</td><td>0.00</td><td>300.00</td><td>300.00</td><td></td></tr>
<tr><td>{开始日} 00:00:01</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>2</td><td>0.00</td><td>0.00</td><td>0.00</td><td>300.00</td><td>x</td></tr>
<tr><td>{开始日} 00:00:02</td><td>3</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98875.00</td><td>3</td><td>0.00</td><td>0.00</td><td>12.50</td><td>312.50</td><td>x</td></tr></table></body></html>'''.encode("utf-16le"))
        权益 = 暂存目录 / "逐tick权益.json"
        成交风险 = 暂存目录 / "成交风险.json"
        风险 = 暂存目录 / "风险限额.json"
        权益.write_text(
            f'{{"权益点":[{{"时间":"{开始日} 00:00:00","余额":"300","权益":"300"}},'
            f'{{"时间":"{开始日} 00:00:01","余额":"300","权益":"300"}},'
            f'{{"时间":"{开始日} 00:00:02","余额":"312.5","权益":"312.5"}}]}}',
            encoding="utf-8",
        )
        成交风险.write_text(
            f'{{"开仓风险":[{{"成交号":2,"时间":"{开始日} 00:00:01","当前权益":"300",'
            '"单笔初始风险":"1","开放初始风险":"1"}]}',
            encoding="utf-8",
        )
        报告摘要 = 解析MT5报告(报告, 报告期望("WaiTrade_OB", "BTCUSDm", "M1", 开始日, 结束日, Decimal("300")))
        验收 = 完成正式验收风险桥接(
            报告=报告摘要, 报告路径=报告, 逐tick权益路径=权益, 成交风险路径=成交风险, 风险限额路径=风险,
            压力封存净收益=Decimal("2"), 极端压力风险通过=True, 输入工件完整=True, 治理通过=True,
        )
        if self.失败:
            验收 = 验收.__class__(
                **{**验收.__dict__, "压力封存净收益": Decimal("-1")}
            )
        压力报告 = 暂存目录 / "压力报告.html"
        压力报告.write_bytes(b"\xff\xfe" + f'''<html><body><table>
<tr><td>Expert:</td><td>WaiTrade_OB</td></tr><tr><td>Symbol:</td><td>BTCUSDm</td></tr>
<tr><td>Period:</td><td>M1 ({开始日} - {结束日})</td></tr><tr><td>Initial Deposit:</td><td>300.00</td></tr>
<tr><td>History Quality:</td><td>100% real ticks</td></tr><tr><td>Total Net Profit:</td><td>2.00</td></tr>
<tr><td>Balance Drawdown Maximal:</td><td>0.00 (0.00%)</td></tr><tr><td>Equity Drawdown Maximal:</td><td>11.00 (3.50%)</td></tr>
<tr><td>Profit Factor:</td><td>1.25</td></tr><tr><td>Total Trades:</td><td>2</td></tr><tr><td>Total Deals:</td><td>4</td></tr></table>
<table><tr><td>Orders</td></tr><tr><td>Open Time</td><td>Order</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S / L</td><td>T / P</td><td>Time</td><td>State</td><td>Comment</td></tr>
<tr><td>{开始日} 00:00:00</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>99000.00</td><td>99063.02</td><td></td><td>{开始日} 00:00:00</td><td>filled</td><td>x</td></tr>
<tr><td>{第二个月} 00:00:00</td><td>4</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>99000.00</td><td>99063.02</td><td></td><td>{第二个月} 00:00:00</td><td>filled</td><td>x</td></tr>
<tr><td>Deals</td></tr><tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td><td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td></tr>
<tr><td>{开始日} 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td><td></td><td></td><td>0.00</td><td>0.00</td><td>300.00</td><td>300.00</td><td></td></tr>
<tr><td>{开始日} 00:00:01</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>2</td><td>0.00</td><td>0.00</td><td>0.00</td><td>300.00</td><td>x</td></tr>
<tr><td>{开始日} 00:00:02</td><td>3</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98990.00</td><td>3</td><td>0.00</td><td>0.00</td><td>1.00</td><td>301.00</td><td>x</td></tr>
<tr><td>{第二个月} 00:00:01</td><td>4</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>4</td><td>0.00</td><td>0.00</td><td>0.00</td><td>301.00</td><td>x</td></tr>
<tr><td>{第二个月} 00:00:02</td><td>5</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98990.00</td><td>5</td><td>0.00</td><td>0.00</td><td>1.00</td><td>302.00</td><td>x</td></tr></table></body></html>'''.encode("utf-16le"))
        无摩擦报告 = 暂存目录 / "无摩擦报告.html"
        无摩擦报告.write_bytes(报告.read_bytes().replace(b"12.50", b"25.00").replace(b"312.50", b"325.00"))
        工件 = {路径.name: sha256(路径.read_bytes()).hexdigest() for 路径 in (报告, 压力报告, 无摩擦报告, 权益, 成交风险, 风险)}
        return 执行结果(
            实验状态.已归档, 工件, {}, 验收输入=验收,
            评分证据工件=(压力报告.name, 无摩擦报告.name),
            风险证据工件=None if self.缺少风险证据 else (权益.name, 成交风险.name, 风险.name),
            报告工件=(报告.name, "WaiTrade_OB", "M1"),
        )


class _占位风险工件执行器(_正式成功执行器):
    """模拟旧实现：任意非空 JSON 被伪装成正式风险证据。"""

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        结果 = super().执行(输入, 暂存目录)
        占位 = {
            "逐tick权益.json": {"来源": "占位"},
            "成交风险.json": {"来源": "占位"},
            "风险限额.json": {"来源": "占位"},
        }
        工件 = dict(结果.工件)
        for 名称, 内容 in 占位.items():
            路径 = 暂存目录 / 名称
            路径.write_text(json.dumps(内容, ensure_ascii=False), encoding="utf-8")
            工件[名称] = sha256(路径.read_bytes()).hexdigest()
        return replace(结果, 工件=工件)


class _复用样本外报告评分执行器(_正式成功执行器):
    """评分情景不能复用样本外报告来伪造独立压力证据。"""

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        结果 = super().执行(输入, 暂存目录)
        return replace(结果, 评分证据工件=("报告.html", "无摩擦报告.html"))


class _漏报开仓风险执行器(_正式成功执行器):
    """模拟风险快照与报告中的真实开仓集合脱钩。"""

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        结果 = super().执行(输入, 暂存目录)
        风险 = 暂存目录 / "成交风险.json"
        风险.write_text('{"开仓风险":[]}', encoding="utf-8")
        # 重建限额工件哈希，确保测试命中的是报告 Deals 完整性而非旧哈希。
        限额 = 暂存目录 / "风险限额.json"
        内容 = json.loads(限额.read_text(encoding="utf-8"))
        内容["源工件哈希"]["开仓风险"] = sha256(风险.read_bytes()).hexdigest()
        内容["最大单笔初始风险比例"] = None
        内容["最大开放初始风险比例"] = None
        内容["失败原因"] = ["没有开仓风险证据"]
        限额.write_text(json.dumps(内容, ensure_ascii=False), encoding="utf-8")
        工件 = dict(结果.工件)
        工件[风险.name] = sha256(风险.read_bytes()).hexdigest()
        工件[限额.name] = sha256(限额.read_bytes()).hexdigest()
        # 伪造调用者内存验收对象，编排器必须从报告自行否决。
        return replace(结果, 工件=工件, 验收输入=_验收输入())


def test_成功实验原子归档并写入完整事件链(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")

    结果 = 编排器.运行(_输入(), _成功执行器())

    assert 结果.状态 is 实验状态.已归档
    assert (结果.工件目录 / "报告.txt").is_file()
    assert (结果.工件目录 / "验收结果.json").is_file()
    清单 = json.loads((结果.工件目录 / "工件清单.json").read_text(encoding="utf-8"))
    assert set(清单["工件哈希"]) == {"报告.txt", "验收结果.json"}
    assert [事件.类型 for 事件 in 账本.事件(结果.实验身份)] == ["已创建", "已归档"]


def test_无效实验保留失败分类且拒绝相同身份重跑(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入()

    结果 = 编排器.运行(输入, _失败执行器())

    assert 结果.状态 is 实验状态.数据无效
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "数据无效"]
    with pytest.raises(ValueError, match="拒绝重跑"):
        编排器.运行(输入, _失败执行器())


def test_执行器篡改可变参数不会改写实验身份或已创建账本输入(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"风险": 3, "嵌套": {"值": [1]}})

    结果 = 编排器.运行(输入, _篡改输入执行器())

    assert 结果.实验身份 == 输入.身份
    assert 账本.事件(输入.身份)[0].内容["输入"]["参数"] == {"风险": 3, "嵌套": {"值": [1]}}
    assert 输入.参数 == {"风险": 3, "嵌套": {"值": [1]}}


def test_启动恢复会将仅已创建且无终态的实验标为执行无效(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "异常退出后恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})

    assert 编排器.回收未终态实验(输入.身份, "后台宿主异常退出") is True
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]
    assert 账本.事件(输入.身份)[-1].内容 == {"原因": "后台宿主异常退出"}


def test_启动恢复不改写已有终态或仅排队实验(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    已排队 = _输入({"任务": "排队"})
    已归档 = _输入({"任务": "完成"})
    账本.追加(已排队.身份, 实验状态.已排队, {"输入": {}})
    账本.追加(已归档.身份, 实验状态.已创建, {"输入": {}})
    账本.追加(已归档.身份, 实验状态.已归档, {"工件目录": "/tmp/工件"})

    assert 编排器.回收未终态实验(已排队.身份) is False
    assert 编排器.回收未终态实验(已归档.身份) is False
    assert [事件.类型 for 事件 in 账本.事件(已排队.身份)] == ["已排队"]
    assert [事件.类型 for 事件 in 账本.事件(已归档.身份)] == ["已创建", "已归档"]


def test_受限恢复仅在归属进程组已回收后追加无效终态(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "受限恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})
    (暂存目录 / "后台-归属.json").write_text("{}", encoding="utf-8")

    assert 编排器.受限恢复遗留后台实验(输入.身份) is False
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建"]


def test_受限恢复在进程组证据通过后才追加无效终态(tmp_path, monkeypatch) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "已验证受限恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})
    归属记录 = 暂存目录 / "后台-归属.json"
    归属记录.write_text("{}", encoding="utf-8")
    已调用: list[Path] = []

    def _已回收(路径: Path) -> bool:
        已调用.append(路径)
        return True

    monkeypatch.setattr(MT5后台进程, "回收遗留自有进程组", _已回收)

    assert 编排器.受限恢复遗留后台实验(输入.身份) is True
    assert 已调用 == [归属记录]
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]
    assert 账本.事件(输入.身份)[-1].内容 == {"原因": "后台宿主提前退出，已受限回收本轮进程组"}


def test_受限恢复确认进程组已不存在后才追加无效终态(tmp_path, monkeypatch) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "已退出恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})

    monkeypatch.setattr(MT5后台进程, "回收遗留自有进程组", lambda _: False)
    monkeypatch.setattr(MT5后台进程, "确认遗留自有进程组已退出", lambda _: True)

    assert 编排器.受限恢复遗留后台实验(输入.身份) is True
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]
    assert 账本.事件(输入.身份)[-1].内容 == {"原因": "后台宿主提前退出，已确认本轮进程组退出"}


class _留痕执行器:
    def __init__(self, 名称: str, 顺序: list[str], 放行: Event | None = None, 失败: bool = False) -> None:
        self.名称 = 名称
        self.顺序 = 顺序
        self.放行 = 放行
        self.失败 = 失败

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        self.顺序.append(self.名称)
        if self.放行 is not None:
            assert self.放行.wait(5)
        if self.失败:
            raise RuntimeError(f"{self.名称} 故意失败")
        报告 = 暂存目录 / "报告.txt"
        报告.write_text(self.名称, encoding="utf-8")
        return 执行结果(实验状态.已归档, {报告.name: sha256(报告.read_bytes()).hexdigest()}, {})


def test_后台队列严格串行_故障不阻塞后续任务_可定向取消(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    队列 = 中央单实例后台队列(编排器)
    顺序: list[str] = []
    放行 = Event()
    甲 = 队列.提交(_输入({"任务": "甲"}), _留痕执行器("甲", 顺序, 放行))
    乙 = 队列.提交(_输入({"任务": "乙"}), _留痕执行器("乙", 顺序, 失败=True))
    丙 = 队列.提交(_输入({"任务": "丙"}), _留痕执行器("丙", 顺序))

    # ``提交`` 的契约是已可靠入队，而不是调用返回前工作线程已经取得
    # CPU。因此等待明确的运行态，避免把线程调度竞态误判为队列失效。
    截止 = monotonic() + 5
    while 队列.快照(甲).状态 is 后台任务状态.已排队 and monotonic() < 截止:
        sleep(0.01)
    assert 队列.快照(甲).状态 is 后台任务状态.运行中
    assert 队列.取消(丙, "验证定向取消")
    assert not 队列.取消(甲)
    放行.set()

    assert 队列.等待(甲, 5).实验状态 is 实验状态.已归档
    乙快照 = 队列.等待(乙, 5)
    assert 乙快照.状态 is 后台任务状态.已完成
    assert "故意失败" in (乙快照.异常 or "")
    assert 队列.等待(丙, 5).状态 is 后台任务状态.已取消
    assert 顺序 == ["甲", "乙"]
    assert [事件.类型 for 事件 in 账本.事件(甲)] == ["已排队", "已创建", "已归档"]
    assert [事件.类型 for 事件 in 账本.事件(乙)] == ["已排队", "已创建", "执行无效"]
    assert [事件.类型 for 事件 in 账本.事件(丙)] == ["已排队", "已取消"]


def test_后台队列拒绝同一实验身份的重复提交(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    队列 = 中央单实例后台队列(中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件"))
    输入 = _输入({"任务": "唯一"})
    放行 = Event()
    队列.提交(输入, _留痕执行器("唯一", [], 放行))
    with pytest.raises(ValueError, match="拒绝重复提交"):
        队列.提交(输入, _成功执行器())
    放行.set()
    assert 队列.等待(输入.身份, 5).状态 is 后台任务状态.已完成


def test_后台排队后篡改调用者输入不会分裂实验身份或账本(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    队列 = 中央单实例后台队列(编排器)
    放行 = Event()
    占用 = 队列.提交(_输入({"任务": "占用"}), _留痕执行器("占用", [], 放行))
    输入 = _输入({"风险": 3, "嵌套": {"值": [1]}})

    身份 = 队列.提交(输入, _成功执行器())
    输入.参数["风险"] = 99
    输入.参数["嵌套"]["值"].append(99)
    放行.set()

    assert 队列.等待(占用, 5).实验状态 is 实验状态.已归档
    快照 = 队列.等待(身份, 5)
    assert 快照.实验状态 is 实验状态.已归档
    assert [事件.类型 for 事件 in 账本.事件(身份)] == ["已排队", "已创建", "已归档"]
    assert 账本.事件(身份)[0].内容["输入"]["参数"] == {"风险": 3, "嵌套": {"值": [1]}}
    assert not 账本.事件(输入.身份)


def test_正式验收必须提供可独立评估的硬门与评分证据(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _成功执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "治理无效"]


def test_直接单期正式验收也拒绝绕开BTC与资金边界(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31", {"单期": True})
    输入 = 输入.__class__(**{**输入.__dict__, "交易品种": "ETHUSDm", "合约规格": "ETHUSDm"})

    with pytest.raises(ValueError, match="BTC"):
        编排器.运行(输入, _正式成功执行器())
    assert 账本.事件(输入.身份) == []


def test_正式验收拒绝仅由调用者布尔声明的权益风险证据(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _正式成功执行器(缺少风险证据=True))

    assert 结果.状态 is 实验状态.治理无效
    assert "封存逐tick权益" in 账本.事件(输入.身份)[-1].内容["原因"]


def test_正式验收拒绝任意JSON占位风险工件(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _占位风险工件执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert "封存逐tick权益" in 账本.事件(输入.身份)[-1].内容["原因"]


def test_正式验收拒绝复用样本外报告伪造评分证据(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _复用样本外报告评分执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert "评分证据无效" in 账本.事件(输入.身份)[-1].内容["原因"]


def test_正式验收拒绝风险工件遗漏原始报告开仓(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")

    结果 = 编排器.运行(_正式输入("2024-07-01", "2024-12-31"), _漏报开仓风险执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert "封存逐tick权益" in 账本.事件(结果.实验身份)[-1].内容["原因"]


def test_正式四周期先冻结范围_逐期硬门通过才归档评分基线(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    窗口输入 = (
        _正式输入("2024-07-01", "2024-12-31"),
        _正式输入("2025-01-01", "2025-06-30"),
        _正式输入("2025-07-01", "2025-12-31"),
        _正式输入("2026-01-01", "2026-06-30"),
    )
    执行器 = _正式成功执行器()

    结果 = 运行正式策略验收批次(date(2026, 7, 31), 窗口输入, 编排器, (执行器,) * 4)

    assert 结果.通过
    assert 执行器.执行次数 == 4
    for 单期 in 结果.周期结果:
        assert 单期.状态 is 实验状态.已归档
        验收 = json.loads((单期.工件目录 / "验收结果.json").read_text(encoding="utf-8"))
        assert 验收["验收硬门通过"] is True
        assert 验收["评分基线"]["版本"] == 1


def test_正式批次任一期硬门失败立即停止后续周期(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = tuple(
        _正式输入(开始日, 结束日) for 开始日, 结束日 in (
            ("2024-07-01", "2024-12-31"), ("2025-01-01", "2025-06-30"),
            ("2025-07-01", "2025-12-31"), ("2026-01-01", "2026-06-30"),
        )
    )
    失败执行器 = _正式成功执行器(失败=True)
    未执行 = _正式成功执行器()

    结果 = 运行正式策略验收批次(date(2026, 7, 31), 输入, 编排器, (失败执行器, 未执行, 未执行, 未执行))

    assert not 结果.通过
    assert len(结果.周期结果) == 1
    assert 结果.周期结果[0].状态 is 实验状态.有效失败
    assert 未执行.执行次数 == 0
