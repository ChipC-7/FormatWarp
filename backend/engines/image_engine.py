#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片转换引擎：纯 Pillow 本地转换（零 Qt / 零 FastAPI 依赖）。

从旧 image_converter.py 剥离的纯函数版本：
  - 保留了 SUPPORTED_IMAGE_FORMATS / INPUT_IMAGE_FORMATS / QUALITY_PRESETS /
    SCALE_MODE_PRESETS / FORMAT_PIL_SAVE_KWARGS_MAP / FORMAT_TO_PIL 等预设表；
  - SVG 输入先由 cairosvg 光栅化为 PNG，再统一走 Pillow 主流程（可输出任意位图）；
  - 相机 RAW（dng/nef/cr2/arw/orf/rw2）由 rawpy 解码；JPEG XL 由 pillow-jxl-plugin 支持；
  - 位图 → SVG 由 vtracer 矢量描摹；动图 → PNG 输出保留为 APNG 动画；
  - 删除了 _PIL_SUBPROCESS_TEMPLATE（外部 Python 子进程方案）与 FFmpeg 兜底；
  - convert_image(task, progress_cb, should_abort_cb) 与旧 Worker 的
    _convert_single_pil_local 行为一致，返回 (bool, message)。
"""

import io
import os
import shutil
import tempfile
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
    "jxl":  {"ext": ".jxl",  "desc": "JPEG XL — 新一代高效压缩 (有损/无损)", "need_quality": True},
    "svg":  {"ext": ".svg",  "desc": "SVG — 矢量图 (位图描摹生成)", "need_quality": False},
}

# RAW 相机格式扩展名（由 rawpy/LibRaw 解码）
RAW_INPUT_EXTS = {"dng", "nef", "cr2", "arw", "orf", "rw2"}

# RAW 相机格式（dng/nef/cr2/arw/orf/rw2）已暂时从输入列表撤下：
# rawpy 集成代码就位但未经真实 RAW 实证，验证通过后再开放（避免能选必失败）。
INPUT_IMAGE_FORMATS = [
    "png", "jpg", "jpeg", "jfif", "jpe", "webp", "bmp", "gif", "tif", "tiff",
    "ico", "ppm", "pgm", "pbm", "tga", "svg", "heic", "heif", "avif", "jxl",
    "psd", "pcx", "xbm", "xpm",
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
    "jxl":  lambda q: {"lossless": True} if q >= 100 else {"quality": q},
}

FORMAT_TO_PIL = {
    "jpeg": "JPEG", "jpg": "JPEG", "png": "PNG", "webp": "WEBP",
    "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "tif": "TIFF",
    "ico": "ICO", "avif": "AVIF", "jxl": "JXL",
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


def register_optional_plugins() -> None:
    """注册可选图片插件（缺失时静默跳过，由能力预检给出具体原因）。"""
    try:
        import pillow_jxl  # noqa: F401
    except Exception:
        pass
    try:
        import pillow_avif  # noqa: F401
    except Exception:
        pass
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass


_PLUGIN_HINT = {
    "avif": "pillow-avif-plugin",
    "jxl": "pillow-jxl-plugin",
    "svg": "vtracer",
}


def check_output_supported(output_format: str) -> Optional[str]:
    """检查图片输出格式在当前环境是否可用。

    返回 None 表示可输出；返回文案表示缺少编码器/插件，直接作为
    /api/formats 的 unsupported_reason 与 UI 置灰提示。
    """
    fmt = (output_format or "").lower()
    info = SUPPORTED_IMAGE_FORMATS.get(fmt)
    if info is None:
        return f"未知图片输出格式：{fmt}"
    if not pillow_available():
        return "Pillow 未安装，无法执行图片转换（pip install pillow）。"

    register_optional_plugins()

    if fmt == "svg":
        try:
            import vtracer  # noqa: F401
        except Exception:
            return (
                "当前环境缺少位图转 SVG 引擎 vtracer。\n"
                "👉 请安装：pip install vtracer"
            )
        return None

    try:
        from PIL import Image
    except Exception:
        return "Pillow 未安装，无法执行图片转换（pip install pillow）。"

    ext = info["ext"].lower()
    if ext not in Image.registered_extensions():
        hint = _PLUGIN_HINT.get(fmt, "对应的 Pillow 编码器/插件")
        return (
            f"Pillow 当前未注册「{fmt.upper()}」输出支持（缺少 {hint}）。\n"
            f"👉 请安装对应插件后重启后端。"
        )
    return None


def check_conversion_supported(input_path: str, output_format: str) -> Optional[str]:
    """按输入文件扩展名 + 输出格式做组合预检，避免提交后必然失败。"""
    reason = check_output_supported(output_format)
    if reason:
        return reason

    ext = os.path.splitext(input_path)[1].lower().lstrip(".")
    if ext not in INPUT_IMAGE_FORMATS and ext not in RAW_INPUT_EXTS:
        return f"不支持的图片输入格式：{ext or '(无扩展名)'}"
    if ext == "svg":
        try:
            import cairosvg  # noqa: F401
        except Exception:
            return (
                "SVG 输入需要 cairosvg 光栅化引擎。\n"
                "👉 请安装：pip install cairosvg（Linux 还需系统 libcairo）"
            )
    elif ext in RAW_INPUT_EXTS:
        try:
            import rawpy  # noqa: F401
        except Exception:
            return "RAW 输入需要 rawpy（pip install rawpy）。"
    elif ext in ("avif", "jxl", "heic", "heif"):
        try:
            from PIL import Image
        except Exception:
            return "Pillow 未安装，无法读取该图片格式。"
        # 以 Pillow 实际注册的扩展名为准：AVIF 可能是 Pillow 内置，
        # JXL/HEIC 则依赖可选插件。
        if f".{ext}" not in Image.registered_extensions():
            hint = {
                "avif": "pillow-avif-plugin",
                "jxl": "pillow-jxl-plugin",
                "heic": "pillow-heif",
                "heif": "pillow-heif",
            }[ext]
            return f"{ext.upper()} 输入需要 {hint}（安装后重启后端）。"
    return None


def _is_svg(path: str) -> bool:
    """判断输入是否为 SVG：先看扩展名，再嗅探文件开头的 <svg 标记。"""
    if path.lower().endswith(".svg"):
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(512).lstrip()
    except OSError:
        return False
    return head.startswith(b"<svg") or b"<svg" in head[:300]


def _render_svg_png(path: str) -> bytes:
    """用 cairosvg 把 SVG 按其原生尺寸渲染为 PNG 字节。"""
    try:
        import cairosvg
    except Exception as e:
        raise RuntimeError(
            "SVG 转换需要 cairosvg 及系统 libcairo，请先安装：pip install cairosvg"
        ) from e
    with open(path, "rb") as f:
        data = f.read()
    try:
        return cairosvg.svg2png(bytestring=data)
    except Exception as e:
        raise RuntimeError(f"SVG 渲染失败（文件可能包含不支持的特性）：{e}") from e


def _is_raw(path: str) -> bool:
    """判断输入是否为相机 RAW。"""
    return os.path.splitext(path)[1].lower().lstrip(".") in RAW_INPUT_EXTS


def _load_raw_image(path: str):
    """用 rawpy（LibRaw）解码 RAW 为 Pillow Image。"""
    try:
        import rawpy
    except Exception as e:
        raise RuntimeError("RAW 转换需要 rawpy：pip install rawpy") from e
    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess()  # RGB ndarray（含白平衡、去马赛克）
    except Exception as e:
        raise RuntimeError(f"RAW 解码失败：{e}") from e
    # 本函数在模块级定义，不能依赖 convert_image() 内的局部 Image 导入；
    # 这里单独导入，避免启用 RAW 输入后出现 NameError。
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("RAW 转换需要 Pillow：pip install pillow") from e
    return Image.fromarray(rgb)


def _bitmap_to_svg(input_path: str, output_path: str) -> None:
    """用 vtracer 把位图文件矢量描摹为 SVG 文件。"""
    try:
        import vtracer
    except Exception as e:
        raise RuntimeError("位图转 SVG 需要 vtracer：pip install vtracer") from e
    try:
        vtracer.convert_image_to_svg_py(input_path, output_path)
    except Exception as e:
        raise RuntimeError(f"矢量描摹失败：{e}") from e


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

    # 注册可选图像插件（JXL/AVIF 输出、HEIC/HEIF 输入）
    register_optional_plugins()

    progress_cb(5)
    if should_abort_cb():
        _delete_partial(getattr(task, "output_path", ""))
        return False, "用户取消"

    output_format = (task.output_format or "").lower()
    save_dir = os.path.dirname(task.output_path)
    if save_dir and not os.path.isdir(save_dir):
        os.makedirs(save_dir, exist_ok=True)

    try:
        # ---- SVG 输出：位图 → 矢量描摹（RAW 先转临时 PNG）----
        if output_format == "svg":
            if _is_svg(task.input_path):
                shutil.copyfile(task.input_path, task.output_path)
                progress_cb(100)
                return True, "源已是 SVG，直接复制"
            tmp_png = None
            try:
                if _is_raw(task.input_path):
                    tmp_png = os.path.join(tempfile.mkdtemp(), "raw_render.png")
                    _load_raw_image(task.input_path).save(tmp_png)
                    src_for_trace = tmp_png
                else:
                    src_for_trace = task.input_path
                _bitmap_to_svg(src_for_trace, task.output_path)
            finally:
                if tmp_png:
                    shutil.rmtree(os.path.dirname(tmp_png), ignore_errors=True)
            progress_cb(100)
            return True, "位图 → SVG（vtracer 矢量描摹）"

        # ---- 打开输入：RAW / SVG / 普通位图 ----
        if _is_raw(task.input_path):
            img_ctx = _load_raw_image(task.input_path)
        elif _is_svg(task.input_path):
            img_ctx = Image.open(io.BytesIO(_render_svg_png(task.input_path)))
        else:
            img_ctx = Image.open(task.input_path)
        with img_ctx:
            img_ctx.load()
            exif_bytes = None
            if getattr(task, "keep_exif", True):
                try:
                    exif_bytes = img_ctx.info.get("exif") or img_ctx.getexif().tobytes() or None
                except Exception:
                    exif_bytes = None

            # ---- 动图 → PNG：保留全部帧输出 APNG ----
            if output_format == "png" and getattr(img_ctx, "is_animated", False):
                frames, durations = [], []
                for fi in range(getattr(img_ctx, "n_frames", 1)):
                    img_ctx.seek(fi)
                    frame = img_ctx.convert("RGBA")
                    frame = _apply_scale(frame, getattr(task, "scale_mode", None))
                    frames.append(frame)
                    durations.append(img_ctx.info.get("duration", 100))
                    if should_abort_cb():
                        _delete_partial(getattr(task, "output_path", ""))
                        return False, "用户取消"
                frames[0].save(
                    task.output_path, format="PNG", save_all=True,
                    append_images=frames[1:], duration=durations, loop=0,
                    optimize=True, compress_level=6)
                progress_cb(100)
                return True, f"动图 → APNG（{len(frames)} 帧）"

            img = _apply_scale(img_ctx, getattr(task, "scale_mode", None))
            if should_abort_cb():
                _delete_partial(getattr(task, "output_path", ""))
                return False, "用户取消"

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

            if should_abort_cb():
                _delete_partial(getattr(task, "output_path", ""))
                return False, "用户取消"

            img.save(task.output_path, format=pil_fmt, **kwargs)
            out_size = os.path.getsize(task.output_path)
            progress_cb(100)
            return True, f"成功 → 格式: {pil_fmt}  大小: {out_size/1024:.1f} KB (Pillow 本地)"
    except Exception as e:
        _delete_partial(getattr(task, "output_path", ""))
        return False, f"图片转换失败: {e}"


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
