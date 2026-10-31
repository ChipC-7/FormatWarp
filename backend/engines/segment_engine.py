#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超长音视频分段并行编码（FFmpeg CLI）。

思路：
  - 仅对达到时长的文件启用；
  - 音频按时间均分，视频按关键帧切分；
  - 多个 ffmpeg 子进程并行编码各段；
  - 最后用 concat demuxer 无损拼接。

FFmpeg 查找顺序：
  1. FORMATWARP_FFMPEG 环境变量
  2. 系统 PATH
  3. imageio-ffmpeg wheel 内置二进制（随 sidecar 打包）

本模块不依赖 FastAPI / tasks / ws，可独立测试。
"""

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Dict, List, Optional, Tuple

import av

# 至少 5 分钟的音频/视频才值得分段（过短文件并行开销大于收益）
MIN_SEGMENT_DURATION_US = 5 * 60 * 1_000_000
MAX_SEGMENTS = 4

# 只对常见且可安全 concat 的容器启用；其他格式自动回退普通转换
VIDEO_PROFILES: Dict[str, dict] = {
    "mp4":  {"ext": ".mp4",  "container": "mp4",      "vcodec": "libx264",   "acodec": "aac"},
    "mkv":  {"ext": ".mkv",  "container": "matroska", "vcodec": "libx264",   "acodec": "aac"},
    "mov":  {"ext": ".mov",  "container": "mov",      "vcodec": "libx264",   "acodec": "aac"},
    "m4v":  {"ext": ".mp4",  "container": "mp4",      "vcodec": "libx264",   "acodec": "aac"},
    "flv":  {"ext": ".flv",  "container": "flv",      "vcodec": "libx264",   "acodec": "aac"},
    "ts":   {"ext": ".ts",   "container": "mpegts",   "vcodec": "libx264",   "acodec": "aac"},
    "m2ts": {"ext": ".ts",   "container": "mpegts",   "vcodec": "libx264",   "acodec": "aac"},
    "webm": {"ext": ".webm", "container": "webm",     "vcodec": "libvpx-vp9", "acodec": "libopus"},
}

AUDIO_PROFILES: Dict[str, dict] = {
    "mp3": {"ext": ".mp3", "container": "mp3",  "codec": "libmp3lame"},
    "wav": {"ext": ".wav", "container": "wav",  "codec": "pcm_s16le"},
    "flac": {"ext": ".flac", "container": "flac", "codec": "flac"},
    "m4a": {"ext": ".m4a", "container": "mp4",  "codec": "aac"},
    "ogg": {"ext": ".ogg", "container": "ogg",  "codec": "libvorbis"},
}


# =====================================================================
# FFmpeg / 时长 / 分段点
# =====================================================================

def find_ffmpeg() -> Optional[str]:
    """按优先级定位 ffmpeg 可执行文件。"""
    env = os.environ.get("FORMATWARP_FFMPEG")
    if env and os.path.isfile(env):
        return env
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _duration_us(path: str) -> float:
    with av.open(path) as container:
        if container.duration:
            return float(container.duration)
        # 兜底：扫描最后一个 packet 的 pts
        max_us = 0.0
        for packet in container.demux():
            if packet.pts is not None and packet.time_base is not None:
                max_us = max(max_us, float(packet.pts * packet.time_base) * 1_000_000.0)
        return max_us


def _video_keyframe_times(path: str) -> Tuple[float, List[float]]:
    """返回 (视频时长 us, 关键帧时间列表 us)。"""
    with av.open(path) as container:
        if not container.streams.video:
            return 0.0, []
        vstream = container.streams.video[0]
        duration = float(container.duration or 0)
        keys: List[float] = []
        for packet in container.demux(vstream):
            if packet.pts is None or packet.time_base is None:
                continue
            t = float(packet.pts * packet.time_base) * 1_000_000.0
            duration = max(duration, t)
            if packet.is_keyframe and t > 0:
                keys.append(t)
        return duration, keys


def _segment_count() -> int:
    cores = os.cpu_count() or 2
    return max(2, min(MAX_SEGMENTS, cores))


def _choose_keyframe_splits(duration_us: float, keyframes: List[float],
                            count: int) -> List[float]:
    """从关键帧中选出最接近等分位置的内部切点。"""
    if count <= 1 or duration_us <= 0:
        return []
    targets = [duration_us * i / count for i in range(1, count)]
    chosen: List[float] = []
    for target in targets:
        candidates = [
            k for k in keyframes
            if k > 0 and k < duration_us and k > (chosen[-1] if chosen else 0)
        ]
        if not candidates:
            break
        best = min(candidates, key=lambda k: abs(k - target))
        # 避免与上一个切点过近
        if chosen and best <= chosen[-1]:
            break
        chosen.append(best)
    return chosen


def _split_ranges(duration_us: float, starts: List[float]) -> List[Tuple[float, float]]:
    points = [0.0] + starts + [duration_us]
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


# =====================================================================
# FFmpeg 命令
# =====================================================================

def _speed_options(task) -> Tuple[str, str]:
    """返回 (x264 preset, vp9 额外参数)。"""
    speed = str(getattr(task, "encode_speed", None) or "veryfast").lower()
    if speed not in ("ultrafast", "veryfast", "fast", "medium"):
        speed = "veryfast"
    vp9_cpu = {"ultrafast": "8", "veryfast": "6", "fast": "4", "medium": "2"}[speed]
    return speed, vp9_cpu


def _video_segment_cmd(ffmpeg: str, task, profile: dict,
                       start_us: float, duration_us: float, segment_path: str) -> List[str]:
    speed, vp9_cpu = _speed_options(task)
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostats",
        "-ss", f"{start_us / 1_000_000:.3f}",
        "-t", f"{duration_us / 1_000_000:.3f}",
        "-i", task.input_path,
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-c:v", profile["vcodec"], "-pix_fmt", "yuv420p", "-threads", "0",
    ]
    if profile["vcodec"] == "libx264":
        cmd += ["-preset", speed]
        if getattr(task, "video_bitrate", None):
            cmd += ["-b:v", str(task.video_bitrate)]
        else:
            cmd += ["-crf", "23"]
    elif profile["vcodec"] == "libvpx-vp9":
        cmd += ["-deadline", "realtime", "-cpu-used", vp9_cpu]
        if getattr(task, "video_bitrate", None):
            cmd += ["-b:v", str(task.video_bitrate)]
        else:
            cmd += ["-crf", "30", "-b:v", "0"]
    if getattr(task, "audio_bitrate", None):
        cmd += ["-c:a", profile["acodec"], "-b:a", str(task.audio_bitrate)]
    else:
        cmd += ["-c:a", profile["acodec"]]
    cmd += ["-progress", "pipe:1", "-f", profile["container"], segment_path]
    return cmd


def _audio_segment_cmd(ffmpeg: str, task, profile: dict,
                       start_us: float, duration_us: float, segment_path: str) -> List[str]:
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostats",
        "-ss", f"{start_us / 1_000_000:.3f}",
        "-t", f"{duration_us / 1_000_000:.3f}",
        "-i", task.input_path,
        "-vn", "-map", "0:a:0", "-c:a", profile["codec"],
    ]
    if getattr(task, "bitrate", None):
        cmd += ["-b:a", str(task.bitrate)]
    if getattr(task, "sample_rate", None):
        cmd += ["-ar", str(task.sample_rate)]
    if getattr(task, "channels", None):
        cmd += ["-ac", str(task.channels)]
    cmd += ["-progress", "pipe:1", "-f", profile["container"], segment_path]
    return cmd


# =====================================================================
# 并行执行 / 拼接
# =====================================================================

def _run_segment(idx: int, cmd: List[str], duration_us: float,
                 progresses: List[float], procs: List[Optional[subprocess.Popen]],
                 abort_cb: Callable[[], bool]) -> Tuple[int, int, str]:
    """线程内运行一个 ffmpeg 子进程，并解析 -progress 输出。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, creationflags=creationflags,
    )
    procs[idx] = proc
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if abort_cb():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    out_us = float(line.split("=", 1)[1])
                except ValueError:
                    continue
                if duration_us > 0:
                    progresses[idx] = max(0.0, min(100.0, out_us / duration_us * 100.0))
            elif line == "progress=end":
                progresses[idx] = 100.0
        code = proc.wait()
        stderr = proc.stderr.read() if proc.stderr else ""
        return idx, code, stderr
    finally:
        procs[idx] = None


def _run_parallel(ffmpeg: str, cmds: List[List[str]], ranges: List[Tuple[float, float]],
                  progress_cb: Callable[[int], None],
                  abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    n = len(cmds)
    progresses = [0.0] * n
    procs: List[Optional[subprocess.Popen]] = [None] * n
    durations = [end - start for start, end in ranges]
    total = sum(durations) or 1.0

    executor = ThreadPoolExecutor(max_workers=n)
    futures = [
        executor.submit(_run_segment, i, cmd, durations[i], progresses, procs, abort_cb)
        for i, cmd in enumerate(cmds)
    ]
    pending = set(futures)
    failures: List[str] = []
    try:
        while pending:
            done, pending = wait(pending, timeout=0.25)
            if abort_cb():
                for p in procs:
                    if p is not None:
                        try:
                            p.terminate()
                        except Exception:
                            pass
                for f in futures:
                    f.cancel()
                return False, "用户取消"
            done_pct = sum(progresses[i] * durations[i] for i in range(n)) / total
            # 分段编码占 0-90%，最后拼接占 90-100%
            progress_cb(max(0, min(90, int(done_pct * 0.9))))
            for f in done:
                try:
                    idx, code, stderr = f.result()
                except Exception as e:
                    failures.append(str(e))
                    continue
                if code != 0:
                    tail = "\n".join((stderr or "").splitlines()[-6:])
                    failures.append(f"分段 {idx} 失败：{tail or f'exit={code}'}")
        if failures:
            return False, "分段并行编码失败：\n" + "\n".join(failures)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        for p in procs:
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass
    progress_cb(90)
    return True, ""


def _concat_segments(ffmpeg: str, segment_paths: List[str], container: str,
                     output_path: str, progress_cb: Callable[[int], None]) -> Tuple[bool, str]:
    list_path = os.path.join(os.path.dirname(segment_paths[0]), "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("ffconcat version 1.0\n")
        for path in segment_paths:
            # concat demuxer 使用类 shell 引号；Windows 反斜杠需转成正斜杠
            escaped = path.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", "-f", container,
    ]
    if container == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd.append(output_path)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, check=False)
    progress_cb(100)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-8:])
        return False, f"分段拼接失败：{tail or f'exit={proc.returncode}'}"
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        return False, "分段拼接未生成有效输出文件"
    return True, ""


# =====================================================================
# 对外入口
# =====================================================================

def try_segment_audio(task, progress_cb: Callable[[int], None],
                      abort_cb: Callable[[], bool],
                      min_duration_us: float = MIN_SEGMENT_DURATION_US
                      ) -> Tuple[bool, bool, str]:
    """尝试长音频分段并行。

    :return: (是否尝试, 是否成功, 消息)。未尝试时由调用方走普通路径。
    """
    if not getattr(task, "segmented", False):
        return False, False, ""
    if bool(getattr(task, "normalize", False)):
        # 分段独立 loudnorm 会导致各段音量不一致，不使用分段
        return False, False, ""
    out_fmt = (task.output_format or "").lower()
    profile = AUDIO_PROFILES.get(out_fmt)
    if profile is None:
        return False, False, ""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, False, ""
    try:
        duration_us = _duration_us(task.input_path)
    except Exception:
        return False, False, ""
    if duration_us < min_duration_us:
        return False, False, ""

    count = _segment_count()
    starts = [duration_us * i / count for i in range(1, count)]
    ranges = _split_ranges(duration_us, starts)
    workdir = tempfile.mkdtemp(prefix="fw_seg_audio_")
    segment_paths = [
        os.path.join(workdir, f"seg{i}{profile['ext']}") for i in range(len(ranges))
    ]
    cmds = [
        _audio_segment_cmd(ffmpeg, task, profile, start, end - start, path)
        for (start, end), path in zip(ranges, segment_paths)
    ]
    try:
        ok, msg = _run_parallel(ffmpeg, cmds, ranges, progress_cb, abort_cb)
        if not ok:
            _delete_output(task.output_path)
            return True, False, msg
        ok, msg = _concat_segments(
            ffmpeg, segment_paths, profile["container"], task.output_path, progress_cb,
        )
        if not ok:
            _delete_output(task.output_path)
            return True, False, msg
        return True, True, f"转换成功（分段并行，{len(ranges)} 段）"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def try_segment_video(task, progress_cb: Callable[[int], None],
                      abort_cb: Callable[[], bool],
                      min_duration_us: float = MIN_SEGMENT_DURATION_US
                      ) -> Tuple[bool, bool, str]:
    """尝试长视频分段并行。仅使用 CPU 编码，硬件编码仍走原路径。"""
    if not getattr(task, "segmented", False):
        return False, False, ""
    if getattr(task, "extract_audio", False) or (task.output_format or "").lower() == "gif":
        return False, False, ""
    hw = getattr(task, "hardware_accel", None)
    if hw not in (None, "cpu"):
        return False, False, ""
    out_fmt = (task.output_format or "").lower()
    profile = VIDEO_PROFILES.get(out_fmt)
    if profile is None:
        return False, False, ""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, False, ""

    try:
        # 先读容器时长，短文件不做全量关键帧扫描
        if _duration_us(task.input_path) < min_duration_us:
            return False, False, ""
        duration_us, keyframes = _video_keyframe_times(task.input_path)
    except Exception:
        return False, False, ""
    if duration_us < min_duration_us or not keyframes:
        return False, False, ""

    count = _segment_count()
    starts = _choose_keyframe_splits(duration_us, keyframes, count)
    if not starts:
        return False, False, ""
    ranges = _split_ranges(duration_us, starts)
    if len(ranges) < 2:
        return False, False, ""

    workdir = tempfile.mkdtemp(prefix="fw_seg_video_")
    segment_paths = [
        os.path.join(workdir, f"seg{i}{profile['ext']}") for i in range(len(ranges))
    ]
    cmds = [
        _video_segment_cmd(ffmpeg, task, profile, start, end - start, path)
        for (start, end), path in zip(ranges, segment_paths)
    ]
    try:
        ok, msg = _run_parallel(ffmpeg, cmds, ranges, progress_cb, abort_cb)
        if not ok:
            _delete_output(task.output_path)
            return True, False, msg
        ok, msg = _concat_segments(
            ffmpeg, segment_paths, profile["container"], task.output_path, progress_cb,
        )
        if not ok:
            _delete_output(task.output_path)
            return True, False, msg
        return True, True, f"转换成功（分段并行，{len(ranges)} 段）"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _delete_output(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
