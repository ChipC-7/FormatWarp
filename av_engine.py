#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyAV 进程内引擎：音频/视频转换核心。

纯 Python + av（不 import 任何 Qt 模块），可脱离 GUI 独立 import 与单测。

职责：
  - 引擎可用性 / 能力探测（check_av_available / get_supported_formats）
  - 音频转换 convert_audio（含流直拷、重编码、重采样、loudnorm 归一化）
  - 视频转换 convert_video（含流直拷、软/硬编码、GPU 失败自动降级、GIF、提取音频）
  - 输出格式预检查 check_output_supported

约定：
  - 进度通过 progress_cb(percent:int) 回调上报（调用方负责节流）
  - 取消/暂停通过 should_abort_cb() -> bool 轮询（解码循环内检查）
  - 错误消息风格与旧版一致，含「用户取消」这个魔法字符串
  - 取消或失败时自动删除半成品输出文件
"""

import os
from typing import Callable, Dict, Optional, Set, Tuple

import av
import av.error
import av.filter
from av.audio.resampler import AudioResampler
from av.codec.hwaccel import HWAccel
from av.filter import Graph

# =====================================================================
# 常量映射
# =====================================================================

# 输出格式 -> 容器名（沿用原 utils.FFMPEG_MUXER_FORMAT_MAP 的值，自包含避免依赖 Qt）
FORMAT_CONTAINER_MAP: Dict[str, str] = {
    # 视频
    "mp4": "mp4", "mkv": "matroska", "avi": "avi", "mov": "mov",
    "webm": "webm", "flv": "flv", "ts": "mpegts", "m2ts": "mpegts",
    "wmv": "asf", "mpg": "mpeg", "vob": "mpeg", "m4v": "mp4",
    "3gp": "3gp", "ogv": "ogg", "asf": "asf", "gif": "gif",
    # 音频
    "mp3": "mp3", "wav": "wav", "flac": "flac",
    "aac": "adts", "ogg": "ogg", "opus": "opus", "m4a": "mp4",
    "ac3": "ac3", "wma": "asf", "aiff": "aiff", "amr": "amr",
    "mp2": "mp2", "au": "au", "dts": "dts", "tta": "tta",
    "wv": "wv", "spx": "ogg",
}

# 仅有解码器无编码器的输出格式（预检直接拦截）
UNSUPPORTED_FORMATS: Set[str] = {"ape"}

# 音频输出格式 -> 编码器
AUDIO_CODEC_MAP: Dict[str, str] = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "flac": "flac",
    "aac": "aac",
    "ogg": "libvorbis",
    "opus": "libopus",
    "m4a": "aac",
    "wma": "wmav2",
    "aiff": "pcm_s16be",
    "amr": "libopencore_amrnb",
    "ac3": "ac3",
    "dts": "dts",
    "tta": "tta",
    "wv": "wavpack",
    "mp2": "mp2",
    "spx": "libspeex",
}

# 编码器 -> 推荐的输出采样格式（pcm/flac/amr/spx 用整数，其余浮点）
AUDIO_CODEC_FORMAT: Dict[str, str] = {
    "pcm_s16le": "s16",
    "pcm_s16be": "s16",
    "flac": "s16",
    "tta": "s16",
    "wavpack": "s16",
    "libopencore_amrnb": "s16",
    "libspeex": "s16",
    "mp2": "s16p",
}

# 视频软件编码器（按输出格式）
SOFT_VIDEO_CODEC: Dict[str, str] = {
    "webm": "libvpx-vp9",
    "ogv": "libvpx-vp9",
}

# 视频硬件加速：hardware_accel key -> (编码器, 设备类型, 显示名)
GPU_ENCODER_MAP: Dict[str, Tuple[str, str, str]] = {
    "nvenc": ("h264_nvenc", "cuda", "NVIDIA NVENC"),
    "qsv":   ("h264_qsv",   "qsv",  "Intel QSV"),
    "amf":   ("h264_amf",   "amf",  "AMD AMF"),
    "vtb":   ("h264_videotoolbox", "videotoolbox", "Apple VideoToolbox"),
}

# 视频输出时音频的默认编码器（候选列表，取第一个可用的；未启用 stream copy 时）
VIDEO_AUDIO_CODEC: Dict[str, list] = {
    "webm": ["libopus", "libvorbis"],
    "ogv": ["libopus", "libvorbis"],
}
VIDEO_AUDIO_DEFAULT = "aac"


# =====================================================================
# 能力探测
# =====================================================================

def check_av_available() -> Tuple[bool, str]:
    """探测 PyAV 是否可用。

    :return: (可用与否, 版本号或失败原因)
    """
    try:
        import av as _av  # noqa: F401
        version = getattr(_av, "__version__", "(unknown)")
        # 轻微冒烟：确认核心编解码表可读
        _ = _av.codecs_available
        _ = _av.formats_available
        return True, str(version)
    except ImportError as e:
        return False, f"未安装 PyAV：{e}"
    except Exception as e:
        return False, f"PyAV 初始化失败：{e}"


_CAPABILITY_CACHE: Optional[Dict[str, Set[str]]] = None


def get_supported_formats() -> Dict[str, Set[str]]:
    """返回引擎能力集合（结果缓存到模块级变量）。

    :return: {"muxers": set, "encoders": set}
    """
    global _CAPABILITY_CACHE
    if _CAPABILITY_CACHE is None:
        _CAPABILITY_CACHE = {
            "muxers": set(getattr(av, "formats_available", set())),
            "encoders": set(getattr(av, "codecs_available", set())),
        }
    return _CAPABILITY_CACHE


def detect_gpu_encoders() -> Dict[str, str]:
    """探测可用的硬件编码器（供 UI 下拉框填充）。

    :return: {"nvenc": "NVIDIA NVENC", ...} 仅包含 codecs_available 中的方案
    """
    if not check_av_available()[0]:
        return {}
    encoders = get_supported_formats()["encoders"]
    available: Dict[str, str] = {}
    for key, (codec, _device, display) in GPU_ENCODER_MAP.items():
        if codec in encoders:
            available[key] = display
    return available


def check_output_supported(output_format: str) -> Optional[str]:
    """输出格式预检查：不受支持时返回中文错误提示，受支持返回 None。

    覆盖两类情况：
      1. 仅有解码器无编码器的格式（APE 等，沿用原 FFMPEG_UNSUPPORTED_FORMATS）
      2. 封装器或编码器在 PyAV 内置 FFmpeg 中缺失
    """
    fmt = (output_format or "").lower()
    if fmt in UNSUPPORTED_FORMATS:
        return (
            f"PyAV 无法输出「{fmt.upper()}」格式（无对应封装器/编码器，"
            f"APE 等仅有解码器）。\n"
            f"👉 请改用 FLAC / WAV / TTA / WV 等无损格式。"
        )
    container = FORMAT_CONTAINER_MAP.get(fmt, fmt)
    if container not in get_supported_formats()["muxers"]:
        return (
            f"PyAV 内置 FFmpeg 不支持输出「{fmt.upper()}」格式"
            f"（封装器 muxer='{container}' 缺失）。\n"
            f"👉 请改用 MP4 / MKV / MP3 / WAV 等常见格式。"
        )
    codec = AUDIO_CODEC_MAP.get(fmt) or SOFT_VIDEO_CODEC.get(fmt) or (
        "libx264" if fmt not in ("gif",) else "gif"
    )
    if codec not in get_supported_formats()["encoders"]:
        return (
            f"PyAV 内置 FFmpeg 缺少「{fmt.upper()}」编码器（{codec}）。\n"
            f"👉 请改用 MP3/WAV/MP4 等常见格式。"
        )
    return None


# =====================================================================
# 公共小工具
# =====================================================================

def _delete_partial_output(path: str) -> None:
    """取消/失败后删除半成品输出文件。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_set_bitrate(stream, bitrate) -> None:
    """仅在能解析出有效比特率时设置 stream.bit_rate。"""
    b = _bitrate_to_int(bitrate)
    if b:
        try:
            stream.bit_rate = b
        except Exception:
            pass


def _bitrate_to_int(bitrate: Optional[str]) -> Optional[int]:
    """把 '192k' / '192' 等字符串转成 int(bit/s)；空返回 None。"""
    if not bitrate:
        return None
    s = str(bitrate).strip().lower()
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1000_000)
        return int(float(s))
    except Exception:
        return None


def _channel_count(layout) -> int:
    """返回音频布局的声道数（兼容 PyAV 18：layout.channels 是声道对象元组）。"""
    if layout is None:
        return 2
    try:
        ch = layout.channels
        if isinstance(ch, (tuple, list)):
            return len(ch) or 2
        n = int(ch)
        return n if n > 0 else 2
    except Exception:
        return 2


def _layout_name_for(channels) -> str:
    """把声道数转成 ffmpeg 布局名（供 abuffer / AudioResampler 使用）。"""
    if isinstance(channels, (tuple, list)):
        n = len(channels)
    else:
        try:
            n = int(channels)
        except Exception:
            n = 0
    if n <= 0:
        return "stereo"
    mapping = {
        1: "mono",
        2: "stereo",
        6: "5.1",
        8: "7.1",
    }
    return mapping.get(n, "stereo")


# =====================================================================
# 音频管道：resampler + loudnorm Graph 组合
# =====================================================================

class AudioPipeline:
    """封装 AudioResampler + 可选 loudnorm 滤镜的组合管道。

    输入解码帧 →（可选 loudnorm）→ 重采样到目标 格式/布局/采样率 → 输出帧。
    供 convert_audio 复用，避免在主循环里堆 if-else。
    """

    def __init__(self, src_format: str, src_layout: str, src_rate: int,
                 out_format: str, out_layout: str, out_rate: int,
                 normalize: bool):
        self.out_format = out_format
        self.out_layout = out_layout
        self.out_rate = out_rate
        self.normalize = bool(normalize)
        self._graph: Optional[Graph] = None
        self._resampler = AudioResampler(
            format=out_format, layout=out_layout, rate=out_rate,
        )
        if self.normalize:
            self._graph = Graph()
            buf = self._graph.add(
                "abuffer",
                f"time_base=1/{src_rate}:sample_rate={src_rate}:"
                f"sample_fmt={src_format}:channel_layout={src_layout}",
            )
            loud = self._graph.add("loudnorm", "I=-16:LRA=11:TP=-1.5")
            sink = self._graph.add("abuffersink")
            buf.link_to(loud)
            loud.link_to(sink)
            self._graph.configure()

    def process(self, frame) -> list:
        """处理一帧输入音频，返回 0..n 帧目标格式音频。"""
        out_frames: list = []
        if self._graph is not None:
            self._graph.push(frame)
            while True:
                try:
                    f = self._graph.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    break
                out_frames.extend(self._resampler.resample(f))
        else:
            out_frames = list(self._resampler.resample(frame))
        return out_frames

    def flush(self) -> list:
        """冲刷滤镜与重采样器缓冲，返回剩余输出帧。"""
        out_frames: list = []
        if self._graph is not None:
            self._graph.push(None)
            while True:
                try:
                    f = self._graph.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    break
                out_frames.extend(self._resampler.resample(f))
        out_frames.extend(self._resampler.resample(None))
        return out_frames


# =====================================================================
# 音频转换
# =====================================================================

def _audio_stream_copy(task, container_name: str) -> Tuple[bool, str]:
    """无参数修改时尝试直接 mux 原始音频 packet（流直拷）。

    失败（容器不兼容等）返回 (False, 原因)，由上层降级重编码。
    """
    src = dst = None
    try:
        src = av.open(task.input_path)
        if not src.streams.audio:
            return False, "输入无音频流"
        in_stream = src.streams.audio[0]
        ctx = in_stream.codec_context
        dst = av.open(task.output_path, mode="w", format=container_name)
        out_stream = dst.add_stream(ctx.name)
        out_stream.time_base = in_stream.time_base
        try:
            out_stream.codec_context.extradata = ctx.extradata
        except Exception:
            pass
        out_stream.sample_rate = ctx.sample_rate
        out_stream.layout = ctx.layout
        out_stream.format = ctx.format
        out_stream.bit_rate = ctx.bit_rate

        for packet in src.demux(in_stream):
            if packet.dts is None:
                continue
            packet.stream = out_stream
            dst.mux(packet)
        return True, "转换成功（流直拷，无损且快速）"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"流直拷失败（{type(e).__name__}: {e}），降级重编码"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"流直拷失败（{e}），降级重编码"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


def _audio_reencode(task, container_name: str, progress_cb: Callable[[int], None],
                    should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """音频重编码：解码 → 管道（resample/loudnorm）→ 编码 → 封装。"""
    src = dst = None
    try:
        src = av.open(task.input_path)
        if not src.streams.audio:
            return False, "输入无音频流"
        in_stream = src.streams.audio[0]
        in_ctx = in_stream.codec_context
        src_rate = in_ctx.sample_rate or 44100
        src_format = in_ctx.format.name if in_ctx.format else "s16"
        src_layout = _layout_name_for(_channel_count(in_ctx.layout))

        out_fmt = (task.output_format or "").lower()
        codec_name = AUDIO_CODEC_MAP.get(out_fmt, "")
        if not codec_name or codec_name not in get_supported_formats()["encoders"]:
            return False, f"PyAV 缺少音频编码器「{codec_name or out_fmt}」，无法输出 {out_fmt.upper()}"

        out_rate = _safe_int(getattr(task, "sample_rate", None), src_rate) or src_rate
        out_channels = getattr(task, "channels", None) or _channel_count(in_ctx.layout)
        out_layout = _layout_name_for(out_channels)
        out_sample_format = AUDIO_CODEC_FORMAT.get(codec_name, "fltp")

        pipeline = AudioPipeline(
            src_format=src_format, src_layout=src_layout, src_rate=src_rate,
            out_format=out_sample_format, out_layout=out_layout, out_rate=out_rate,
            normalize=bool(getattr(task, "normalize", False)),
        )

        dst = av.open(task.output_path, mode="w", format=container_name)
        out_stream = dst.add_stream(codec_name, rate=out_rate)
        _br = _bitrate_to_int(getattr(task, "bitrate", None))
        if _br:
            out_stream.bit_rate = _br
        out_stream.sample_rate = out_rate
        out_stream.layout = out_layout
        out_stream.format = out_sample_format

        # 进度基准：输入容器时长（微秒）
        total_us = float(src.duration or 0)
        done_us = 0.0

        for frame in src.decode(in_stream):
            if should_abort_cb():
                raise _UserCancel()
            if frame.pts is not None:
                done_us = max(done_us, float(frame.pts * frame.time_base) * 1_000_000.0)
            elif frame.samples:
                done_us += float(frame.samples) / float(src_rate or 1) * 1_000_000.0
            for out_frame in pipeline.process(frame):
                for packet in out_stream.encode(out_frame):
                    dst.mux(packet)
            if total_us > 0:
                progress_cb(min(99, int(done_us / total_us * 100)))

        # 冲刷
        for out_frame in pipeline.flush():
            for packet in out_stream.encode(out_frame):
                dst.mux(packet)
        for packet in out_stream.encode(None):
            dst.mux(packet)
        progress_cb(100)
        return True, "转换成功"
    except _UserCancel:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, "用户取消"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"音频转换失败（{type(e).__name__}: {e}）"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"音频转换异常: {e}"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


class _UserCancel(Exception):
    """内部异常：解码循环检测到取消/停止时抛出。"""


def convert_audio(task, progress_cb: Callable[[int], None],
                  should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """音频格式转换入口。

    :param task: AudioConversionTask（含 input_path/output_path/output_format/
                 bitrate/sample_rate/channels/normalize/task_id）
    :param progress_cb: progress_cb(percent:int)，由调用方负责节流
    :param should_abort_cb: should_abort_cb() -> bool，每处理约 1 秒数据检查一次
    :return: (成功与否, 消息)
    """
    out_fmt = (task.output_format or "").lower()
    hint = check_output_supported(out_fmt)
    if hint:
        return False, hint
    container_name = FORMAT_CONTAINER_MAP.get(out_fmt, out_fmt)

    # 无任何参数修改时优先流直拷，失败降级重编码
    need_reencode = bool(
        getattr(task, "bitrate", None) or getattr(task, "sample_rate", None)
        or getattr(task, "channels", None) or getattr(task, "normalize", None)
    )
    if not need_reencode:
        ok, msg = _audio_stream_copy(task, container_name)
        if ok:
            return True, msg
    return _audio_reencode(task, container_name, progress_cb, should_abort_cb)


# =====================================================================
# 视频转换
# =====================================================================

def _video_stream_copy(task, container_name: str) -> Tuple[bool, str]:
    """视频/音频全部流直拷（-c copy 等价）。"""
    src = dst = None
    try:
        src = av.open(task.input_path)
        dst = av.open(task.output_path, mode="w", format=container_name)
        mapping = {}
        for in_stream in src.streams:
            if in_stream.type not in ("video", "audio"):
                continue
            ctx = in_stream.codec_context
            out_stream = dst.add_stream(ctx.name)
            out_stream.time_base = in_stream.time_base
            try:
                out_stream.codec_context.extradata = ctx.extradata
            except Exception:
                pass
            if in_stream.type == "video":
                out_stream.width = ctx.width
                out_stream.height = ctx.height
                out_stream.pix_fmt = ctx.pix_fmt
                out_stream.framerate = in_stream.average_rate
            else:
                out_stream.sample_rate = ctx.sample_rate
                out_stream.layout = ctx.layout
                out_stream.format = ctx.format
                out_stream.bit_rate = ctx.bit_rate
            mapping[in_stream] = out_stream

        muxed = 0
        for packet in src.demux():
            if packet.stream.type not in ("video", "audio"):
                continue
            if packet.dts is None:
                continue
            packet.stream = mapping[packet.stream]
            dst.mux(packet)
            muxed += 1
        if muxed == 0:
            raise av.error.FFmpegError("无可封装的数据包")
        return True, "转换成功（-c copy 流直拷，无损且快速）"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"流直拷失败（{type(e).__name__}: {e}），降级重编码"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"流直拷失败（{e}），降级重编码"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


def _video_extract_audio(task, container_name: str, progress_cb: Callable[[int], None],
                         should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """从视频中提取音频（-vn 等价），按输出格式编码。"""
    src = dst = None
    try:
        src = av.open(task.input_path)
        if not src.streams.audio:
            return False, "输入无音频流"
        in_stream = src.streams.audio[0]
        in_ctx = in_stream.codec_context
        src_rate = in_ctx.sample_rate or 44100
        src_format = in_ctx.format.name if in_ctx.format else "s16"
        src_layout = _layout_name_for(in_ctx.layout.channels if in_ctx.layout else 2)

        out_fmt = (task.output_format or "").lower()
        codec_name = AUDIO_CODEC_MAP.get(out_fmt, "")
        if not codec_name or codec_name not in get_supported_formats()["encoders"]:
            return False, f"PyAV 缺少音频编码器「{codec_name or out_fmt}」，无法提取为 {out_fmt.upper()}"

        out_rate = src_rate
        out_layout = _layout_name_for(in_ctx.layout.channels if in_ctx.layout else 2)
        out_sample_format = AUDIO_CODEC_FORMAT.get(codec_name, "fltp")

        pipeline = AudioPipeline(
            src_format=src_format, src_layout=src_layout, src_rate=src_rate,
            out_format=out_sample_format, out_layout=out_layout, out_rate=out_rate,
            normalize=False,
        )

        dst = av.open(task.output_path, mode="w", format=container_name)
        out_stream = dst.add_stream(codec_name, rate=out_rate)
        _br = _bitrate_to_int(getattr(task, "audio_bitrate", None))
        if _br:
            out_stream.bit_rate = _br
        out_stream.sample_rate = out_rate
        out_stream.layout = out_layout
        out_stream.format = out_sample_format

        total_us = float(src.duration or 0)
        done_us = 0.0
        for frame in src.decode(in_stream):
            if should_abort_cb():
                raise _UserCancel()
            if frame.pts is not None:
                done_us = max(done_us, float(frame.pts * frame.time_base) * 1_000_000.0)
            for out_frame in pipeline.process(frame):
                for packet in out_stream.encode(out_frame):
                    dst.mux(packet)
            if total_us > 0:
                progress_cb(min(99, int(done_us / total_us * 100)))

        for out_frame in pipeline.flush():
            for packet in out_stream.encode(out_frame):
                dst.mux(packet)
        for packet in out_stream.encode(None):
            dst.mux(packet)
        progress_cb(100)
        return True, f"音频提取成功 → {out_fmt.upper()}"
    except _UserCancel:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, "用户取消"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"音频提取失败（{type(e).__name__}: {e}）"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"音频提取异常: {e}"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


def _video_to_gif(task, progress_cb: Callable[[int], None],
                  should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """视频转 GIF：scale→fps→palettegen（第1遍）+ paletteuse（第2遍），保持原命令行效果。"""
    src = dst = None
    try:
        src = av.open(task.input_path)
        if not src.streams.video:
            return False, "输入无视频流"
        vstream = src.streams.video[0]
        width = vstream.codec_context.width or 640
        height = vstream.codec_context.height or 360
        fps_num = vstream.average_rate.numerator if vstream.average_rate else 25
        fps_den = vstream.average_rate.denominator if vstream.average_rate else 1
        fps = fps_num / fps_den if fps_den else 25.0
        in_format = vstream.codec_context.format.name if vstream.codec_context.format else "yuv420p"
        in_rate = fps if fps else 25.0
        src_args = (f"video_size={width}x{height}:pix_fmt={in_format}:"
                    f"time_base=1/{max(1, int(round(in_rate)))}:frame_rate={in_rate}")

        # 收集待处理帧（fps=15 抽样）
        frame_list = []
        for i, frame in enumerate(src.decode(vstream)):
            if i % max(1, int(round(fps / 15.0))):
                continue
            frame_list.append(frame)
            if len(frame_list) % 30 == 0 and should_abort_cb():
                raise _UserCancel()

        # ---- 第 1 遍：palettegen ----
        g1 = Graph()
        buf1 = g1.add("buffer", src_args)
        scale1 = g1.add("scale", "480:-1")
        fps1 = g1.add("fps", "15")
        pal_node = g1.add("palettegen", "stats_mode=diff")
        sink1 = g1.add("buffersink")
        buf1.link_to(scale1)
        scale1.link_to(fps1)
        fps1.link_to(pal_node)
        pal_node.link_to(sink1)
        g1.configure()
        palette = None
        for f in frame_list:
            g1.push(f)
            while True:
                try:
                    g1.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    break
        g1.push(None)
        while True:
            try:
                palette = g1.pull()
            except (av.error.BlockingIOError, av.error.EOFError):
                break
        if palette is None:
            raise av.error.FFmpegError("palettegen 未生成调色板")

        # ---- 第 2 遍：paletteuse → gif 编码 ----
        dst = av.open(task.output_path, mode="w", format="gif")
        gstream = dst.add_stream("gif", rate=15)
        gstream.width = 480
        gstream.height = 270
        gstream.pix_fmt = "pal8"

        g2 = Graph()
        buf2 = g2.add("buffer", src_args)
        scale2 = g2.add("scale", "480:-1")
        fps2 = g2.add("fps", "15")
        palbuf = g2.add(
            "buffer",
            f"video_size={palette.width}x{palette.height}:pix_fmt={palette.format.name}:"
            f"time_base=1/25:frame_rate=25",
        )
        use = g2.add("paletteuse", "dither=bayer:bayer_scale=5:diff_mode=rectangle")
        sink2 = g2.add("buffersink")
        buf2.link_to(scale2)
        scale2.link_to(fps2)
        fps2.link_to(use, 0, 0)
        palbuf.link_to(use, 0, 1)
        use.link_to(sink2)
        g2.configure()

        palette.pts = 0
        g2.push(palette)

        total = max(1, len(frame_list))
        processed = 0
        for f in frame_list:
            if should_abort_cb():
                raise _UserCancel()
            g2.push(f)
            while True:
                try:
                    out_frame = g2.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    break
                for packet in gstream.encode(out_frame):
                    dst.mux(packet)
            processed += 1
            progress_cb(min(99, int(processed / total * 100)))
        g2.push(None)
        while True:
            try:
                out_frame = g2.pull()
            except (av.error.BlockingIOError, av.error.EOFError):
                break
            for packet in gstream.encode(out_frame):
                dst.mux(packet)
        for packet in gstream.encode(None):
            dst.mux(packet)
        progress_cb(100)
        return True, "转换成功（GIF，480p 15fps）"
    except _UserCancel:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, "用户取消"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"GIF 转换失败（{type(e).__name__}: {e}）"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"GIF 转换异常: {e}"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


def _video_transcode(task, container_name: str, video_codec: str,
                     hw_device: Optional[str],
                     progress_cb: Callable[[int], None],
                     should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """视频/音频重编码（GPU 或 CPU），hw_device 为 None 时用软件编码。"""
    src = dst = None
    try:
        src = av.open(task.input_path)
        dst = av.open(task.output_path, mode="w", format=container_name)

        vstream = src.streams.video[0] if src.streams.video else None
        astream = src.streams.audio[0] if src.streams.audio else None

        out_video = None
        if vstream is not None:
            vctx = vstream.codec_context
            rate = vstream.average_rate or (25, 1)
            kwargs = {}
            if hw_device:
                kwargs["hwaccel"] = HWAccel(hw_device)
            out_video = dst.add_stream(video_codec, rate=rate, **kwargs)
            out_video.width = vctx.width
            out_video.height = vctx.height
            out_video.pix_fmt = vctx.pix_fmt
            if video_codec == "h264_nvenc":
                out_video.options = {"preset": "p4", "rc": "vbr"}
                if getattr(task, "video_bitrate", None):
                    out_video.bit_rate = _bitrate_to_int(task.video_bitrate)
                else:
                    out_video.options.update({"cq": "23"})
            elif getattr(task, "video_bitrate", None):
                out_video.bit_rate = _bitrate_to_int(task.video_bitrate)
            else:
                # 恒定质量：mp4/mkv/mov 用 CRF；webm 用 libvpx-vp9 恒定质量
                if video_codec == "libvpx-vp9":
                    out_video.options = {"crf": "30", "b": "0"}
                else:
                    out_video.options = {"crf": "23", "preset": "medium"}
            if vctx.format:
                out_video.format = vctx.format  # PyAV 18：视频 format 需传 VideoFormat 对象

        out_audio = None
        if astream is not None:
            actx = astream.codec_context
            src_rate = actx.sample_rate or 44100
            src_format = actx.format.name if actx.format else "s16"
            src_layout = _layout_name_for(_channel_count(actx.layout))
            out_fmt = (task.output_format or "").lower()
            audio_candidates = VIDEO_AUDIO_CODEC.get(out_fmt) or [VIDEO_AUDIO_DEFAULT]
            encoders = get_supported_formats()["encoders"]
            audio_codec = next((c for c in audio_candidates if c in encoders), VIDEO_AUDIO_DEFAULT)
            # libopus 仅支持 8k/12k/16k/24k/48k；且 PyAV 18 内置 libopus 立体声编码损坏，
            # 多声道源在 webm/ogv 输出时确定性降级为单声道（避免 avcodec_open2 失败）
            if audio_codec == "libopus":
                src_rate = 48000 if src_rate not in (8000, 12000, 16000, 24000, 48000) else src_rate
                src_layout = "mono"
                src_format = "fltp"
            out_audio = dst.add_stream(audio_codec, rate=src_rate)
            out_audio.sample_rate = src_rate
            out_audio.layout = src_layout
            out_audio.format = AUDIO_CODEC_FORMAT.get(audio_codec, "fltp")
            if getattr(task, "audio_bitrate", None):
                _safe_set_bitrate(out_audio, task.audio_bitrate)

            pipeline = AudioPipeline(
                src_format=src_format, src_layout=src_layout, src_rate=src_rate,
                out_format=AUDIO_CODEC_FORMAT.get(audio_codec, "fltp"),
                out_layout=src_layout, out_rate=src_rate, normalize=False,
            )
        else:
            pipeline = None

        total_us = float(src.duration or 0)
        done_us = 0.0
        frame_count = 0

        for packet in src.demux():
            if packet.stream.type not in ("video", "audio"):
                continue
            if packet.stream.type == "video":
                if out_video is None:
                    continue
                for frame in packet.decode():
                    frame_count += 1
                    if should_abort_cb():
                        raise _UserCancel()
                    if frame.pts is not None:
                        done_us = max(done_us, float(frame.pts * frame.time_base) * 1_000_000.0)
                    for out_packet in out_video.encode(frame):
                        dst.mux(out_packet)
                    if total_us > 0:
                        progress_cb(min(99, int(done_us / total_us * 100)))
            elif packet.stream.type == "audio":
                if out_audio is None or pipeline is None:
                    continue
                for frame in packet.decode():
                    if should_abort_cb():
                        raise _UserCancel()
                    for out_frame in pipeline.process(frame):
                        for out_packet in out_audio.encode(out_frame):
                            dst.mux(out_packet)

        if out_video is not None:
            for out_packet in out_video.encode(None):
                dst.mux(out_packet)
        if out_audio is not None and pipeline is not None:
            for out_frame in pipeline.flush():
                for out_packet in out_audio.encode(out_frame):
                    dst.mux(out_packet)
            for out_packet in out_audio.encode(None):
                dst.mux(out_packet)
        progress_cb(100)
        return True, "转换成功"
    except _UserCancel:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, "用户取消"
    except av.error.FFmpegError as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"视频转换失败（{type(e).__name__}: {e}）"
    except Exception as e:
        _delete_partial_output(getattr(task, "output_path", ""))
        return False, f"视频转换异常: {e}"
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass


def convert_video(task, progress_cb: Callable[[int], None],
                  should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """视频格式转换入口。

    :param task: VideoConversionTask（含 input_path/output_path/output_format/
                 video_bitrate/audio_bitrate/extract_audio/hardware_accel/task_id）
    :param progress_cb: progress_cb(percent:int)
    :param should_abort_cb: should_abort_cb() -> bool
    :return: (成功与否, 消息)
    """
    out_fmt = (task.output_format or "").lower()
    hint = check_output_supported(out_fmt)
    if hint:
        return False, hint
    container_name = FORMAT_CONTAINER_MAP.get(out_fmt, out_fmt)

    # 提取音频（-vn）
    if getattr(task, "extract_audio", False):
        return _video_extract_audio(task, container_name, progress_cb, should_abort_cb)

    # GIF 专用滤镜链
    if out_fmt == "gif":
        return _video_to_gif(task, progress_cb, should_abort_cb)

    # 无任何参数修改时尝试流直拷
    if not getattr(task, "video_bitrate", None) and not getattr(task, "audio_bitrate", None):
        ok, msg = _video_stream_copy(task, container_name)
        if ok:
            return True, msg

    # 决定硬件编码器
    hw_key = getattr(task, "hardware_accel", None)
    if hw_key == "cpu":
        hw_key = None
    if hw_key is None:
        # 自动：检测到 GPU 编码器则尝试，否则纯 CPU
        available_gpu = detect_gpu_encoders()
        if available_gpu:
            hw_key = next(iter(available_gpu.keys()))
    if hw_key is not None and hw_key not in GPU_ENCODER_MAP:
        hw_key = None

    video_codec = SOFT_VIDEO_CODEC.get(out_fmt, "libx264")
    if hw_key is not None:
        hw_codec, hw_device, _ = GPU_ENCODER_MAP[hw_key]
        ok, msg = _video_transcode(task, container_name, hw_codec, hw_device,
                                   progress_cb, should_abort_cb)
        if ok:
            return True, "转换成功（硬件加速）"
        # GPU 失败 → 删除半成品 → 降级软编
        _delete_partial_output(getattr(task, "output_path", ""))
        ok2, msg2 = _video_transcode(task, container_name, video_codec, None,
                                     progress_cb, should_abort_cb)
        if ok2:
            return True, "转换成功（硬件加速失败，已自动降级为 CPU 编码）"
        return False, f"硬件加速失败且 CPU 编码也失败：\n{msg2}"

    return _video_transcode(task, container_name, video_codec, None,
                            progress_cb, should_abort_cb)
