from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from wt4.mt5后台 import MT5后台进程


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


@dataclass(frozen=True)
class BTC候选实际二进制:
    """目标终端受控编译并实际加载的候选二进制身份。"""

    专家顾问: str
    冻结来源标识: str
    源码哈希: dict[str, str]
    二进制路径: Path
    二进制哈希: str


@dataclass(frozen=True)
class MT5候选策略编译配置:
    """受控 MetaEditor 编译所需的单一隔离终端身份。"""

    Wine命令: Path
    Wine前缀: Path
    终端目录: Path
    超时秒数: int = 120


def _禁止直连沙箱配置() -> str:
    return """(version 1)
(deny default)
(allow process*)
(allow file-read*)
(allow file-write*)
(allow sysctl-read)
(allow mach-lookup)
(allow mach-register)
(allow ipc-posix-shm)
(allow ipc-posix-sem)
(allow network-bind (local unix-socket))
(allow network-outbound (remote unix-socket))
(allow network-outbound (remote tcp "localhost:*"))
"""


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


def 绑定BTC候选实际二进制(
    候选: BTC候选策略,
    部署: BTC候选策略部署,
    终端目录: Path,
) -> BTC候选实际二进制:
    """绑定目标终端中已受控生成的 ``.ex5``，拒绝仓库二进制或链接。"""
    if 部署.专家顾问 != 候选.专家顾问 or 部署.源码哈希 != 候选.可执行源码哈希:
        raise ValueError("候选策略部署身份与冻结候选不一致")
    二进制 = 终端目录 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
    if not 二进制.is_file() or 二进制.is_symlink():
        raise ValueError(f"缺少或拒绝链接的实际编译二进制: {二进制}")
    return BTC候选实际二进制(
        专家顾问=候选.专家顾问,
        冻结来源标识=候选.冻结来源标识,
        源码哈希=dict(候选.可执行源码哈希),
        二进制路径=二进制,
        二进制哈希=_哈希(二进制),
    )


def 解析MT5编译日志(日志文本: str, 目标源码: str) -> list[str]:
    """核验 MetaEditor 已为指定源码写出唯一的零错误、零警告结果。"""
    if not 目标源码 or Path(目标源码).is_absolute() or ".." in Path(目标源码).parts:
        raise ValueError("目标源码路径无效")
    规范目标 = 目标源码.replace("/", "\\").lower()
    匹配 = [
        行 for 行 in 日志文本.splitlines()
        if "compile" in 行.lower() and 规范目标 in 行.replace("/", "\\").lower()
    ]
    if not 匹配:
        raise ValueError("编译日志缺少目标源码记录")
    if len(匹配) != 1:
        raise ValueError(f"编译日志包含多条目标源码记录: {len(匹配)}")
    成功 = re.compile(r"\b0\s+errors\s*,\s*0\s+warnings\b", re.IGNORECASE)
    if not 成功.search(匹配[0]):
        raise ValueError(f"目标源码编译结果不是零错误零警告: {匹配[0]}")
    return 匹配


def 受控编译BTC候选策略(
    候选: BTC候选策略,
    部署: BTC候选策略部署,
    配置: MT5候选策略编译配置,
    工件目录: Path,
) -> BTC候选实际二进制:
    """在专属 Wine Prefix 内编译已部署候选并绑定实际 EX5。"""
    Wine前缀 = 配置.Wine前缀.resolve()
    终端目录 = 配置.终端目录.resolve()
    工件目录 = 工件目录.resolve()
    if not 配置.Wine命令.is_file() or not Wine前缀.is_dir() or not 工件目录.is_dir():
        raise ValueError("受控编译的 Wine、前缀或工件目录无效")
    if 配置.超时秒数 <= 0:
        raise ValueError("受控编译超时必须为正")
    try:
        终端目录.relative_to(Wine前缀 / "drive_c")
    except ValueError as 异常:
        raise ValueError("终端目录必须位于受控 Wine Prefix 的 drive_c 内") from 异常
    编辑器 = 终端目录 / "metaeditor64.exe"
    if not 编辑器.is_file():
        raise ValueError(f"MetaEditor 不存在: {编辑器}")
    目标二进制 = 终端目录 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
    if 目标二进制.exists():
        raise ValueError(f"拒绝使用预存在的候选二进制: {目标二进制}")
    源码 = 终端目录 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.mq5"
    if not 源码.is_file() or 源码.is_symlink():
        raise ValueError(f"待编译候选源码不存在或为链接: {源码}")
    编译日志 = 工件目录 / "编译-metaeditor.log"
    if 编译日志.exists():
        raise ValueError("编译日志工件已存在")
    编辑器日志 = 终端目录 / "logs/metaeditor.log"
    编辑器日志运行前 = 编辑器日志.read_bytes() if 编辑器日志.is_file() else None
    沙箱命令 = shutil.which("sandbox-exec")
    if 沙箱命令 is None:
        raise ValueError("缺少 sandbox-exec，无法建立 MetaEditor 禁止直连边界")
    命令 = (
        沙箱命令,
        "-p",
        _禁止直连沙箱配置(),
        str(配置.Wine命令),
        _转为WineC盘路径(编辑器, Wine前缀),
        f"/compile:{_转为WineC盘路径(源码, Wine前缀)}",
        f"/log:{_转为WineZ盘路径(编译日志)}",
    )
    进程 = MT5后台进程.启动(命令, 工件目录, {"WINEPREFIX": str(Wine前缀)}, 工件目录)
    返回码 = 进程.等待(配置.超时秒数)
    if 返回码 is None:
        进程.终止自有进程组()
        进程.等待(5)
        进程.终止自有Wine服务()
        raise RuntimeError("MetaEditor 编译超时")
    进程.终止自有Wine服务()
    if 返回码 != 0:
        raise RuntimeError(f"MetaEditor 返回码 {返回码}")
    if not 编译日志.is_file():
        _封存本次MetaEditor日志(编辑器日志, 编辑器日志运行前, 编译日志)
    if not 编译日志.is_file() or 编译日志.is_symlink():
        raise ValueError("MetaEditor 未产生本次受控编译日志")
    解析MT5编译日志(_读取MT5日志文本(编译日志), r"WaiTrade4\BTC订单块分层风控.mq5")
    return 绑定BTC候选实际二进制(候选, 部署, 终端目录)


def _转为WineC盘路径(路径: Path, Wine前缀: Path) -> str:
    try:
        相对 = 路径.resolve().relative_to((Wine前缀 / "drive_c").resolve())
    except ValueError as 异常:
        raise ValueError(f"路径不在 Wine C 盘内: {路径}") from 异常
    return "C:\\" + str(相对).replace("/", "\\")


def _转为WineZ盘路径(路径: Path) -> str:
    路径 = 路径.resolve()
    return "Z:" + str(路径).replace("/", "\\")


def _读取MT5日志文本(路径: Path) -> str:
    内容 = 路径.read_bytes()
    for 编码 in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return 内容.decode(编码)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码 MT5 编译日志: {路径}")


def _封存本次MetaEditor日志(编辑器日志: Path, 运行前: bytes | None, 工件日志: Path) -> None:
    """仅在 ``/log`` 未落盘时封存终端日志的本轮新增字节。"""
    if not 编辑器日志.is_file() or 编辑器日志.is_symlink():
        return
    运行后 = 编辑器日志.read_bytes()
    if 运行前 is None:
        新增 = 运行后
    elif 运行后.startswith(运行前):
        新增 = 运行后[len(运行前):]
    else:
        return
    if 新增:
        工件日志.parent.mkdir(parents=True, exist_ok=True)
        工件日志.write_bytes(新增)
