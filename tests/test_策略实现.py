from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from wt4.策略实现 import (
    BTC候选策略目录,
    读取BTC候选策略,
    部署BTC候选策略,
    绑定BTC候选实际二进制,
    解析MT5编译日志,
    MT5候选策略编译配置,
    受控编译BTC候选策略,
    _封存本次MetaEditor日志,
)


def _写(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


def _构造候选(root: Path) -> Path:
    冻结 = root / "冻结迁移"
    _写(冻结 / "Experts/WaiTrade2/WaiTrade_OB.mq5", "// frozen\n")
    _写(冻结 / "参数/V11-BTC-M5-R21.set", "InpRiskPercent=3.0\n")
    哈希 = {
        "Experts/WaiTrade2/WaiTrade_OB.mq5": sha256(b"// frozen\n").hexdigest(),
        "参数/V11-BTC-M5-R21.set": sha256(b"InpRiskPercent=3.0\n").hexdigest(),
    }
    _写(
        冻结 / "来源.json",
        '{"来源标识": "WaiTrade2:commit:r21", "文件哈希": ' + str(哈希).replace("'", '"') + "}",
    )
    可执行 = root / "可执行实现"
    _写(可执行 / "Experts/WaiTrade4/BTC订单块分层风控.mq5", '#include "../../Include/WaiTrade2/依赖.mqh"\n')
    _写(可执行 / "Include/WaiTrade2/依赖.mqh", "// dependency\n")
    return root


def test_读取候选绑定冻结来源和可执行源码闭包(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))

    assert 候选.专家顾问 == r"WaiTrade4\BTC订单块分层风控"
    assert 候选.冻结来源标识 == "WaiTrade2:commit:r21"
    assert set(候选.可执行源码哈希) == {
        "Experts/WaiTrade4/BTC订单块分层风控.mq5",
        "Include/WaiTrade2/依赖.mqh",
    }


def test_读取候选拒绝被冻结清单篡改的来源(tmp_path: Path) -> None:
    根目录 = _构造候选(tmp_path / "候选")
    _写(根目录 / "冻结迁移/参数/V11-BTC-M5-R21.set", "tampered\n")

    with pytest.raises(ValueError, match="冻结文件哈希不一致"):
        读取BTC候选策略(根目录)


def test_部署仅复制已核验源码并拒绝覆盖既有专家(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))
    终端 = tmp_path / "终端"

    部署 = 部署BTC候选策略(候选, 终端)

    assert 部署.专家顾问 == r"WaiTrade4\BTC订单块分层风控"
    assert (终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.mq5").is_file()
    assert (终端 / "MQL5/Include/WaiTrade2/依赖.mqh").is_file()
    assert not (终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5").exists()

    with pytest.raises(ValueError, match="拒绝覆盖"):
        部署BTC候选策略(候选, 终端)


def test_仓库候选可被读取且不将仓库内ex5充作验收二进制() -> None:
    候选 = 读取BTC候选策略(BTC候选策略目录)

    assert 候选.二进制哈希 is None
    assert "Experts/WaiTrade4/BTC订单块分层风控.mq5" in 候选.可执行源码哈希

def test_部署预检全部目标以避免部分复制(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))
    终端 = tmp_path / "终端"
    已存在依赖 = 终端 / "MQL5/Include/WaiTrade2/依赖.mqh"
    _写(已存在依赖, "existing\n")

    with pytest.raises(ValueError, match="拒绝覆盖"):
        部署BTC候选策略(候选, 终端)

    assert not (终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.mq5").exists()

def test_读取候选递归收集相对路径的间接依赖(tmp_path: Path) -> None:
    根目录 = _构造候选(tmp_path / "候选")
    _写(根目录 / "可执行实现/Include/WaiTrade2/依赖.mqh", '#include "间接.mqh"\n')
    _写(根目录 / "可执行实现/Include/WaiTrade2/间接.mqh", "// indirect\n")

    候选 = 读取BTC候选策略(根目录)

    assert "Include/WaiTrade2/间接.mqh" in 候选.可执行源码哈希


def test_绑定实际编译二进制要求目标ex5且保留来源和源码哈希(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))
    终端 = tmp_path / "终端"
    部署 = 部署BTC候选策略(候选, 终端)
    ex5 = 终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
    _写(ex5, b"actual-ex5")

    绑定 = 绑定BTC候选实际二进制(候选, 部署, 终端)

    assert 绑定.冻结来源标识 == "WaiTrade2:commit:r21"
    assert 绑定.源码哈希 == 候选.可执行源码哈希
    assert 绑定.二进制哈希 == sha256(b"actual-ex5").hexdigest()


def test_绑定实际二进制拒绝缺失或链接的ex5(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))
    终端 = tmp_path / "终端"
    部署 = 部署BTC候选策略(候选, 终端)

    with pytest.raises(ValueError, match="实际编译二进制"):
        绑定BTC候选实际二进制(候选, 部署, 终端)

    ex5 = 终端 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
    原件 = tmp_path / "other.ex5"
    _写(原件, b"other")
    ex5.symlink_to(原件)

    with pytest.raises(ValueError, match="实际编译二进制"):
        绑定BTC候选实际二进制(候选, 部署, 终端)


def test_解析MT5编译日志只接受目标源码的零错误零警告记录() -> None:
    日志 = (
        "0\t2026.08.01 10:00:00.000\tCompile\t"
        r"C:\Program Files\MetaTrader 5\MQL5\Experts\WaiTrade4\BTC订单块分层风控.mq5"
        " - 0 errors, 0 warnings, 4000 ms elapsed\n"
    )

    assert len(解析MT5编译日志(日志, r"WaiTrade4\BTC订单块分层风控.mq5")) == 1


@pytest.mark.parametrize("日志,期望", [
    ("Compile\tC:\\WaiTrade4\\BTC订单块分层风控.mq5 - 1 errors, 0 warnings\n", "零错误零警告"),
    ("Compile\tC:\\other.mq5 - 0 errors, 0 warnings\n", "目标源码"),
    (
        "Compile\tC:\\WaiTrade4\\BTC订单块分层风控.mq5 - 0 errors, 0 warnings\n"
        "Compile\tC:\\WaiTrade4\\BTC订单块分层风控.mq5 - 0 errors, 0 warnings\n",
        "多条目标源码记录",
    ),
    ("", "目标源码"),
])
def test_解析MT5编译日志拒绝非目标或失败记录(日志: str, 期望: str) -> None:
    with pytest.raises(ValueError, match=期望):
        解析MT5编译日志(日志, r"WaiTrade4\BTC订单块分层风控.mq5")


def test_受控编译拒绝终端不属于声明wine前缀且不启动进程(tmp_path: Path) -> None:
    候选 = 读取BTC候选策略(_构造候选(tmp_path / "候选"))
    前缀 = tmp_path / "prefix"
    前缀.mkdir()
    wine = tmp_path / "wine"
    _写(wine, "#!/bin/sh\nexit 99\n")
    wine.chmod(0o755)
    终端 = tmp_path / "外部终端"
    部署 = 部署BTC候选策略(候选, 终端)
    _写(终端 / "metaeditor64.exe", b"editor")
    工件 = tmp_path / "工件"
    工件.mkdir()

    with pytest.raises(ValueError, match="Wine Prefix"):
        受控编译BTC候选策略(
            候选, 部署, MT5候选策略编译配置(wine, 前缀, 终端), 工件
        )

    assert not (工件 / "后台-stdout.txt").exists()


def test_候选编译沙箱仅允许wine本地套接字与环回网络() -> None:
    from wt4.策略实现 import _禁止直连沙箱配置

    配置 = _禁止直连沙箱配置()

    assert "(deny default)" in 配置
    assert "(allow mach-register)" in 配置
    assert "(allow ipc-posix-shm)" in 配置
    assert "(allow ipc-posix-sem)" in 配置
    assert "(allow network-bind (local unix-socket))" in 配置
    assert "(allow network-outbound (remote unix-socket))" in 配置
    assert '(allow network-outbound (remote tcp "localhost:*"))' in 配置


def test_封存MetaEditor日志仅接受运行后追加内容(tmp_path: Path) -> None:
    编辑器日志 = tmp_path / "logs/metaeditor.log"
    工件日志 = tmp_path / "工件/编译.log"
    _写(编辑器日志, b"old\nnew\n")

    _封存本次MetaEditor日志(编辑器日志, b"old\n", 工件日志)

    assert 工件日志.read_bytes() == b"new\n"


def test_封存MetaEditor日志拒绝被重写的旧日志(tmp_path: Path) -> None:
    编辑器日志 = tmp_path / "logs/metaeditor.log"
    工件日志 = tmp_path / "工件/编译.log"
    _写(编辑器日志, b"rewritten\n")

    _封存本次MetaEditor日志(编辑器日志, b"old\n", 工件日志)

    assert not 工件日志.exists()
