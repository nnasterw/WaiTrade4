from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from wt4.策略实现 import BTC候选策略目录, 读取BTC候选策略, 部署BTC候选策略


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
