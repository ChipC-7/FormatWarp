#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频转换引擎：薄封装 av_engine.convert_video（零 Qt / 零 FastAPI 依赖）。

预设表从旧 video_converter.py 复制（自包含，避免引入 Qt 依赖）。
格式别名重命名（m2ts→.ts 等）在 Worker 层处理，这里也保留等价逻辑。
"""

import copy
import os
from typing import Callable, Tuple

import av_engine

# =====================================================================
# 格式预设表（沿用旧 video_converter.py）
# =====================================================================

SUPPORTED_VIDEO_FORMATS = {
    "mp4":  {"ext": ".mp4",  "desc": "MP4 (H.264 + AAC)"},
    "mkv":  {"ext": ".mkv",  "desc": "MKV (Matroska 万能容器)"},
    "avi":  {"ext": ".avi",  "desc": "AVI (Audio Video Interleave)"},
    "mov":  {"ext": ".mov",  "desc": "MOV (Apple QuickTime)"},
    "webm": {"ext": ".webm", "desc": "WebM (VP9 + Opus)"},
    "flv":  {"ext": ".flv",  "desc": "FLV (Flash Video)"},
    "ts":   {"ext": ".ts",   "desc": "TS (MPEG Transport Stream)"},
    "wmv":  {"ext": ".wmv",  "desc": "WMV (Windows Media Video)"},
    "mpg":  {"ext": ".mpg",  "desc": "MPG (MPEG-1/2 视频)"},
    "m4v":  {"ext": ".m4v",  "desc": "M4V (iTunes 视频)"},
    "3gp":  {"ext": ".3gp",  "desc": "3GP (移动端视频)"},
    "ogv":  {"ext": ".ogv",  "desc": "OGV (Ogg Theora 视频)"},
    "vob":  {"ext": ".vob",  "desc": "VOB (DVD 视频对象)"},
    "asf":  {"ext": ".asf",  "desc": "ASF (Advanced Systems Format)"},
    "m2ts": {"ext": ".m2ts", "desc": "M2TS (蓝光 MPEG-2 TS)"},
    "gif":  {"ext": ".gif",  "desc": "GIF (视频转动图 ⚡)"},
}

INPUT_VIDEO_FORMATS = [
    "mp4", "mkv", "avi", "mov", "webm", "flv", "ts", "wmv", "mpg", "mpeg", "m4v",
    "3gp", "ogv", "vob", "asf", "m2ts", "rmvb", "rm", "divx", "f4v",
]

VIDEO_BITRATE_PRESETS = {
    "自动 (CRF)": None,
    "低画质 (1M)": "1M",
    "中等画质 (3M)": "3M",
    "高画质 (6M)": "6M",
    "超高画质 (10M)": "10M",
    "极高画质 (20M)": "20M",
}

EXTRACT_AUDIO_FORMATS = {
    "mp3":  {"ext": ".mp3",  "desc": "MP3 — 有损压缩 (最通用)"},
    "wav":  {"ext": ".wav",  "desc": "WAV — 无损未压缩"},
    "flac": {"ext": ".flac", "desc": "FLAC — 无损压缩"},
    "aac":  {"ext": ".aac",  "desc": "AAC — 高级音频编码"},
    "ogg":  {"ext": ".ogg",  "desc": "OGG Vorbis — 开源有损"},
    "opus": {"ext": ".opus", "desc": "OPUS — 低延迟高压缩"},
    "m4a":  {"ext": ".m4a",  "desc": "M4A — Apple AAC 容器"},
    "ac3":  {"ext": ".ac3",  "desc": "AC3 — 杜比数字环绕声"},
}

AUDIO_BITRATE_PRESETS = {
    "自动": None, "128k": "128k", "192k": "192k", "256k": "256k", "320k": "320k",
}

VIDEO_FORMAT_ALIAS_TO_REAL_EXT = {
    "m2ts": ".ts",
    "m4v": ".mp4",
    "ogv": ".ogg",
    "wmv": ".asf",
    "vob": ".mpg",
}

EXTRACT_AUDIO_FORMAT_ALIAS_TO_REAL_EXT = {
    "aac": ".aac",
    "m4a": ".m4a",
}

# 硬件加速选项（供前端下拉）
HARDWARE_ACCEL_PRESETS = [
    {"label": "自动选择 (推荐)", "value": None},
    {"label": "CPU 软件编码", "value": "cpu"},
    {"label": "NVIDIA NVENC", "value": "nvenc"},
    {"label": "Intel QSV", "value": "qsv"},
    {"label": "AMD AMF", "value": "amf"},
    {"label": "Apple VideoToolbox", "value": "vtb"},
]


# =====================================================================
# 引擎接口
# =====================================================================

def run(task, progress_cb: Callable[[int], None],
        should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """执行视频转换（含格式别名重命名逻辑）。

    :param task: 鸭子类型任务对象，需含 input_path / output_path / output_format，
                 另有 video_bitrate / audio_bitrate / extract_audio / hardware_accel。
    :return: (成功与否, 消息)
    """
    alias_table = EXTRACT_AUDIO_FORMAT_ALIAS_TO_REAL_EXT if getattr(task, "extract_audio", False) \
        else VIDEO_FORMAT_ALIAS_TO_REAL_EXT
    real_ext = alias_table.get(task.output_format, "")
    target = task.output_path
    effective_task = task
    temp_path = None

    # 格式别名重命名（如 m2ts→.ts）：先写真实扩展名临时文件，成功后 rename
    if real_ext and not target.lower().endswith(real_ext.lower()):
        temp_path = os.path.splitext(target)[0] + real_ext
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        effective_task = copy.copy(task)
        effective_task.output_path = temp_path

    ok, msg = av_engine.convert_video(effective_task, progress_cb, should_abort_cb)
    if not ok:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return ok, msg

    if temp_path is not None:
        try:
            if os.path.exists(target):
                os.remove(target)
            os.replace(temp_path, target)
        except OSError as e:
            return False, f"转换成功，但重命名失败: {temp_path} → {target}: {e}"
    return True, msg


def engine_info() -> Tuple[bool, str]:
    """探测 PyAV 引擎可用性。"""
    return av_engine.check_av_available()


# =====================================================================
# 格式信息（供 REST /api/formats）
# =====================================================================

def formats_info() -> dict:
    """返回视频模块的格式与预设信息。"""
    outputs = []
    for key, info in SUPPORTED_VIDEO_FORMATS.items():
        outputs.append({"key": key, "desc": info["desc"], "ext": info["ext"], "extract_audio": False})
    for key, info in EXTRACT_AUDIO_FORMATS.items():
        outputs.append({"key": key, "desc": info["desc"], "ext": info["ext"], "extract_audio": True})
    return {
        "inputs": list(INPUT_VIDEO_FORMATS),
        "outputs": outputs,
        "presets": {
            "video_bitrate": [{"label": label, "value": value} for label, value in VIDEO_BITRATE_PRESETS.items()],
            "audio_bitrate": [{"label": label, "value": value} for label, value in AUDIO_BITRATE_PRESETS.items()],
            "hardware_accel": HARDWARE_ACCEL_PRESETS,
        },
    }
