"""backend 包：FormatWarp 的 FastAPI 后端。

本包会把项目根目录加入 sys.path，保证：
  - `from backend.engines import image_engine` 可从任意工作目录执行（引擎独立单测）；
  - 引擎层 `import av_engine`（项目根的 PyAV 引擎）始终可用。
"""
import os
import sys

# backend/__init__.py -> 项目根 = dirname x2
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
