#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .state import MODULES

ModuleName = Literal["audio", "video", "image", "doc"]

# 每模块并行数取值区间：1-8
ParallelValue = Annotated[int, Field(ge=1, le=8)]


class FileRef(BaseModel):
    """待转换文件引用。"""
    path: str


class CreateTaskRequest(BaseModel):
    """创建任务请求。"""
    module: ModuleName
    files: List[FileRef]
    output_dir: str = ""
    output_format: str
    params: Dict = {}
    overwrite: bool = False


class SettingsModel(BaseModel):
    """全局设置（全量写回）。max_parallel 为按模块字典（每模块 1-8）。"""
    theme: Literal["dark", "light"] = "dark"
    default_output_dir: str = ""
    max_parallel: Dict[ModuleName, ParallelValue] = Field(
        default_factory=lambda: {m: 2 for m in MODULES}
    )
    task_timeout_minutes: int = Field(0, ge=0, le=120)


class OpenPathRequest(BaseModel):
    """打开系统文件管理器请求。"""
    path: str
