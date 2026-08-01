from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.正式策略执行 import (
    BTC正式单期配置,
    正式BTC单期执行器,
    正式场景结果,
    正式MT5场景运行配置,
    真实MT5正式场景运行器,
)
from wt4.编排 import 实验状态, 中央实验编排器
from wt4.账本 import 追加式账本


def _输入(**修改: object) -> 实验输入:
    字段: dict[str, object] = {
        "策略实现提交": "wt4-btc-candidate", "二进制哈希": sha256(b"actual-ex5").hexdigest(),
        "参数": {"风险": 3.0}, "数据指纹": "data", "成本快照": "cost",
        "合约规格": "BTCUSDm", "mt5版本": "MT5", "建模方式": 4,
        "起始日": "2025-01-01", "结束日": "2025-06-30", "分区": "正式",
        "正式策略验收": True, "交易品种": "BTCUSDm", "初始资金": "300",
    }
    字段.update(修改)
    return 实验输入(**字段)  # type: ignore[arg-type]


def _报告(输入: 实验输入, 净收益: str) -> bytes:
    开始 = 输入.起始日.replace("-", ".")
    结束 = 输入.结束日.replace("-", ".")
    内容 = f'''<html><body><table>
<tr><td>Expert:</td><td>WaiTrade4\\BTC订单块分层风控</td></tr><tr><td>Symbol:</td><td>BTCUSDm</td></tr>
<tr><td>Period:</td><td>M5 ({开始} - {结束})</td></tr><tr><td>Initial Deposit:</td><td>300.00</td></tr>
<tr><td>History Quality:</td><td>100% real ticks</td></tr><tr><td>Total Net Profit:</td><td>{净收益}</td></tr>
<tr><td>Balance Drawdown Maximal:</td><td>0.00 (0.00%)</td></tr><tr><td>Equity Drawdown Maximal:</td><td>6.00 (2.00%)</td></tr>
<tr><td>Profit Factor:</td><td>1.25</td></tr><tr><td>Total Trades:</td><td>2</td></tr><tr><td>Total Deals:</td><td>4</td></tr></table>
<table><tr><td>Orders</td></tr><tr><td>Open Time</td><td>Order</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S / L</td><td>T / P</td><td>Time</td><td>State</td><td>Comment</td></tr>
<tr><td>{开始} 00:00:01</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>99000.00</td><td>99100.00</td><td></td><td>{开始} 00:00:01</td><td>filled</td><td>x</td></tr>
<tr><td>2025.02.01 00:00:01</td><td>4</td><td>BTCUSDm</td><td>sell</td><td>0.01 / 0.01</td><td>99000.00</td><td>99100.00</td><td></td><td>2025.02.01 00:00:01</td><td>filled</td><td>x</td></tr>
<tr><td>Deals</td></tr><tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td><td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td></tr>
<tr><td>{开始} 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td><td></td><td></td><td>0.00</td><td>0.00</td><td>300.00</td><td>300.00</td><td></td></tr>
<tr><td>{开始} 00:00:01</td><td>2</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>2</td><td>0.00</td><td>0.00</td><td>0.00</td><td>300.00</td><td>x</td></tr>
<tr><td>{开始} 00:00:02</td><td>3</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98900.00</td><td>2</td><td>0.00</td><td>0.00</td><td>1.00</td><td>301.00</td><td>x</td></tr>
<tr><td>2025.02.01 00:00:01</td><td>4</td><td>BTCUSDm</td><td>sell</td><td>in</td><td>0.01</td><td>99000.00</td><td>4</td><td>0.00</td><td>0.00</td><td>0.00</td><td>301.00</td><td>x</td></tr>
<tr><td>2025.02.01 00:00:02</td><td>5</td><td>BTCUSDm</td><td>buy</td><td>out</td><td>0.01</td><td>98900.00</td><td>4</td><td>0.00</td><td>0.00</td><td>1.00</td><td>302.00</td><td>x</td></tr></table></body></html>'''
    return b"\xff\xfe" + 内容.encode("utf-16le")


@dataclass
class _场景桩:
    复用报告: bool = False
    调用次数: int = 0

    def 运行(self, 场景: str, 输入: 实验输入, 暂存目录: Path, 参数路径: Path, 审计目录: Path) -> 正式场景结果:
        self.调用次数 += 1
        名称 = {"样本外": "报告.html", "压力": "压力报告.html", "无摩擦": "无摩擦报告.html"}[场景]
        报告 = 暂存目录 / 名称
        if self.复用报告 and 场景 == "压力":
            报告.write_bytes((暂存目录 / "报告.html").read_bytes())
        else:
            报告.write_bytes(_报告(输入, {"样本外": "2.00", "压力": "1.00", "无摩擦": "4.00"}[场景]))
        if 场景 == "样本外":
            审计目录.mkdir(parents=True)
            开始 = 输入.起始日.replace("-", ".")
            (审计目录 / "equity.csv").write_text(
                "time,balance,equity\n"
                f"{开始} 00:00:00.000,300,300\n{开始} 00:00:01.000,300,300\n{开始} 00:00:02.000,301,301\n2025.02.01 00:00:02.000,302,302\n", encoding="utf-8")
            (审计目录 / "opening_risk.csv").write_text(
                "deal_id,time,equity,initial_risk,open_initial_risk\n"
                f"2,{开始} 00:00:01,300,1,1\n4,2025.02.01 00:00:01,301,1,1\n", encoding="utf-8")
        return 正式场景结果(
            报告路径=报告, 审计目录=审计目录 if 场景 == "样本外" else None,
            极端压力风险通过=场景 == "压力",
            实际二进制哈希=输入.二进制哈希,
        )


def _配置(tmp_path: Path) -> BTC正式单期配置:
    return BTC正式单期配置(代理地址="127.0.0.1:7897", 代理TLS端点=("mt5.example", 443), 审计根目录=tmp_path / "ea-audit")


def test_代理前置失败不启动任何正式场景(tmp_path: Path) -> None:
    场景 = _场景桩()
    执行器 = 正式BTC单期执行器(_配置(tmp_path), 场景, lambda *_: {"通过": False, "原因": "timeout"})

    结果 = 执行器.执行(_输入(), tmp_path / "run")

    assert 结果.状态 is 实验状态.执行无效
    assert "代理前置" in str(结果.结果["原因"])
    assert 场景.调用次数 == 0


def test_正式单期封存三场景报告和独立风险工件(tmp_path: Path) -> None:
    场景 = _场景桩()
    执行器 = 正式BTC单期执行器(_配置(tmp_path), 场景, lambda *_: {"通过": True})
    暂存 = tmp_path / "run"
    暂存.mkdir()

    结果 = 执行器.执行(_输入(), 暂存)

    assert 结果.状态 is 实验状态.已归档
    assert 场景.调用次数 == 3
    参数组 = sorted(暂存.glob("正式运行参数-*.set"))
    assert len(参数组) == 3
    assert all(参数.read_text(encoding="utf-8").find("InpRiskPercent=3.0") >= 0 for 参数 in 参数组)
    assert 结果.报告工件 == ("报告.html", r"WaiTrade4\BTC订单块分层风控", "M5")
    assert set(结果.风险证据工件 or ()) == {"逐tick权益.json", "开仓风险.json", "风险限额.json"}
    assert all(sha256((暂存 / 名称).read_bytes()).hexdigest() == 哈希 for 名称, 哈希 in 结果.工件.items())


def test_正式单期拒绝复用样本外报告冒充压力报告(tmp_path: Path) -> None:
    场景 = _场景桩(复用报告=True)
    执行器 = 正式BTC单期执行器(_配置(tmp_path), 场景, lambda *_: {"通过": True})
    暂存 = tmp_path / "run"
    暂存.mkdir()

    结果 = 执行器.执行(_输入(), 暂存)

    assert 结果.状态 is 实验状态.治理无效
    assert "报告内容重复" in str(结果.结果["原因"])


def test_非正式BTC输入不启动正式场景(tmp_path: Path) -> None:
    场景 = _场景桩()
    执行器 = 正式BTC单期执行器(_配置(tmp_path), 场景, lambda *_: {"通过": True})

    结果 = 执行器.执行(_输入(交易品种="ETHUSDm", 合约规格="ETHUSDm"), tmp_path / "run")

    assert 结果.状态 is 实验状态.治理无效
    assert 场景.调用次数 == 0


def test_正式单期拒绝场景自报但未绑定实际加载二进制(tmp_path: Path) -> None:
    @dataclass
    class 二进制不一致场景(_场景桩):
        def 运行(self, 场景: str, 输入: 实验输入, 暂存目录: Path, 参数路径: Path, 审计目录: Path) -> 正式场景结果:
            结果 = super().运行(场景, 输入, 暂存目录, 参数路径, 审计目录)
            return 正式场景结果(
                报告路径=结果.报告路径, 审计目录=结果.审计目录,
                极端压力风险通过=结果.极端压力风险通过, 实际二进制哈希="1" * 64,
            )

    场景 = 二进制不一致场景()
    执行器 = 正式BTC单期执行器(_配置(tmp_path), 场景, lambda *_: {"通过": True})
    暂存 = tmp_path / "run"
    暂存.mkdir()

    结果 = 执行器.执行(_输入(), 暂存)

    assert 结果.状态 is 实验状态.治理无效
    assert "二进制哈希" in str(结果.结果["原因"])


def test_真实场景运行器只接受runtime内专属wine前缀(tmp_path: Path) -> None:
    wine = tmp_path / "wine"
    wine.write_text("wine", encoding="utf-8")
    前缀 = tmp_path / "shared-prefix"
    终端 = 前缀 / "drive_c/Program Files/MetaTrader 5"
    (终端 / "terminal64.exe").parent.mkdir(parents=True)
    (终端 / "terminal64.exe").write_bytes(b"terminal")

    try:
        真实MT5正式场景运行器(正式MT5场景运行配置(wine, 前缀, 终端, "1", "server", 10))
    except ValueError as 异常:
        assert "runtime" in str(异常)
    else:
        raise AssertionError("共享 Wine Prefix 不得用于正式运行")


def test_真实场景运行器封存唯一场景报告并绑定实际_ex5(tmp_path: Path, monkeypatch) -> None:
    from wt4.编排 import 执行结果
    from wt4.mt5单实例探测 import 单实例MT5探测执行器

    runtime = Path(__file__).resolve().parents[1] / "runtime"
    前缀 = runtime / f"test-正式场景-{tmp_path.name}"
    终端 = 前缀 / "drive_c/Program Files/MetaTrader 5"
    for 名称, 内容 in {
        "terminal64.exe": b"terminal",
        "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5": b"actual-ex5",
    }.items():
        路径 = 终端 / 名称
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_bytes(内容)
    wine = tmp_path / "wine"
    wine.write_text("wine", encoding="utf-8")
    暂存 = tmp_path / "run"
    暂存.mkdir()
    参数 = 暂存 / "正式运行参数-样本外.set"
    参数.write_text("InpRiskPercent=3.0\n", encoding="utf-8")
    审计 = 终端 / "MQL5/Files/wt4/audit" / ("a" * 64)

    def 伪执行(self, 输入, 暂存目录):
        (暂存目录 / self.报告封存名称).write_bytes(_报告(输入, "2.00"))
        return 执行结果(实验状态.已归档, {}, {})

    monkeypatch.setattr(单实例MT5探测执行器, "执行", 伪执行)
    运行器 = 真实MT5正式场景运行器(
        正式MT5场景运行配置(wine, 前缀, 终端, "1", "server", 10)
    )

    结果 = 运行器.运行("样本外", _输入(), 暂存, 参数, 审计)

    assert 结果.报告路径 == 暂存 / "报告.html"
    assert 结果.实际二进制哈希 == sha256(b"actual-ex5").hexdigest()
    assert (暂存 / "样本外-mt5运行/正式运行参数-样本外.set").is_file()
    assert 结果.工件 is not None
    assert "样本外-mt5运行/报告.html" not in 结果.工件
    assert "报告.html" in 结果.工件


def test_真实场景运行器拒绝运行期间替换_ex5(tmp_path: Path, monkeypatch) -> None:
    from wt4.编排 import 执行结果
    from wt4.mt5单实例探测 import 单实例MT5探测执行器

    runtime = Path(__file__).resolve().parents[1] / "runtime"
    前缀 = runtime / f"test-正式场景-替换-{tmp_path.name}"
    终端 = 前缀 / "drive_c/Program Files/MetaTrader 5"
    二进制 = 终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
    for 路径, 内容 in ((终端 / "terminal64.exe", b"terminal"), (二进制, b"actual-ex5")):
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_bytes(内容)
    wine = tmp_path / "wine"
    wine.write_text("wine", encoding="utf-8")
    暂存 = tmp_path / "run"
    暂存.mkdir()
    参数 = 暂存 / "正式运行参数-样本外.set"
    参数.write_text("InpRiskPercent=3.0\n", encoding="utf-8")
    审计 = 终端 / "MQL5/Files/wt4/audit" / ("b" * 64)

    def 伪执行(self, 输入, 暂存目录):
        二进制.write_bytes(b"replaced-ex5")
        (暂存目录 / self.报告封存名称).write_bytes(_报告(输入, "2.00"))
        return 执行结果(实验状态.已归档, {}, {})

    monkeypatch.setattr(单实例MT5探测执行器, "执行", 伪执行)
    运行器 = 真实MT5正式场景运行器(正式MT5场景运行配置(wine, 前缀, 终端, "1", "server", 10))

    try:
        运行器.运行("样本外", _输入(), 暂存, 参数, 审计)
    except ValueError as 异常:
        assert "EX5" in str(异常)
    else:
        raise AssertionError("运行中被替换的 EX5 不得形成正式场景结果")
