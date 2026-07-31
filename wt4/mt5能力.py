from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class 测试实例配置:
    名称: str
    终端目录: Path
    数据目录: Path
    Wine前缀: Path
    输出目录: Path


def 校验实例隔离(实例列表: list[测试实例配置]) -> None:
    if len(实例列表) < 2:
        raise ValueError("并发能力测试至少需要两个实例")
    已见: dict[Path, str] = {}
    for 实例 in 实例列表:
        for 资源 in (实例.终端目录, 实例.数据目录, 实例.Wine前缀, 实例.输出目录):
            规范路径 = 资源.resolve()
            for 已有路径, 已有实例 in 已见.items():
                if _路径重叠(规范路径, 已有路径):
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
