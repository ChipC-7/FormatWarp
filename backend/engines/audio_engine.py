#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频转换引擎：薄封装 av_engine.convert_audio（零 Qt / 零 FastAPI 依赖）。

预设表从旧 audio_converter.py / utils.py 复制（自包含，避免引入 Qt 依赖）。
"""

import os
from typing import Callable, Tuple

import av_engine

# =====================================================================
# 格式预设表（沿用旧 audio_converter.py / utils.py）
# =====================================================================

SUPPORTED_AUDIO_FORMATS = {
    "mp3":  {"ext": ".mp3",  "desc": "MP3 — 有损压缩 (最通用)"},
    "wav":  {"ext": ".wav",  "desc": "WAV — 无损未压缩"},
    "flac": {"ext": ".flac", "desc": "FLAC — 无损压缩 (Hi-Fi首选)"},
    "aac":  {"ext": ".aac",  "desc": "AAC — 高级音频编码"},
    "ogg":  {"ext": ".ogg",  "desc": "OGG Vorbis — 开源有损"},
    "opus": {"ext": ".opus", "desc": "OPUS — 低延迟语音/音乐"},
    "m4a":  {"ext": ".m4a",  "desc": "M4A — Apple AAC 容器"},
    "wma":  {"ext": ".wma",  "desc": "WMA — Windows 音频"},
    "aiff": {"ext": ".aiff", "desc": "AIFF — 苹果无损音频"},
    "amr":  {"ext": ".amr",  "desc": "AMR — 移动设备语音"},
    "ape":  {"ext": ".ape",  "desc": "APE — Monkey's 无损"},
    "au":   {"ext": ".au",   "desc": "AU — Sun 微系统音频"},
    "ac3":  {"ext": ".ac3",  "desc": "AC3 — 杜比数字环绕声"},
    "dts":  {"ext": ".dts",  "desc": "DTS — 影院级环绕声"},
    "tta":  {"ext": ".tta",  "desc": "TTA — True Audio 无损"},
    "wv":   {"ext": ".wv",   "desc": "WavPack — 混合无损"},
    "mp2":  {"ext": ".mp2",  "desc": "MP2 — 广播级音频"},
    "spx":  {"ext": ".spx",  "desc": "Speex — 开源语音编码"},
}

INPUT_AUDIO_FORMATS = [
    "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus",
    "aiff", "aif", "amr", "ape", "au", "ac3", "dts", "tta", "wv", "mp2", "spx",
]

BITRATE_PRESETS = {
    "自动": None, "64k": "64k", "96k": "96k", "128k": "128k",
    "160k": "160k", "192k": "192k", "256k": "256k", "320k": "320k",
}

SAMPLE_RATE_PRESETS = {
    "保持原样": None, "8000": 8000, "16000": 16000,
    "44100": 44100, "48000": 48000, "96000": 96000,
}

CHANNEL_PRESETS = {
    "保持原样": None, "单声道 (1)": 1, "立体声 (2)": 2,
}


# =====================================================================
# 引擎接口
# =====================================================================

def run(task, progress_cb: Callable[[int], None],
        should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """执行音频转换。

    :param task: 鸭子类型任务对象，需含 input_path / output_path / output_format，
                 另有 bitrate / sample_rate / channels / normalize。
    :return: (成功与否, 消息)
    """
    return av_engine.convert_audio(task, progress_cb, should_abort_cb)


def engine_info() -> Tuple[bool, str]:
    """探测 PyAV 引擎可用性。"""
    return av_engine.check_av_available()


# =====================================================================
# 格式信息（供 REST /api/formats）
# =====================================================================

def formats_info() -> dict:
    """返回音频模块的格式与预设信息。"""
    outputs = []
    for key, info in SUPPORTED_AUDIO_FORMATS.items():
        outputs.append({"key": key, "desc": info["desc"], "ext": info["ext"]})
    return {
        "inputs": list(INPUT_AUDIO_FORMATS),
        "outputs": outputs,
        "presets": {
            "bitrate": [{"label": label, "value": value} for label, value in BITRATE_PRESETS.items()],
            "sample_rate": [{"label": label, "value": value} for label, value in SAMPLE_RATE_PRESETS.items()],
            "channels": [{"label": label, "value": value} for label, value in CHANNEL_PRESETS.items()],
        },
    }
