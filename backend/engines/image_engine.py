#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片转换引擎：纯 Pillow 本地转换（零 Qt / 零 FastAPI 依赖）。

从旧 image_converter.py 剥离的纯函数版本：
  - 保留了 SUPPORTED_IMAGE_FORMATS / INPUT_IMAGE_FORMATS / QUALITY_PRESETS /
    SCALE_MODE_PRESETS / FORMAT_PIL_SAVE_KWARGS_MAP / FORMAT_TO_PIL 等预设表；
  - 删除了 _PIL_SUBPROCESS_TEMPLATE（外部 Python 子进程方案）与 FFmpeg 兜底，
    只保留本地 Pillow 主路径；
  - convert_image(task, progress_cb, should_abort_cb) 与旧 Worker 的
    _convert_single_pil_local 行为一致，返回 (bool, message)。
"""

import os
from typing import Callable, Optional, Tuple

# =====================================================================
# 格式预设表（沿用旧 image_converter.py）
# =====================================================================

SUPPORTED_IMAGE_FORMATS = {
    "png":  {"ext": ".png",  "desc": "PNG — 无损压缩 (透明通道支持)", "need_quality": False},
    "jpeg": {"ext": ".jpg",  "desc": "JPEG — 通用有损压缩 (照片首选)", "need_quality": True},
    "webp": {"ext": ".webp", "desc": "WebP — 新一代谷歌格式 (有损/无损)", "need_quality": True},
    "bmp":  {"ext": ".bmp",  "desc": "BMP — 位图 (无压缩)", "need_quality": False},
    "gif":  {"ext": ".gif",  "desc": "GIF — 动态/静态图 (256 色)", "need_quality": False},
    "tiff": {"ext": ".tiff", "desc": "TIFF — 印刷级无损压缩", "need_quality": True},
    "ico":  {"ext": ".ico",  "desc": "ICO — Windows 图标", "need_quality": False},
    "avif": {"ext": ".avif", "desc": "AVIF — 新一代 AV1 压缩 (体积最小)", "need_quality": True},
}

INPUT_IMAGE_FORMATS = [
    "png", "jpg", "jpeg", "jfif", "jpe", "webp", "bmp", "gif", "tif", "tiff",
    "ico", "ppm", "pgm", "pbm", "tga", "svg", "heic", "heif", "avif", "eps",
    "psd", "dng", "nef", "cr2", "arw", "orf", "rw2", "pcx", "xbm", "xpm",
]

QUALITY_PRESETS = [
    ("最高质量 (100)", 100),
    ("高质量 (92)", 92),
    ("标准质量 (80)", 80),
    ("中等质量 (65)", 65),
    ("较小体积 (50)", 50),
    ("最小体积 (30)", 30),
]

SCALE_MODE_PRESETS = [
    ("保持原样", None),
    ("按百分比缩小 50%", ("percent", 50)),
    ("按百分比缩小 25%", ("percent", 25)),
    ("限制最长边 1920px", ("max", 1920)),
    ("限制最长边 1280px", ("max", 1280)),
    ("限制最长边 1080px", ("max", 1080)),
    ("限制最长边 720px", ("max", 720)),
]

FORMAT_PIL_SAVE_KWARGS_MAP = {
    "jpeg": lambda q: {"quality": q, "optimize": True, "progressive": True},
    "jpg":  lambda q: {"quality": q, "optimize": True, "progressive": True},
    "webp": lambda q: {"quality": q, "method": 6, "lossless": False} if q < 101 else {"lossless": True, "quality": 100},
    "tiff": lambda q: {"compression": "tiff_deflate"},
    "png":  lambda q: {"optimize": True, "compress_level": 6},
    "bmp":  lambda q: {},
    "gif":  lambda q: {"optimize": True},
    "ico":  lambda q: {},
    "avif": lambda q: {"quality": q, "speed": 5},
}

FORMAT_TO_PIL = {
    "jpeg": "JPEG", "jpg": "JPEG", "png": "PNG", "webp": "WEBP",
    "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "tif": "TIFF",
    "ico": "ICO", "avif": "AVIF",
}


# =====================================================================
# 工具
# =====================================================================

def pillow_available() -> bool:
    """探测 Pillow 是否可用。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def _apply_scale(img, scale_mode):
    """按缩放预设缩放图片（percent / max 两种模式），None 表示保持原样。"""
    if scale_mode is None:
        return img
    mode, val = scale_mode
    if mode == "percent":
        w = max(1, int(img.size[0] * val / 100.0))
        h = max(1, int(img.size[1] * val / 100.0))
        try:
            return img.resize((w, h), img.LANCZOS)
        except Exception:
            return img.resize((w, h))
    if mode == "max":
        w, h = img.size
        longest = max(w, h)
        if longest <= val:
            return img
        ratio = val / float(longest)
        w2 = max(1, int(w * ratio))
        h2 = max(1, int(h * ratio))
        try:
            return img.resize((w2, h2), img.LANCZOS)
        except Exception:
            return img.resize((w2, h2))
    return img


def _delete_partial(path: str) -> None:
    """取消/失败后删除半成品输出文件。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# =====================================================================
# 转换入口
# =====================================================================

def convert_image(task, progress_cb: Callable[[int], None],
                  should_abort_cb: Callable[[], bool]) -> Tuple[bool, str]:
    """图片转换入口（Pillow 本地路径）。

    :param task: 鸭子类型任务对象，需含 input_path / output_path / output_format，
                 另有 quality / scale_mode / keep_exif。
    :param progress_cb: progress_cb(percent:int)
    :param should_abort_cb: should_abort_cb() -> bool
    :return: (成功与否, 消息)
    """
    try:
        from PIL import Image
    except Exception as e:
        return False, f"Pillow 未安装: {e}"

    progress_cb(5)
    if should_abort_cb():
        _delete_partial(getattr(task, "output_path", ""))
        return False, "用户取消"

    try:
        with Image.open(task.input_path) as img:
            img.load()
            exif_bytes = None
            if getattr(task, "keep_exif", True):
                try:
                    exif_bytes = img.info.get("exif") or img.getexif().tobytes() or None
                except Exception:
                    exif_bytes = None

            img = _apply_scale(img, getattr(task, "scale_mode", None))
            if should_abort_cb():
                _delete_partial(getattr(task, "output_path", ""))
                return False, "用户取消"

            output_format = (task.output_format or "").lower()
            pil_fmt = FORMAT_TO_PIL.get(output_format, output_format.upper())

            if img.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
                img = img.convert("RGB")
            if pil_fmt in ("JPEG",) and img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg

            kwargs = {}
            qfunc = FORMAT_PIL_SAVE_KWARGS_MAP.get(output_format)
            if qfunc:
                try:
                    kwargs = qfunc(getattr(task, "quality", 92))
                except Exception:
                    kwargs = {}
            if exif_bytes and pil_fmt in ("JPEG", "WEBP", "PNG", "TIFF"):
                kwargs["exif"] = exif_bytes

            save_dir = os.path.dirname(task.output_path)
            if save_dir and not os.path.isdir(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            if should_abort_cb():
                _delete_partial(getattr(task, "output_path", ""))
                return False, "用户取消"

            img.save(task.output_path, format=pil_fmt, **kwargs)
            out_size = os.path.getsize(task.output_path)
            progress_cb(100)
            return True, f"成功 → 格式: {pil_fmt}  大小: {out_size/1024:.1f} KB (Pillow 本地)"
    except Exception as e:
        _delete_partial(getattr(task, "output_path", ""))
        return False, f"Pillow 转换失败: {e}"


# =====================================================================
# 格式信息（供 REST /api/formats）
# =====================================================================

def formats_info() -> dict:
    """返回图片模块的格式与预设信息。"""
    outputs = []
    for key, info in SUPPORTED_IMAGE_FORMATS.items():
        outputs.append({
            "key": key,
            "desc": info["desc"],
            "ext": info["ext"],
            "need_quality": info.get("need_quality", False),
        })
    return {
        "inputs": list(INPUT_IMAGE_FORMATS),
        "outputs": outputs,
        "presets": {
            "quality": [{"label": label, "value": value} for label, value in QUALITY_PRESETS],
            "scale_mode": [{"label": label, "value": value} for label, value in SCALE_MODE_PRESETS],
        },
    }
