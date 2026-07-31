from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path


@dataclass(frozen=True)
class 测试实例配置:
    名称: str
    终端目录: Path
    数据目录: Path
    Wine前缀: Path
    输出目录: Path
    临时目录: Path
    配置目录: Path
    缓存目录: Path


def 校验实例隔离(实例列表: list[测试实例配置]) -> None:
    if len(实例列表) < 2:
        raise ValueError("并发能力测试至少需要两个实例")
    已见: dict[Path, str] = {}
    for 实例 in 实例列表:
        for 资源 in (
            实例.终端目录,
            实例.数据目录,
            实例.Wine前缀,
            实例.输出目录,
            实例.临时目录,
            实例.配置目录,
            实例.缓存目录,
        ):
            规范路径 = 资源.resolve()
            for 已有路径, 已有实例 in 已见.items():
                # 同一 Wine Prefix 内的终端、数据与缓存目录必然嵌套；
                # 隔离要求针对不同实例，不能把实例内部目录关系误判为共享。
                if 已有实例 != 实例.名称 and _路径重叠(规范路径, 已有路径):
                    raise ValueError(f"实例共享可变目录: {实例.名称} 与 {已有实例} 共享或嵌套 {规范路径}")
            已见[规范路径] = 实例.名称

@dataclass(frozen=True)
class 能力证据:
    单实例重复一致: bool
    数据报告完整: bool
    中断无污染: bool
    实例隔离通过: bool
    两实例逐笔一致: bool
    并发失败率为零且有效提速: bool


def 判定调度方式(证据: 能力证据) -> str:
    if all((
        证据.单实例重复一致,
        证据.数据报告完整,
        证据.中断无污染,
        证据.实例隔离通过,
        证据.两实例逐笔一致,
        证据.并发失败率为零且有效提速,
    )):
        return "两实例并行"
    return "中央单实例串行"


def _路径重叠(左: Path, 右: Path) -> bool:
    return 左 == 右 or 左 in 右.parents or 右 in 左.parents


@dataclass(frozen=True)
class 隔离准备评估:
    可准备: bool
    可用字节: int
    所需字节: int
    原因: str | None


@dataclass(frozen=True)
class 本机MT5盘点:
    终端目录: tuple[Path, ...]
    Wine前缀: Path
    Wine前缀字节: int
    运行中进程数: int
    双实例隔离可准备: 隔离准备评估


def 盘点本机MT5(终端目录: list[Path], Wine前缀: Path, 目标根目录: Path, 额外余量字节: int, 运行中进程数: int = 0) -> 本机MT5盘点:
    """只读取本机状态，为是否允许并发实验提供保守事实输入。"""
    if not Wine前缀.is_dir():
        raise ValueError(f"Wine 前缀不存在: {Wine前缀}")
    不存在终端 = [目录 for 目录 in 终端目录 if not (目录 / "terminal64.exe").is_file()]
    if 不存在终端:
        raise ValueError(f"MT5 终端不存在: {不存在终端}")
    前缀字节 = sum(
        路径.stat().st_size
        for 路径 in Wine前缀.rglob("*")
        if 路径.is_file() and not 路径.is_symlink()
    )
    return 本机MT5盘点(
        tuple(终端目录),
        Wine前缀,
        前缀字节,
        运行中进程数,
        评估隔离准备(2, 前缀字节, 目标根目录, 额外余量字节),
    )


def 评估隔离准备(实例数量: int, 单实例种子字节: int, 目标根目录: Path, 额外余量字节: int) -> 隔离准备评估:
    """仅评估空间，不创建或复制 MT5/Wine 状态。"""
    if 实例数量 < 1 or 单实例种子字节 < 1 or 额外余量字节 < 0:
        raise ValueError("隔离准备参数必须有效")
    可用字节 = shutil.disk_usage(目标根目录).free
    所需字节 = 实例数量 * 单实例种子字节 + 额外余量字节
    if 可用字节 < 所需字节:
        return 隔离准备评估(False, 可用字节, 所需字节, "磁盘空间不足，禁止创建隔离实例")
    return 隔离准备评估(True, 可用字节, 所需字节, None)
