from __future__ import annotations

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


def test_只识别FD4精确指向wine前缀的wineserver(tmp_path: Path) -> None:
    前缀 = tmp_path / "受控"
    文本 = f"p10\nf4\nn{前缀}\n".encode()

    assert MT5后台进程._解析Wine服务进程(10, 文本, 前缀) == {10}
    assert MT5后台进程._解析Wine服务进程(10, f"p10\nf4\nn{tmp_path / '其他'}\n".encode(), 前缀) == set()


def test_解码lsof的中文路径转义且拒绝不完整转义(tmp_path: Path) -> None:
    前缀 = tmp_path / "甲-wine前缀"
    转义 = str(前缀).encode().replace(b"\xe7", b"\\xe7").replace(b"\x94", b"\\x94").replace(b"\xb2", b"\\xb2").replace(b"\xe5", b"\\xe5").replace(b"\x89", b"\\x89").replace(b"\x8d", b"\\x8d").replace(b"\xe7", b"\\xe7").replace(b"\xbc", b"\\xbc").replace(b"\x80", b"\\x80")

    assert MT5后台进程._解码lsof路径(转义) == 前缀.resolve()
    assert MT5后台进程._解码lsof路径(b"/tmp/\\xe5\\x") is None
