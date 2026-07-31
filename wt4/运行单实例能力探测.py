from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import socket

from wt4.experiment import 实验输入
from wt4.mt5单实例探测 import 单实例MT5探测执行器, 通过SOCKS5探测端点
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.账本 import 追加式账本
from wt4.编排 import 中央实验编排器


工作区 = Path(__file__).resolve().parent.parent
默认Wine = Path("/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine")
默认Wine前缀 = Path("/Users/wen/Library/Application Support/net.metaquotes.wine.metatrader5")
默认Tester = 默认Wine前缀 / "drive_c/Program Files/MetaTrader 5 Tester"
默认历史参数 = 默认Wine前缀 / (
    "drive_c/Program Files/MetaTrader 5/MQL5/Profiles/Tester/v11btc-r234.set"
)
默认代理地址 = "127.0.0.1:7897"
默认代理探测端点 = ("mt5.exness.com", 443)
默认Mihomo日志 = Path(
    "/Users/wen/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/logs/latest.log"
)


def 计算三风险参数内容(来源: Path) -> bytes:
    """仅替换历史参数中的单笔风险，禁止改变其他策略参数。"""
    内容 = 来源.read_text(encoding="utf-8")
    新内容, 替换数 = re.subn(r"(?m)^InpRiskPercent=[^\r\n]*$", "InpRiskPercent=3.0", 内容)
    if 替换数 != 1:
        raise ValueError(f"参数文件必须且只能包含一个 InpRiskPercent，实际: {替换数}")
    if "InpRiskPercent=6.5" not in 内容:
        raise ValueError("历史参数基线不是预期的 6.5% 风险版本，拒绝实验")
    return 新内容.encode("utf-8")


def 生成三风险参数副本(来源: Path, 目标: Path) -> str:
    """生成不可覆盖的三风险参数副本，并返回其内容哈希。"""
    新内容 = 计算三风险参数内容(来源)
    目标.parent.mkdir(parents=True, exist_ok=True)
    if 目标.exists():
        raise ValueError(f"拒绝覆盖既有运行参数副本: {目标}")
    目标.write_bytes(新内容)
    return sha256(新内容).hexdigest()


def 生成参数文件名(参数哈希: str, 开始日: str, 结束日: str, 超时秒数: int, 试验标识: str) -> str:
    """由不可变输入派生 Tester 参数名，避免共享目录同名覆盖。"""
    if not re.fullmatch(r"[0-9a-f]{64}", 参数哈希):
        raise ValueError("参数哈希必须是 SHA-256 十六进制摘要")
    日期标识 = f"{开始日}-{结束日}".replace(".", "")
    if not re.fullmatch(r"\d{8}-\d{8}", 日期标识) or 超时秒数 <= 0:
        raise ValueError("参数文件名输入无效")
    if not re.fullmatch(r"[a-z0-9-]{1,32}", 试验标识):
        raise ValueError("试验标识仅允许小写字母、数字和连字符，且最长 32 位")
    return f"v11btc-r234-risk3-{日期标识}-t{超时秒数}-{试验标识}-{参数哈希[:12]}.set"


def 核验SOCKS5代理前置(
    代理地址: str = 默认代理地址,
    探测端点: tuple[str, int] = 默认代理探测端点,
) -> dict[str, object]:
    """只在 SOCKS5 CONNECT 已通过时允许启动 MT5，绝不降级直连。"""
    探测 = 通过SOCKS5探测端点(代理地址, *探测端点)
    if 探测.get("通过") is not True:
        raise ValueError(f"SOCKS5 代理前置探测失败，拒绝启动 MT5: {探测}")
    return 探测


def 核验离线代理隔离前置(代理地址: str) -> dict[str, object]:
    """确认离线边界实验只会连接一个不可用的环回 SOCKS5 地址。

    该模式用于验证 MT5 在代理不可用时是否严格失败，而不是验证外部
    网络可达性。它拒绝非环回地址、默认代理端口和任何已监听地址，
    因而无法产生外部出口流量，也不允许回退直连。
    """
    try:
        主机, 端口文本 = 代理地址.rsplit(":", 1)
        端口 = int(端口文本)
    except (AttributeError, ValueError) as 异常:
        raise ValueError(f"离线代理地址无效: {代理地址}") from 异常
    # CLI 地址格式当前只定义为 IPv4 的 ``host:port``。避免把未加方括号的
    # IPv6 字面量误解析成可用地址，进而放宽隔离实验的网络边界。
    if 主机 != "127.0.0.1" or not 0 < 端口 < 65536:
        raise ValueError("离线代理隔离仅允许未监听的 127.0.0.1 地址")
    if 代理地址 == 默认代理地址:
        raise ValueError("离线代理隔离不得使用默认7897代理")
    try:
        with socket.create_connection((主机, 端口), timeout=0.5):
            raise ValueError(f"离线代理地址正在监听，拒绝实验: {代理地址}")
    except ConnectionRefusedError:
        return {"模式": "离线代理隔离", "代理地址": 代理地址, "代理监听": False}
    except TimeoutError as 异常:
        raise ValueError(f"离线代理地址未明确拒绝连接，拒绝实验: {代理地址}") from 异常
    except OSError as 异常:
        raise ValueError(f"离线代理地址无法确认拒绝连接，拒绝实验: {代理地址}") from 异常


def 创建输入(
    参数哈希: str,
    配置: MT5短窗口探测配置,
    超时秒数: int,
    试验标识: str = "initial",
    代理前置探测: dict[str, object] | None = None,
) -> 实验输入:
    return 实验输入(
        策略实现提交="历史成功链兼容性探测:WaiTrade2/WaiTrade_OB",
        二进制哈希=sha256((配置.终端目录 / "MQL5/Experts/WaiTrade2/WaiTrade_OB.ex5").read_bytes()).hexdigest(),
        参数={
            "实验": "历史成功执行链兼容性探测",
            "唯一变量": "MT5实际参数加载路径与历史下载等待上限",
            "参数文件哈希": 参数哈希,
            "ExpertParameters": 配置.参数文件,
            "试验标识": 试验标识,
            "日期字段规范": "FromDate/ToDate",
            "InpRiskPercent": 3.0,
            "配置路径": "工作区ASCII暂存目录",
            "MT5实际参数目录": "Tester/MQL5/Profiles/Tester",
            "运行超时秒数": 超时秒数,
            "SOCKS5代理前置探测": 代理前置探测,
        },
        数据指纹="MT5-Tester-远程数据:BTCUSDm-M1",
        成本快照="MT5-Tester-实时合约与报价",
        合约规格="BTCUSDm",
        mt5版本="MetaTrader 5 Tester",
        建模方式=4,
        起始日=配置.开始日,
        结束日=配置.结束日,
        分区="能力探测",
    )


def main() -> None:
    参数 = argparse.ArgumentParser(description="运行 wt4 单实例 MT5 历史成功链兼容性探测")
    参数.add_argument("--开始日", default="2026.05.12")
    参数.add_argument("--结束日", default="2026.05.13")
    参数.add_argument("--超时秒数", type=int, default=600)
    参数.add_argument("--试验标识", default="fromdate-v1")
    参数.add_argument("--登录账号", default="277656700")
    参数.add_argument("--服务器", default="Exness-MT5Trial5")
    参数.add_argument("--wine", type=Path, default=默认Wine)
    参数.add_argument("--wine前缀", type=Path, default=默认Wine前缀)
    参数.add_argument("--tester", type=Path, default=默认Tester)
    参数.add_argument("--历史参数", type=Path, default=默认历史参数)
    参数.add_argument("--mihomo日志", type=Path, default=默认Mihomo日志)
    参数.add_argument("--代理地址", default=默认代理地址)
    参数.add_argument("--离线代理隔离", action="store_true")
    实参 = 参数.parse_args()

    if not 实参.wine.is_file() or not 实参.tester.is_dir() or not 实参.wine前缀.is_dir():
        raise SystemExit("Wine、Wine 前缀或 Tester 路径无效")
    if not (实参.tester / "MQL5/Experts/WaiTrade2/WaiTrade_OB.ex5").is_file():
        raise SystemExit("历史成功 EA 不存在")
    try:
        代理前置探测 = (
            核验离线代理隔离前置(实参.代理地址)
            if 实参.离线代理隔离
            else 核验SOCKS5代理前置(实参.代理地址)
        )
    except ValueError as 异常:
        raise SystemExit(str(异常)) from 异常

    运行根目录 = 工作区 / "runtime" / "单实例历史链兼容性"
    参数哈希 = sha256(计算三风险参数内容(实参.历史参数)).hexdigest()
    参数文件名 = 生成参数文件名(参数哈希, 实参.开始日, 实参.结束日, 实参.超时秒数, 实参.试验标识)
    参数副本 = 运行根目录 / "inputs" / 参数文件名
    已写入参数哈希 = 生成三风险参数副本(实参.历史参数, 参数副本)
    if 已写入参数哈希 != 参数哈希:
        raise RuntimeError("运行参数副本哈希与预览哈希不一致")
    配置 = MT5短窗口探测配置(
        终端目录=实参.tester,
        专家顾问=r"WaiTrade2\WaiTrade_OB",
        参数文件=参数文件名,
        品种="BTCUSDm",
        周期="M1",
        开始日=实参.开始日,
        结束日=实参.结束日,
        初始资金=300,
        杠杆=2000,
        登录账号=实参.登录账号,
        服务器=实参.服务器,
        代理地址=实参.代理地址,
        参数文件路径=参数副本,
    )
    输入 = 创建输入(参数哈希, 配置, 实参.超时秒数, 实参.试验标识, 代理前置探测)
    编排器 = 中央实验编排器(
        追加式账本(运行根目录 / "账本.sqlite"),
        运行根目录 / "暂存",
        运行根目录 / "工件",
    )
    结果 = 编排器.运行(
        输入,
        单实例MT5探测执行器(
            配置,
            实参.wine,
            实参.wine前缀,
            实参.超时秒数,
            实参.mihomo日志,
            离线代理隔离=实参.离线代理隔离,
        ),
    )
    print(json.dumps({"输入": asdict(配置), "实验身份": 结果.实验身份, "状态": 结果.状态, "工件目录": str(结果.工件目录) if 结果.工件目录 else None}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
