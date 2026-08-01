from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil


工作区 = Path(__file__).resolve().parent.parent
BTC候选策略目录 = 工作区 / "策略实现/BTC-M5-订单块-分层风控"
_入口相对路径 = Path("Experts/WaiTrade4/BTC订单块分层风控.mq5")
_专家顾问 = r"WaiTrade4\BTC订单块分层风控"
_可执行包含 = re.compile(r'^\s*#include\s+[<"](.+?)[>"]')


@dataclass(frozen=True)
class BTC候选策略:
    """已冻结来源、待编译的 BTC 单策略实现。

    仓库中的 ``.ex5`` 只可作为人工编译留痕，绝不可替代待部署终端中
    实际加载的二进制哈希。
    """

    根目录: Path
    冻结来源标识: str
    冻结文件哈希: dict[str, str]
    可执行源码哈希: dict[str, str]
    专家顾问: str = _专家顾问
    二进制哈希: None = None


@dataclass(frozen=True)
class BTC候选策略部署:
    专家顾问: str
    源码哈希: dict[str, str]
    已部署文件: tuple[Path, ...]


def _哈希(路径: Path) -> str:
    return sha256(路径.read_bytes()).hexdigest()


def _读取冻结清单(冻结目录: Path) -> tuple[str, dict[str, str]]:
    清单路径 = 冻结目录 / "来源.json"
    try:
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
        来源标识 = 清单["来源标识"]
        文件哈希 = 清单["文件哈希"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as 异常:
        raise ValueError(f"冻结来源清单无效: {清单路径}") from 异常
    if not isinstance(来源标识, str) or not 来源标识 or not isinstance(文件哈希, dict):
        raise ValueError(f"冻结来源清单字段无效: {清单路径}")
    for 相对路径, 预期哈希 in 文件哈希.items():
        if not isinstance(相对路径, str) or not isinstance(预期哈希, str) or not re.fullmatch(r"[0-9a-f]{64}", 预期哈希):
            raise ValueError(f"冻结来源清单包含无效哈希: {清单路径}")
        路径 = Path(相对路径)
        if 路径.is_absolute() or ".." in 路径.parts:
            raise ValueError(f"冻结来源清单路径越界: {相对路径}")
        文件 = 冻结目录 / 路径
        if not 文件.is_file() or _哈希(文件) != 预期哈希:
            raise ValueError(f"冻结文件哈希不一致: {相对路径}")
    return 来源标识, dict(文件哈希)


def _收集可执行源码闭包(可执行目录: Path) -> tuple[Path, ...]:
    已访问: set[Path] = set()

    def 遍历(相对路径: Path) -> None:
        if 相对路径 in 已访问:
            return
        if 相对路径.is_absolute() or ".." in 相对路径.parts:
            raise ValueError(f"可执行策略源码路径越界: {相对路径}")
        文件 = 可执行目录 / 相对路径
        if not 文件.is_file():
            raise ValueError(f"可执行策略源码缺失: {相对路径}")
        已访问.add(相对路径)
        for 行 in 文件.read_text(encoding="utf-8-sig", errors="strict").splitlines():
            匹配 = _可执行包含.match(行)
            if 匹配:
                引用 = Path(匹配.group(1))
                if 引用.is_absolute():
                    raise ValueError(f"可执行策略引用路径越界: {引用}")
                if 引用.parts and 引用.parts[0] == "Include":
                    依赖 = 引用
                elif 引用.parts and 引用.parts[0] == "WaiTrade2":
                    依赖 = Path("Include") / 引用
                else:
                    try:
                        依赖 = (文件.parent / 引用).resolve().relative_to(可执行目录.resolve())
                    except ValueError as 异常:
                        raise ValueError(f"可执行策略引用路径越界: {引用}") from 异常
                遍历(依赖)

    遍历(_入口相对路径)
    return tuple(sorted(已访问))


def 读取BTC候选策略(根目录: Path = BTC候选策略目录) -> BTC候选策略:
    根目录 = 根目录.resolve()
    冻结来源标识, 冻结文件哈希 = _读取冻结清单(根目录 / "冻结迁移")
    可执行目录 = 根目录 / "可执行实现"
    可执行源码 = _收集可执行源码闭包(可执行目录)
    return BTC候选策略(
        根目录=根目录,
        冻结来源标识=冻结来源标识,
        冻结文件哈希=冻结文件哈希,
        可执行源码哈希={str(路径): _哈希(可执行目录 / 路径) for 路径 in 可执行源码},
    )


def 部署BTC候选策略(候选: BTC候选策略, 终端目录: Path) -> BTC候选策略部署:
    """将已核验的 MQL 源码闭包复制到一个空的目标 Expert 路径。

    此函数不复制仓库内 ``.ex5``：正式实验只能绑定该终端受控编译后实际
    加载的二进制；调用方还必须单独核验其哈希。
    """
    可执行目录 = 候选.根目录 / "可执行实现"
    mql目录 = 终端目录 / "MQL5"
    文件组: list[tuple[Path, Path, str]] = []
    for 文本路径, 预期哈希 in sorted(候选.可执行源码哈希.items()):
        相对路径 = Path(文本路径)
        来源 = 可执行目录 / 相对路径
        目标 = mql目录 / 相对路径
        if not 来源.is_file() or _哈希(来源) != 预期哈希:
            raise ValueError(f"可执行策略源码哈希不一致: {文本路径}")
        if 目标.exists():
            raise ValueError(f"拒绝覆盖终端既有候选策略文件: {目标}")
        文件组.append((来源, 目标, 预期哈希))

    已部署: list[Path] = []
    for 来源, 目标, 预期哈希 in 文件组:
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(来源, 目标)
        if _哈希(目标) != 预期哈希:
            raise RuntimeError(f"候选策略部署哈希不一致: {目标}")
        已部署.append(目标)
    return BTC候选策略部署(候选.专家顾问, dict(候选.可执行源码哈希), tuple(已部署))
