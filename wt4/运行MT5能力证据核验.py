from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from wt4.mt5能力证据 import 核验能力证据
from wt4.账本 import 追加式账本


工作区 = Path(__file__).resolve().parent.parent


def main() -> None:
    参数 = argparse.ArgumentParser(description="重新核验真实 MT5 工件后决定是否开放两实例并行")
    参数.add_argument("--重复结论", type=Path, default=工作区 / "runtime/MT5重复能力/工件/7b7f0b1d832f40d9/重复结论.json")
    参数.add_argument("--并发结论", type=Path, default=工作区 / "runtime/MT5并发能力/工件/45a620040e284220/并发结论.json")
    参数.add_argument("--中断结论", type=Path, default=工作区 / "runtime/MT5并发能力/中断工件/506203df42ee4ca9/中断结论.json")
    实参 = 参数.parse_args()
    标识 = uuid4().hex[:16]
    根目录 = 工作区 / "runtime/MT5能力核验/工件" / 标识
    根目录.mkdir(parents=True)
    账本 = 追加式账本(根目录 / "账本.sqlite")
    账本.追加(标识, "已创建", {"重复结论": str(实参.重复结论), "并发结论": str(实参.并发结论), "中断结论": str(实参.中断结论)})
    try:
        结果 = 核验能力证据(实参.重复结论, 实参.并发结论, 实参.中断结论).可序列化()
    except Exception as 异常:
        账本.追加(标识, "核验失败", {"原因": str(异常)})
        raise
    (根目录 / "调度结论.json").write_text(json.dumps(结果, ensure_ascii=False, indent=2), encoding="utf-8")
    账本.追加(标识, "已完成", 结果)
    print(json.dumps({"实验标识": 标识, **结果}, ensure_ascii=False))


if __name__ == "__main__":
    main()
