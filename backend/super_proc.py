#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超级模式进程池 worker（在独立转换进程内执行）。

设计要点：
  - 本模块只依赖 stdlib + 引擎层（不 import fastapi / tasks / ws），
    因此在 spawn 启动方式下子进程重新导入本模块很快，且可被 pickle
    （run_in_process 是模块级函数，入参均为原生类型/Queue/Event）；
  - 进度通过 multiprocessing.Queue 上行（消息格式 ("progress", task_id, pct)），
    主进程的读取协程负责节流后的 WS 广播；本侧仍做 250ms 节流避免队列打爆；
  - 中止通过 multiprocessing.Event 下行（主进程在取消/超时时 set），
    引擎解码循环内经 abort_cb 轮询感知；
  - 默认值表须与 tasks.DEFAULTS_BY_MODULE 保持一致（避免在 worker 内
    导入 tasks 而拖入 FastAPI）。
"""

import time
from types import SimpleNamespace
from typing import Any, Dict, Tuple

from .engines import audio_engine, video_engine, image_engine, doc_engine

# 引擎函数表（与 tasks.ENGINE_MAP 对应）
ENGINE_MAP = {
    "audio": audio_engine.run,
    "video": video_engine.run,
    "image": image_engine.convert_image,
    "doc": doc_engine.convert_doc,
}

# 各模块参数字段默认值（须与 tasks.DEFAULTS_BY_MODULE 同步）
DEFAULTS_BY_MODULE: Dict[str, Dict[str, Any]] = {
    "audio": {"bitrate": None, "sample_rate": None, "channels": None, "normalize": False},
    "video": {"video_bitrate": None, "audio_bitrate": None, "extract_audio": False, "hardware_accel": None},
    "image": {"quality": 92, "scale_mode": None, "keep_exif": True},
    "doc": {"pdf_dpi": 200, "keep_original": True},
}


def _build_task(module: str, fields: Dict[str, Any]):
    """由可 pickle 的字段字典构建引擎所需的鸭子类型任务对象。"""
    task = SimpleNamespace(
        input_path=fields["input_path"],
        output_path=fields["output_path"],
        output_format=fields["output_format"],
        task_id=fields["task_id"],
    )
    for k, v in fields.get("params", {}).items():
        setattr(task, k, v)
    for k, v in DEFAULTS_BY_MODULE.get(module, {}).items():
        if not hasattr(task, k):
            setattr(task, k, v)
    return task


def run_in_process(module: str, fields: Dict[str, Any],
                   report_q, abort_event) -> Tuple[bool, str]:
    """进程池任务入口：构建 task → 执行引擎 → 返回 (ok, msg)。

    :param module: audio/video/image/doc
    :param fields: {input_path, output_path, output_format, task_id, params}
    :param report_q: multiprocessing.Queue，进度上行
    :param abort_event: multiprocessing.Event，中止下行
    """
    task = _build_task(module, fields)
    task_id = fields["task_id"]

    last_emit = {"t": 0.0}

    def progress_cb(percent: int) -> None:
        pct = max(0, min(100, int(percent)))
        now = time.monotonic()
        if pct == 100 or (now - last_emit["t"]) >= 0.25:
            last_emit["t"] = now
            try:
                report_q.put(("progress", task_id, pct), timeout=1)
            except Exception:
                pass

    def abort_cb() -> bool:
        return abort_event.is_set()

    return ENGINE_MAP[module](task, progress_cb, abort_cb)
