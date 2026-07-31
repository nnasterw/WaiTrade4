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
