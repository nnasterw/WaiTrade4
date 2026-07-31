from pathlib import Path

import pytest

from wt4.mt5能力证据 import 能力证据错误, 核验能力证据


def test_缺少任一真实结论即拒绝开启并行(tmp_path: Path) -> None:
    缺失 = tmp_path / "missing.json"
    with pytest.raises(能力证据错误, match="结论文件不存在"):
        核验能力证据(缺失, 缺失, 缺失)


def test_空账本不能作为并发能力依据(tmp_path: Path) -> None:
    from wt4.mt5能力证据 import _核验账本

    (tmp_path / "账本.sqlite").touch()
    with pytest.raises(能力证据错误, match="账本缺少"):
        _核验账本(tmp_path, "实验", "已完成")
