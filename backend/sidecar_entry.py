#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sidecar 打包入口（PyInstaller / Nuitka 的 --entry 指向本文件）。

不能直接把 backend/app.py 作为打包入口：它使用 `from . import ...` 相对导入，
冻结环境下以 `__main__` 脚本运行时没有父包，会抛
`ImportError: attempted relative import with no known parent package`。
本文件用绝对导入 `from backend.app import main` 绕开该限制。

打包工具会通过 --paths 项目根收集 backend 包与顶层 av_engine，
产物运行即等价于 `python -m backend.app`。
"""

import sys
import os

# 项目根 = 本文件所在目录的上级（backend/..）：
#  - dev 运行：即仓库根，`import backend.app` 可用；
#  - 冻结产物：即 PyInstaller _MEIPASS / Nuitka 解包目录，backend 包同样在根。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.app import main  # noqa: E402

if __name__ == "__main__":
    main()
