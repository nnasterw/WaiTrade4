from pathlib import Path

import pytest

from wt4.mt5能力证据 import 能力证据错误, _读取严格SOCKS5配置, 核验能力证据


def test_缺少任一真实结论即拒绝开启并行(tmp_path: Path) -> None:
    缺失 = tmp_path / "missing.json"
    with pytest.raises(能力证据错误, match="结论文件不存在"):
        核验能力证据(缺失, 缺失, 缺失)


def test_空账本不能作为并发能力依据(tmp_path: Path) -> None:
    from wt4.mt5能力证据 import _核验账本

    (tmp_path / "账本.sqlite").touch()
    with pytest.raises(能力证据错误, match="账本缺少"):
        _核验账本(tmp_path, "实验", "已完成")


def test_仅本机实锤的_socks5_枚举可成为能力证据(tmp_path: Path) -> None:
    配置 = tmp_path / "mt5-探测.ini"
    配置.write_text("ProxyEnable=1\nProxyType=1\nProxyAddress=127.0.0.1:7897\n", encoding="utf-8")

    assert _读取严格SOCKS5配置(配置)["ProxyAddress"] == "127.0.0.1:7897"

    # 0 在本机构建的日志中显示为 NONE，不能作为严格 SOCKS5 证据。
    配置.write_text("ProxyEnable=1\nProxyType=0\nProxyAddress=127.0.0.1:7897\n", encoding="utf-8")
    with pytest.raises(能力证据错误, match="严格 SOCKS5"):
        _读取严格SOCKS5配置(配置)
