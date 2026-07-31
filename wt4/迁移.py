from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import shutil


_INCLUDE = re.compile(r'^\s*#include\s+[<"]WaiTrade2/(.+?)[>"]')


@dataclass(frozen=True)
class 冻结迁移结果:
    文件哈希: dict[str, str]
    来源: str


def _哈希(路径: Path) -> str:
    return sha256(路径.read_bytes()).hexdigest()


def 收集最小依赖闭包(旧mql根目录: Path, 入口相对路径: Path) -> list[Path]:
    已访问: set[Path] = set()

    def 遍历(相对路径: Path) -> None:
        if 相对路径 in 已访问:
            return
        文件 = 旧mql根目录 / 相对路径
        if not 文件.is_file():
            raise ValueError(f"迁移依赖不存在: {相对路径}")
        已访问.add(相对路径)
        for 行 in 文件.read_text(encoding="utf-8-sig", errors="strict").splitlines():
            匹配 = _INCLUDE.match(行)
            if 匹配:
                遍历(Path("Include") / "WaiTrade2" / 匹配.group(1))

    遍历(入口相对路径)
    return sorted(已访问)


def 冻结迁移(旧mql根目录: Path, 入口相对路径: Path, 参数文件: Path, 目标目录: Path, 来源标识: str) -> 冻结迁移结果:
    if 目标目录.exists():
        raise ValueError(f"冻结迁移目标已存在，拒绝覆盖: {目标目录}")
    依赖 = 收集最小依赖闭包(旧mql根目录, 入口相对路径)
    目标目录.mkdir(parents=True)
    文件哈希: dict[str, str] = {}
    for 相对路径 in [*依赖, Path("参数") / 参数文件.name]:
        来源文件 = 参数文件 if 相对路径.parts[0] == "参数" else 旧mql根目录 / 相对路径
        目标文件 = 目标目录 / 相对路径
        目标文件.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(来源文件, 目标文件)
        文件哈希[str(相对路径)] = _哈希(目标文件)
    (目标目录 / "来源.json").write_text(
        json.dumps(
            {
                "来源标识": 来源标识,
                "入口相对路径": str(入口相对路径),
                "参数原始路径": str(参数文件),
                "文件哈希": 文件哈希,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 冻结迁移结果(文件哈希, 来源标识)
