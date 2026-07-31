from __future__ import annotations

from hashlib import sha256
import json
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
    if not 预期哈希:
        raise ValueError("预期工件不能为空")
    预期路径: set[Path] = set()
    for 相对路径, 期望值 in 预期哈希.items():
        路径 = Path(相对路径)
        if 路径.is_absolute() or ".." in 路径.parts:
            raise ValueError(f"工件路径必须位于暂存目录内: {相对路径}")
        文件 = 暂存目录 / 路径
        if not 文件.is_file():
            raise ValueError(f"缺少工件: {相对路径}")
        if 文件.is_symlink():
            raise ValueError(f"工件不能是符号链接: {相对路径}")
        if _文件哈希(文件) != 期望值:
            raise ValueError(f"工件哈希不匹配: {相对路径}")
        预期路径.add(路径)

    实际路径 = {文件.relative_to(暂存目录) for 文件 in 暂存目录.rglob("*") if 文件.is_file()}
    if 实际路径 != 预期路径:
        未声明 = sorted(str(路径) for 路径 in 实际路径 - 预期路径)
        缺失 = sorted(str(路径) for 路径 in 预期路径 - 实际路径)
        raise ValueError(f"暂存工件与清单不一致: 未声明={未声明}, 缺失={缺失}")

    清单 = 暂存目录 / "工件清单.json"
    if 清单.exists():
        raise ValueError("执行器不得预写工件清单.json")
    清单.write_text(
        json.dumps({"版本": 1, "工件哈希": dict(sorted(预期哈希.items()))}, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

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
