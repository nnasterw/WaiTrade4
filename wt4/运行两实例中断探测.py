from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from time import sleep
from uuid import uuid4

from wt4.mt5后台 import MT5后台进程
from wt4.mt5执行 import 隔离MT5执行器
from wt4.mt5单实例探测 import 单实例MT5探测执行器, 解析MT5生命周期, 解析MT5实际测试区间
from wt4.mt5探测 import MT5短窗口探测配置, 生成MT5探测配置
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.mt5中断探测 import 两实例中断探测器
from wt4.mt5能力 import 校验实例隔离
from wt4.运行两实例并发能力探测 import _实例, _确认无既有MT5进程
from wt4.运行单实例能力探测 import 计算三风险参数内容
from wt4.账本 import 追加式账本


工作区 = Path(__file__).resolve().parent.parent
默认Wine = Path("/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine")
默认隔离根目录 = 工作区 / "runtime/MT5并发能力/隔离实例"
默认历史参数 = Path(
    "/Users/wen/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Profiles/Tester/v11btc-r234.set"
)


def _准备实例运行(
    名称: str, 开始日: str, 结束日: str, 标识: str, 根目录: Path, 实例, 历史参数: Path, wine: Path, 账号: str, 服务器: str, 超时秒数: int,
) -> tuple[MT5后台进程, Path, MT5短窗口探测配置, dict[str, bytes]]:
    暂存 = 根目录 / 名称
    暂存.mkdir()
    内容 = 计算三风险参数内容(历史参数)
    参数名 = f"wt4-interrupt-{标识}-{名称}-{sha256(内容).hexdigest()[:12]}.set"
    参数路径 = 暂存 / 参数名
    参数路径.write_bytes(内容)
    配置 = MT5短窗口探测配置(
        实例.终端目录, r"WaiTrade2\WaiTrade_OB", 参数名, "BTCUSDm", "M1",
        开始日, 结束日, 300, 2000, 账号, 服务器, 参数文件路径=参数路径,
    )
    # 复用单实例执行器的实际 Parameter 目录规则，且唯一命名、拒绝覆盖。
    执行器 = 单实例MT5探测执行器(配置, wine, 实例.Wine前缀, 超时秒数)
    执行器._准备参数输入(暂存)
    ini = 生成MT5探测配置(配置, 暂存)
    命令 = (str(wine), r"C:\Program Files\MetaTrader 5 Tester\terminal64.exe", f"/config:{单实例MT5探测执行器._mac路径转WineZ盘(ini)}")
    日志快照 = 执行器._日志字节快照()
    return MT5后台进程.启动(命令, 暂存, {"WINEPREFIX": str(实例.Wine前缀)}, 暂存), 暂存, 配置, 日志快照


def _封存并哈希(目录: Path) -> dict[str, str]:
    工件: dict[str, str] = {}
    for 路径 in sorted(目录.rglob("*")):
        if 路径.is_file() and not 路径.is_symlink() and 路径.name not in {"账本.sqlite", "中断结论.json"}:
            工件[路径.relative_to(目录).as_posix()] = 隔离MT5执行器._哈希(路径)
    return 工件


def main() -> None:
    参数 = argparse.ArgumentParser(description="实测中断一个隔离 MT5 实例不会污染另一实例")
    参数.add_argument("--甲开始日", default="2025.03.01")
    参数.add_argument("--甲结束日", default="2025.04.01")
    参数.add_argument("--乙开始日", default="2025.03.02")
    参数.add_argument("--乙结束日", default="2025.03.03")
    参数.add_argument("--启动宽限秒", type=float, default=12)
    参数.add_argument("--第二实例启动间隔秒", type=float, default=2)
    参数.add_argument("--乙超时秒", type=int, default=180)
    参数.add_argument("--登录账号", default="277656700")
    参数.add_argument("--服务器", default="Exness-MT5Trial5")
    参数.add_argument("--wine", type=Path, default=默认Wine)
    参数.add_argument("--隔离根目录", type=Path, default=默认隔离根目录)
    参数.add_argument("--历史参数", type=Path, default=默认历史参数)
    实参 = 参数.parse_args()
    if not 实参.wine.is_file() or not 实参.历史参数.is_file():
        raise SystemExit("Wine 或历史参数无效")
    _确认无既有MT5进程()
    标识 = uuid4().hex[:16]
    根目录 = 工作区 / "runtime/MT5并发能力/中断工件" / 标识
    根目录.mkdir(parents=True)
    实例 = {名称: _实例(名称, 实参.隔离根目录 / f"{名称}-wine前缀", 根目录) for 名称 in ("甲", "乙")}
    校验实例隔离(list(实例.values()))
    账本 = 追加式账本(根目录 / "账本.sqlite")
    账本.追加(标识, "已创建", {
        "甲区间": [实参.甲开始日, 实参.甲结束日], "乙区间": [实参.乙开始日, 实参.乙结束日],
        "启动宽限秒": 实参.启动宽限秒, "第二实例启动间隔秒": 实参.第二实例启动间隔秒, "乙超时秒": 实参.乙超时秒,
    })
    启动记录: dict[str, tuple[Path, MT5短窗口探测配置, dict[str, bytes]]] = {}

    def 启动(名称: str, 开始日: str, 结束日: str) -> MT5后台进程:
        进程, 暂存, 配置, 日志快照 = _准备实例运行(名称, 开始日, 结束日, 标识, 根目录, 实例[名称], 实参.历史参数, 实参.wine, 实参.登录账号, 实参.服务器, 实参.乙超时秒)
        启动记录[名称] = (暂存, 配置, 日志快照)
        return 进程

    结果 = 两实例中断探测器(
        lambda: 启动("甲", 实参.甲开始日, 实参.甲结束日),
        lambda: 启动("乙", 实参.乙开始日, 实参.乙结束日),
    ).执行(实参.启动宽限秒, 实参.乙超时秒, 实参.第二实例启动间隔秒)
    乙暂存, 乙配置, 乙运行前日志 = 启动记录["乙"]
    乙执行器 = 单实例MT5探测执行器(乙配置, 实参.wine, 实例["乙"].Wine前缀, 实参.乙超时秒)
    日志 = 乙执行器._保留本次日志证据(乙暂存, 乙运行前日志)
    生命周期 = 解析MT5生命周期((乙暂存 / 日志).read_text(encoding="utf-8"))
    报告名 = 单实例MT5探测执行器._配置报告名称(乙暂存 / "mt5-探测.ini")
    报告源 = 实例["乙"].终端目录 / f"{报告名}.htm"
    if not 报告源.is_file():
        raise RuntimeError("乙实例被污染或未完成：缺少报告")
    报告目标 = 乙暂存 / "报告.html"
    if 报告目标.exists():
        raise RuntimeError("乙报告封存目标已存在")
    报告目标.write_bytes(报告源.read_bytes())
    报告 = 解析MT5报告(报告目标, 报告期望("WaiTrade_OB", "BTCUSDm", "M1", 实参.乙开始日, 实参.乙结束日, Decimal("300.00")))
    实际区间 = 解析MT5实际测试区间((乙暂存 / 日志).read_text(encoding="utf-8"))
    try:
        _确认无既有MT5进程()
        无残留 = True
    except RuntimeError:
        无残留 = False
    严格通过 = (
        结果.通过
        and 生命周期["完整"]
        and 实际区间 == (实参.乙开始日, 实参.乙结束日)
        and 无残留
    )
    工件 = _封存并哈希(根目录)
    证据 = {
        "实验标识": 标识, "中断无污染": 严格通过, "进程隔离通过": 结果.通过, "甲返回码": 结果.被中断返回码,
        "甲被中断时仍运行": 结果.被中断时仍运行, "乙返回码": 结果.未中断返回码,
        "甲受限回收Wine服务进程号": list(结果.被中断Wine服务进程号),
        "乙受限回收Wine服务进程号": list(结果.未中断Wine服务进程号),
        "乙生命周期完整": 生命周期["完整"], "乙实际测试区间": 实际区间,
        "乙报告成交数": len(报告.成交), "乙净利润": str(报告.净利润),
        "运行结束无MT5Wine残留": 无残留, "工件哈希": 工件,
    }
    (根目录 / "中断结论.json").write_text(json.dumps(证据, ensure_ascii=False, indent=2), encoding="utf-8")
    账本.追加(标识, "已完成", 证据)
    print(json.dumps(证据, ensure_ascii=False))


if __name__ == "__main__":
    main()
