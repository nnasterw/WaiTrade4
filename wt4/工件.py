from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil


def _文件哈希(路径: Path) -> str:
    摘要 = sha256()
    with 路径.open("rb") as 文件:
        for 块 in iter(lambda: 文件.read(1024 * 1024), b""):
            摘要.update(块)
    return 摘要.hexdigest()


def 归档工件(暂存目录: Path, 工件根目录: Path, 实验身份: str, 预期哈希: dict[str, str]) -> Path:
    if not 暂存目录.is_dir():
        raise ValueError(f"暂存目录不存在: {暂存目录}")
    for 相对路径, 期望值 in 预期哈希.items():
        文件 = 暂存目录 / 相对路径
        if not 文件.is_file():
            raise ValueError(f"缺少工件: {相对路径}")
        if _文件哈希(文件) != 期望值:
            raise ValueError(f"工件哈希不匹配: {相对路径}")

    工件根目录.mkdir(parents=True, exist_ok=True)
    目标目录 = 工件根目录 / 实验身份
    if 目标目录.exists():
        raise ValueError(f"实验工件已存在，拒绝覆盖: {实验身份}")
    中间目录 = 工件根目录 / f".{实验身份}.归档中"
    if 中间目录.exists():
        raise ValueError(f"发现未清理的归档中目录: {中间目录}")
    shutil.copytree(暂存目录, 中间目录)
    os.replace(中间目录, 目标目录)
    shutil.rmtree(暂存目录)
    return 目标目录
