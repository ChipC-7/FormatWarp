#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置资源解析：定位随应用分发的外部二进制（如 pandoc）。

查找优先级：
  1. 环境变量（FORMATWARP_PANDOC）
  2. 内置资源目录：
     - 冻结打包：PyInstaller 的 sys._MEIPASS、可执行文件同级 resources；
       Nuitka 的 __compiled__ 同级 resources
     - 开发运行：本仓库 backend/resources
  3. 系统 PATH 兜底
"""

import os
import shutil
import sys
from typing import List, Optional


def _candidate_dirs() -> List[str]:
    """返回内置 resources/pandoc 所有可能的父目录。"""
    dirs: List[str] = []

    # PyInstaller：onefile 解包目录 / onedir
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(os.path.join(meipass, "resources", "pandoc"))

    # 冻结后：可执行文件同级 resources（Nuitka onefile/onedir 及拷贝场景）
    if getattr(sys, "frozen", False) or hasattr(sys, "__compiled__"):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        dirs.append(os.path.join(exe_dir, "resources", "pandoc"))

    # 开发/源码运行：backend/resources/pandoc
    here = os.path.dirname(os.path.abspath(__file__))
    dirs.append(os.path.join(here, "resources", "pandoc"))
    return dirs


def _exe_candidates(name: str) -> List[str]:
    exe = f"{name}.exe" if sys.platform.startswith("win") else name
    return [os.path.join(d, exe) for d in _candidate_dirs()]


def find_bundled(name: str, env_var: Optional[str] = None) -> Optional[str]:
    """定位内置或系统中的二进制；找不到返回 None。"""
    # 1. 环境变量覆盖
    if env_var:
        env_path = os.environ.get(env_var)
        if env_path and os.path.isfile(env_path):
            return env_path

    # 2. 内置资源
    for cand in _exe_candidates(name):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    # 3. PATH 兜底（允许使用用户自装版本）
    return shutil.which(name)
