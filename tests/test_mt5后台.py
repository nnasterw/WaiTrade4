from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from wt4.mt5后台 import MT5后台进程


def test_后台进程可观测并保留标准输出(tmp_path: Path) -> None:
    进程 = MT5后台进程.启动(
        (sys.executable, "-c", "print('后台完成')"),
        tmp_path,
        dict(os.environ),
        tmp_path,
    )

    运行中或已退出 = 进程.快照()
    assert 运行中或已退出.进程号 > 0
    assert 进程.等待(5) == 0
    快照 = 进程.快照()
    assert 快照.状态 == "已退出"
    assert 进程.输出文本() == ("后台完成\n", "")


def test_超时后只终止自身进程组(tmp_path: Path) -> None:
    进程 = MT5后台进程.启动(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        tmp_path,
        dict(os.environ),
        tmp_path,
    )

    assert 进程.等待(1) is None
    进程.终止自有进程组()
    返回码 = 进程.等待(5)

    assert 返回码 is not None
    assert 进程.快照().状态 == "已退出"


def test_归属记录仅在命令仍携带实验身份时受限回收进程组(tmp_path: Path) -> None:
    实验目录 = tmp_path / ("a" * 64)
    实验目录.mkdir()
    进程 = MT5后台进程.启动(
        (
            sys.executable,
            "-c",
            f"import time; 受控实验={str(实验目录)!r}; time.sleep(30)",
        ),
        实验目录,
        dict(os.environ),
        实验目录,
    )

    归属记录 = 实验目录 / "后台-归属.json"
    assert 归属记录.is_file()
    assert MT5后台进程.回收遗留自有进程组(归属记录) is True
    assert 进程.等待(5) is not None
    assert "已受限回收" in 归属记录.read_text(encoding="utf-8")


def test_归属记录验证片段不匹配时绝不回收进程(tmp_path: Path) -> None:
    实验目录 = tmp_path / ("b" * 64)
    实验目录.mkdir()
    进程 = MT5后台进程.启动(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        实验目录,
        dict(os.environ),
        实验目录,
    )

    归属记录 = 实验目录 / "后台-归属.json"
    assert MT5后台进程.回收遗留自有进程组(归属记录) is False
    assert 进程.快照().状态 == "运行中"
    进程.终止自有进程组()
    assert 进程.等待(5) is not None


def test_归属记录实验目录不匹配时绝不回收进程(tmp_path: Path) -> None:
    实验目录 = tmp_path / ("c" * 64)
    实验目录.mkdir()
    进程 = MT5后台进程.启动(
        (sys.executable, "-c", f"import time; 受控实验={str(实验目录)!r}; time.sleep(30)"),
        实验目录,
        dict(os.environ),
        实验目录,
    )
    归属记录 = 实验目录 / "后台-归属.json"
    内容 = json.loads(归属记录.read_text(encoding="utf-8"))
    内容["实验目录"] = str(tmp_path / "伪造")
    归属记录.write_text(json.dumps(内容), encoding="utf-8")

    assert MT5后台进程.回收遗留自有进程组(归属记录) is False
    进程.终止自有进程组()
    assert 进程.等待(5) is not None


def test_只识别FD4精确指向wine前缀的wineserver(tmp_path: Path) -> None:
    前缀 = tmp_path / "受控"
    文本 = f"p10\nf4\nn{前缀}\n".encode()

    assert MT5后台进程._解析Wine服务进程(10, 文本, 前缀) == {10}
    assert MT5后台进程._解析Wine服务进程(10, f"p10\nf4\nn{tmp_path / '其他'}\n".encode(), 前缀) == set()


def test_认领时排除启动前已存在的同前缀wine服务(tmp_path: Path, monkeypatch) -> None:
    进程 = MT5后台进程.__new__(MT5后台进程)
    进程._Wine前缀 = tmp_path / "受控"
    进程._启动前Wine服务进程号 = {10}
    进程._自有Wine服务进程号 = set()
    monkeypatch.setattr(进程, "_当前自有Wine服务", lambda: {10, 11})

    assert 进程.认领自有Wine服务() == (11,)


def test_解码lsof的中文路径转义且拒绝不完整转义(tmp_path: Path) -> None:
    前缀 = tmp_path / "甲-wine前缀"
    转义 = str(前缀).encode().replace(b"\xe7", b"\\xe7").replace(b"\x94", b"\\x94").replace(b"\xb2", b"\\xb2").replace(b"\xe5", b"\\xe5").replace(b"\x89", b"\\x89").replace(b"\x8d", b"\\x8d").replace(b"\xe7", b"\\xe7").replace(b"\xbc", b"\\xbc").replace(b"\x80", b"\\x80")

    assert MT5后台进程._解码lsof路径(转义) == 前缀.resolve()
    assert MT5后台进程._解码lsof路径(b"/tmp/\\xe5\\x") is None
