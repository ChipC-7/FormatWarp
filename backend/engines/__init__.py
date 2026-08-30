"""引擎层包：四个转换引擎（audio/video/image/doc），全部零 Qt / 零 FastAPI 依赖。

本包的 __init__ 会把项目根目录加入 sys.path，保证 `import av_engine` 可用，
引擎模块可脱离 Web 层独立导入与单测。
"""
import os
import sys

# backend/engines/__init__.py -> 项目根 = dirname x3
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
