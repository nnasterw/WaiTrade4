from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

from wt4.mt5单实例探测 import 单实例MT5探测执行器
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.mt5重复探测 import 单实例MT5重复探测器
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.运行两实例并发能力探测 import _确认无既有MT5进程
from wt4.运行单实例能力探测 import 创建输入, 生成三风险参数副本, 生成参数文件名, 计算三风险参数内容
from wt4.账本 import 追加式账本
from wt4.编排 import 中央实验编排器


工作区 = Path(__file__).resolve().parent.parent
默认Wine = Path("/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine")
默认Wine前缀 = Path("/Users/wen/Library/Application Support/net.metaquotes.wine.metatrader5")
默认Tester = 默认Wine前缀 / "drive_c/Program Files/MetaTrader 5 Tester"
默认历史参数 = 默认Wine前缀 / "drive_c/Program Files/MetaTrader 5/MQL5/Profiles/Tester/v11btc-r234.set"


def main() -> None:
    参数 = argparse.ArgumentParser(description="实测同一隔离 MT5 实例的两次顺序回测一致性")
    参数.add_argument("--开始日", default="2025.03.02")
    参数.add_argument("--结束日", default="2025.03.03")
    参数.add_argument("--超时秒数", type=int, default=600)
    参数.add_argument("--登录账号", default="277656700")
    参数.add_argument("--服务器", default="Exness-MT5Trial5")
    参数.add_argument("--wine", type=Path, default=默认Wine)
    参数.add_argument("--wine前缀", type=Path, default=默认Wine前缀)
    参数.add_argument("--tester", type=Path, default=默认Tester)
    参数.add_argument("--历史参数", type=Path, default=默认历史参数)
    实参 = 参数.parse_args()
    if not 实参.wine.is_file() or not 实参.wine前缀.is_dir() or not 实参.tester.is_dir() or not 实参.历史参数.is_file() or 实参.超时秒数 <= 0:
        raise SystemExit("Wine、Wine前缀、Tester、历史参数或超时参数无效")
    if not (实参.tester / "terminal64.exe").is_file() or not (实参.tester / "MQL5/Experts/WaiTrade2/WaiTrade_OB.ex5").is_file():
        raise SystemExit("MT5 Tester 或历史成功 EA 不存在")
    _确认无既有MT5进程()

    标识 = uuid4().hex[:16]
    根目录 = 工作区 / "runtime/MT5重复能力/工件" / 标识
    输入目录 = 根目录 / "输入"
    输入目录.mkdir(parents=True)
    账本 = 追加式账本(根目录 / "账本.sqlite")
    参数哈希 = __import__("hashlib").sha256(计算三风险参数内容(实参.历史参数)).hexdigest()
    输入与工件: dict[str, tuple[object, Path]] = {}

    def 执行(轮次: str):
        英文轮次 = {"首次": "first", "再次": "second"}[轮次]
        试验标识 = f"repeat-{标识[:12]}-{英文轮次}"
        参数名 = 生成参数文件名(参数哈希, 实参.开始日, 实参.结束日, 实参.超时秒数, 试验标识)
        参数副本 = 输入目录 / 参数名
        生成三风险参数副本(实参.历史参数, 参数副本)
        配置 = MT5短窗口探测配置(
            实参.tester, r"WaiTrade2\WaiTrade_OB", 参数名, "BTCUSDm", "M1",
            实参.开始日, 实参.结束日, 300, 2000, 实参.登录账号, 实参.服务器, 参数文件路径=参数副本,
        )
        输入 = 创建输入(参数哈希, 配置, 实参.超时秒数, 试验标识)
        编排器 = 中央实验编排器(账本, 根目录 / "暂存", 根目录 / "归档")
        结果 = 编排器.运行(输入, 单实例MT5探测执行器(配置, 实参.wine, 实参.wine前缀, 实参.超时秒数))
        输入与工件[轮次] = (结果, 结果.工件目录 / "报告.html" if 结果.工件目录 else Path())
        # 只要运行结束便拒绝容忍残留；下一轮也由这一检查隔开。
        _确认无既有MT5进程()
        from wt4.编排 import 执行结果, 实验状态
        return 执行结果(结果.状态, {}, {"实验身份": 结果.实验身份, "工件目录": str(结果.工件目录) if 结果.工件目录 else None})

    期望 = 报告期望("WaiTrade_OB", "BTCUSDm", "M1", 实参.开始日, 实参.结束日, Decimal("300.00"))
    探测 = 单实例MT5重复探测器(
        执行, lambda 轮次: 输入与工件[轮次][1], lambda 路径: 解析MT5报告(路径, 期望),
    ).执行()
    证据 = {
        "实验标识": 标识, "配置": {"开始日": 实参.开始日, "结束日": 实参.结束日, "初始资金": 300, "风险百分比": 3.0},
        "首次状态": 探测.首次.状态.value, "再次状态": 探测.再次.状态.value,
        "数据报告完整": 探测.报告完整, "单实例重复一致": 探测.逐笔一致, "通过": 探测.通过,
        "首次实验": 探测.首次.结果, "再次实验": 探测.再次.结果,
    }
    (根目录 / "重复结论.json").write_text(json.dumps(证据, ensure_ascii=False, indent=2), encoding="utf-8")
    账本.追加(标识, "重复能力已完成", 证据)
    print(json.dumps(证据, ensure_ascii=False))


if __name__ == "__main__":
    main()
