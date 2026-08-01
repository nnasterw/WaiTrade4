from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import uuid4

from wt4.mt5后台 import MT5后台进程
from wt4.mt5单实例探测 import 单实例MT5探测执行器
from wt4.mt5并发探测 import 两实例MT5并发探测器
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.mt5能力 import 测试实例配置, 校验实例隔离
from wt4.运行单实例能力探测 import 计算三风险参数内容, 核验SOCKS5代理前置
from wt4.账本 import 追加式账本


工作区 = Path(__file__).resolve().parent.parent
默认Wine = Path("/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine")
默认隔离根目录 = 工作区 / "runtime/MT5并发能力/隔离实例"
默认历史参数 = Path(
    "/Users/wen/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Profiles/Tester/v11btc-r234.set"
)


def _实例(名称: str, 前缀: Path, 运行根目录: Path) -> 测试实例配置:
    终端 = 前缀 / "drive_c/Program Files/MetaTrader 5 Tester"
    return 测试实例配置(
        名称, 终端, 前缀 / "drive_c/Program Files/MetaTrader 5", 前缀,
        运行根目录 / "输出" / 名称, 运行根目录 / "临时" / 名称,
        终端 / "MQL5/Profiles/Tester", 终端 / "Tester/cache",
    )


def _参数文件(来源: Path, 输入目录: Path, 标识: str, 名称: str) -> tuple[str, Path]:
    内容 = 计算三风险参数内容(来源)
    哈希 = sha256(内容).hexdigest()
    文件名 = f"wt4-{标识}-{名称}-{哈希[:12]}.set"
    路径 = 输入目录 / 文件名
    路径.write_bytes(内容)
    return 文件名, 路径


def _确认专属Wine前缀未被占用(*Wine前缀: Path) -> None:
    """只拒绝本轮专属 Prefix 被占用，绝不枚举或干扰共享 MT5/Wine。"""
    if not Wine前缀:
        raise ValueError("至少需要一个专属 Wine 前缀")
    被占用 = {str(前缀): sorted(MT5后台进程._查询Wine服务(前缀)) for 前缀 in Wine前缀}
    被占用 = {前缀: 进程号 for 前缀, 进程号 in 被占用.items() if 进程号}
    if 被占用:
        raise RuntimeError(f"本轮专属 Wine 前缀仍有服务进程，拒绝重叠启动: {被占用}")


def _写入结论并完成记账(
    运行根目录: Path,
    账本: 追加式账本,
    标识: str,
    证据: dict[str, object],
    *,
    终态: str = "已完成",
) -> None:
    """同时留下结论文件和追加式终态，失败观测也不可成为半成品。

    结论先以原子替换落盘；随后无论探测是通过、未通过还是异常，都
    追加一个终态事件。严格核验器仍会拒绝不通过的结论，但不会把真实
    失败错误地表现为只有“已创建”的不可审计运行。
    """
    # ``asdict(测试实例配置)`` 中包含 Path；结论和账本必须落下同一份
    # 已规范化 JSON 数据，避免结论已经存在而终态账本因序列化失败缺失。
    可记账证据 = json.loads(json.dumps(证据, ensure_ascii=False, default=str))
    结论路径 = 运行根目录 / "并发结论.json"
    临时路径 = 结论路径.with_name(f".{结论路径.name}.{标识}.tmp")
    临时路径.write_text(json.dumps(可记账证据, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(结论路径)
    账本.追加(标识, 终态, 可记账证据)


def _提取运行诊断(运行根目录: Path) -> dict[str, dict[str, dict[str, object]]]:
    """提取每次运行实际连接的 Agent 端点及授权错误，供并发失败归因。"""
    诊断: dict[str, dict[str, dict[str, object]]] = {}
    for 阶段 in ("串行", "并行"):
        诊断[阶段] = {}
        for 名称 in ("甲", "乙"):
            日志 = 运行根目录 / 阶段 / 名称 / "MT5日志证据.txt"
            内容 = 日志.read_text(encoding="utf-8", errors="replace") if 日志.is_file() else ""
            端点 = re.findall(r"agent process started on (127\.0\.0\.1:\d+)", 内容, flags=re.IGNORECASE)
            诊断[阶段][名称] = {
                "Agent端点": sorted(set(端点)),
                "存在Agent授权错误": "tester agent authorization error" in 内容.lower(),
            }
    return 诊断


def main() -> None:
    参数 = argparse.ArgumentParser(description="实测 wt4 两套隔离 MT5 Tester 的串行与并行能力")
    参数.add_argument("--开始日", default="2025.03.02")
    参数.add_argument("--结束日", default="2025.03.03")
    参数.add_argument("--超时秒数", type=int, default=600)
    参数.add_argument("--最低加速比", type=float, default=1.10)
    参数.add_argument("--登录账号", default="277656700")
    参数.add_argument("--服务器", default="Exness-MT5Trial5")
    参数.add_argument("--wine", type=Path, default=默认Wine)
    参数.add_argument("--隔离根目录", type=Path, default=默认隔离根目录)
    参数.add_argument("--历史参数", type=Path, default=默认历史参数)
    参数.add_argument("--代理地址", default="127.0.0.1:7897")
    实参 = 参数.parse_args()

    if not 实参.wine.is_file() or not 实参.历史参数.is_file() or 实参.超时秒数 <= 0:
        raise SystemExit("Wine、历史参数或超时参数无效")
    try:
        代理前置探测 = 核验SOCKS5代理前置(实参.代理地址)
    except ValueError as 异常:
        raise SystemExit(str(异常)) from 异常
    标识 = uuid4().hex[:16]
    运行根目录 = 工作区 / "runtime/MT5并发能力/工件" / 标识
    输入目录 = 运行根目录 / "输入"
    输入目录.mkdir(parents=True)
    账本 = 追加式账本(运行根目录 / "账本.sqlite")
    实例 = {名称: _实例(名称, 实参.隔离根目录 / f"{名称}-wine前缀", 运行根目录) for 名称 in ("甲", "乙")}
    校验实例隔离(list(实例.values()))
    _确认专属Wine前缀未被占用(*(配置.Wine前缀 for 配置 in 实例.values()))
    for 配置 in 实例.values():
        if not (配置.终端目录 / "terminal64.exe").is_file() or not 配置.Wine前缀.is_dir():
            raise SystemExit(f"隔离 MT5 实例不完整: {配置.名称}")
    账本.追加(标识, "已创建", {"开始日": 实参.开始日, "结束日": 实参.结束日, "实例": ["甲", "乙"], "SOCKS5代理前置探测": 代理前置探测})

    def 执行函数(名称: str):
        def 执行(暂存目录: Path):
            阶段 = 暂存目录.parent.name
            参数名, 参数路径 = _参数文件(实参.历史参数, 输入目录, f"{标识}-{阶段}", 名称)
            配置 = MT5短窗口探测配置(
                终端目录=实例[名称].终端目录, 专家顾问=r"WaiTrade2\WaiTrade_OB", 参数文件=参数名,
                品种="BTCUSDm", 周期="M1", 开始日=实参.开始日, 结束日=实参.结束日,
                初始资金=300, 杠杆=2000, 登录账号=实参.登录账号, 服务器=实参.服务器, 代理地址=实参.代理地址, 参数文件路径=参数路径,
            )
            return 单实例MT5探测执行器(配置, 实参.wine, 实例[名称].Wine前缀, 实参.超时秒数).执行(None, 暂存目录)
        return 执行

    期望 = 报告期望(r"WaiTrade_OB", "BTCUSDm", "M1", 实参.开始日, 实参.结束日, Decimal("300.00"))
    探测器 = 两实例MT5并发探测器(
        {名称: 执行函数(名称) for 名称 in ("甲", "乙")},
        lambda 路径: 解析MT5报告(路径, 期望),
        实参.最低加速比,
    )
    try:
        结果 = 探测器.执行(运行根目录)
        证据: dict[str, object] = {
            "实验标识": 标识, "实例": {名称: asdict(配置) for 名称, 配置 in 实例.items()},
            "串行墙钟秒": 结果.串行墙钟秒, "并行墙钟秒": 结果.并行墙钟秒, "加速比": 结果.加速比,
            "两实例逐笔一致": 结果.两实例逐笔一致,
            "并发失败率为零且有效提速": 结果.并发失败率为零且有效提速,
            "串行状态": {名称: 结果.状态.value for 名称, 结果 in 结果.串行结果.items()},
            "并行状态": {名称: 结果.状态.value for 名称, 结果 in 结果.并行结果.items()},
            "运行诊断": _提取运行诊断(运行根目录),
        }
    except BaseException as 异常:
        证据 = {
            "实验标识": 标识,
            "实例": {名称: asdict(配置) for 名称, 配置 in 实例.items()},
            "异常类型": type(异常).__name__,
            "原因": str(异常),
        }
        _写入结论并完成记账(运行根目录, 账本, 标识, 证据, 终态="执行无效")
        raise
    _写入结论并完成记账(运行根目录, 账本, 标识, 证据)
    print(json.dumps(证据, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
