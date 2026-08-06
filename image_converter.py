
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import time
import tempfile
from dataclasses import dataclass
from typing import Optional
from collections import deque

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QTextEdit, QGroupBox, QSplitter, QMessageBox, QMenu, QFileDialog,
    QSizePolicy, QSlider, QSpinBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QStandardPaths, QRectF, QSize, QObject, QTimer, Slot
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QPixmap, QPainter, QColor, QPen, QBrush,
    QPainterPath, QIcon
)
from utils import BaseConversionWorker, FFMPEG_MUXER_FORMAT_MAP, get_cjk_font_qss, ThemeManager, hex_with_alpha

SUPPORTED_IMAGE_FORMATS = {
    "png":  {"ext": ".png",  "desc": "PNG — 无损压缩 (透明通道支持)", "quality": False},
    "jpeg": {"ext": ".jpg",  "desc": "JPEG — 通用有损压缩 (照片首选)", "quality": True},
    "webp": {"ext": ".webp", "desc": "WebP — 新一代谷歌格式 (有损/无损)", "quality": True},
    "bmp":  {"ext": ".bmp",  "desc": "BMP — 位图 (无压缩)", "quality": False},
    "gif":  {"ext": ".gif",  "desc": "GIF — 动态/静态图 (256 色)", "quality": False},
    "tiff": {"ext": ".tiff", "desc": "TIFF — 印刷级无损压缩", "quality": True},
    "ico":  {"ext": ".ico",  "desc": "ICO — Windows 图标", "quality": False},
    "avif": {"ext": ".avif", "desc": "AVIF — 新一代 AV1 压缩 (体积最小)", "quality": True},
}

INPUT_IMAGE_FORMATS = [
    "png", "jpg", "jpeg", "jfif", "jpe", "webp", "bmp", "gif", "tif", "tiff",
    "ico", "ppm", "pgm", "pbm", "tga", "svg", "heic", "heif", "avif", "eps",
    "psd", "dng", "nef", "cr2", "arw", "orf", "rw2", "pcx", "xbm", "xpm"
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

_PIL_SUBPROCESS_TEMPLATE = r'''
import sys, os, traceback
try:
    from PIL import Image, ImageOps
except Exception as _e:
    sys.stderr.write("PIL_IMPORT_FAIL: " + str(_e))
    sys.exit(2)

src, dst, fmt, quality, scale_mode, keep_exif = sys.argv[1:7]
quality = int(quality)
keep_exif = keep_exif == "1"

def parse_scale(s):
    if s == "none":
        return None
    try:
        a, b = s.split(":")
        return (a, int(b))
    except Exception:
        return None

scale_mode = parse_scale(scale_mode)

FORMAT_TO_PIL = {
    "jpeg": "JPEG", "jpg": "JPEG", "png": "PNG", "webp": "WEBP",
    "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "tif": "TIFF",
    "ico": "ICO", "avif": "AVIF",
}
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

try:
    with Image.open(src) as img:
        img.load()
        exif_bytes = None
        if keep_exif:
            try:
                exif_bytes = img.info.get("exif") or img.getexif().tobytes() or None
            except Exception:
                exif_bytes = None
        def apply_scale(i, sm):
            if sm is None: return i
            mode, val = sm
            if mode == "percent":
                w = max(1, int(i.size[0] * val / 100.0))
                h = max(1, int(i.size[1] * val / 100.0))
                try: return i.resize((w, h), Image.LANCZOS)
                except Exception: return i.resize((w, h))
            if mode == "max":
                w, h = i.size
                longest = max(w, h)
                if longest <= val: return i
                ratio = val / float(longest)
                w2 = max(1, int(w * ratio))
                h2 = max(1, int(h * ratio))
                try: return i.resize((w2, h2), Image.LANCZOS)
                except Exception: return i.resize((w2, h2))
            return i
        img = apply_scale(img, scale_mode)
        pil_fmt = FORMAT_TO_PIL.get(fmt, fmt.upper())
        if img.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
            img = img.convert("RGB")
        if pil_fmt in ("JPEG",) and img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P": img = img.convert("RGBA")
            if img.mode == "RGBA": bg.paste(img, mask=img.split()[-1])
            else: bg.paste(img)
            img = bg
        kwargs = {}
        qfunc = FORMAT_PIL_SAVE_KWARGS_MAP.get(fmt)
        if qfunc:
            try: kwargs = qfunc(quality)
            except Exception: kwargs = {}
        if exif_bytes and pil_fmt in ("JPEG", "WEBP", "PNG", "TIFF"):
            kwargs["exif"] = exif_bytes
        save_dir = os.path.dirname(dst)
        if save_dir and not os.path.isdir(save_dir):
            os.makedirs(save_dir, exist_ok=True)
        img.save(dst, format=pil_fmt, **kwargs)
        sys.stdout.write("OK")
except Exception as e:
    sys.stderr.write("SAVE_FAIL: " + str(e) + "\n" + traceback.format_exc())
    sys.exit(3)
'''

def _probe_python_has_pil(py_path: str) -> bool:
    if not py_path or not os.path.isfile(py_path):
        return False
    probe = (
        "import sys, importlib.util\n"
        "ok1 = importlib.util.find_spec('PIL') is not None\n"
        "ok2 = importlib.util.find_spec('PIL.Image') is not None if ok1 else False\n"
        "sys.stdout.write('1' if (ok1 and ok2) else '0')\n"
    )
    try:
        r = subprocess.run(
            [py_path, "-c", probe],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace"
        )
        return r.returncode == 0 and r.stdout.strip() == "1"
    except Exception:
        return False


def _collect_python_candidates():
    cands = []
    if not getattr(sys, 'frozen', False):
        cands.append(sys.executable)
    for name in ("python3", "python"):
        try:
            p = shutil.which(name)
            if p and p not in cands:
                cands.append(p)
        except Exception:
            pass
    for hard in ("/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"):
        if os.path.isfile(hard) and hard not in cands:
            cands.append(hard)
    return [p for p in cands if p and os.path.isfile(p)]


def _find_pil_backup_python() -> Optional[str]:
    for p in _collect_python_candidates():
        if p == sys.executable and getattr(sys, 'frozen', False):
            continue
        if _probe_python_has_pil(p):
            if p == sys.executable:
                continue
            return p
    return None


@dataclass
class ImageConversionTask:
    input_path: str
    output_path: str
    output_format: str
    quality: int = 92
    scale_mode: Optional[tuple] = None
    keep_exif: bool = True
    overwrite: bool = False


@dataclass
class ImageConversionResult:
    success: bool
    task: ImageConversionTask
    message: str


def _make_checkbox_icon_pixmap(checked: bool, accent_hex: str, size=22, radius=5,
                              bg_hex: str = "#1a1a2e", border_hex: str = "#0f3460"):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if checked:
        p.setBrush(QBrush(QColor(accent_hex)))
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
        p.drawPath(path)
        pen = QPen(QColor("#ffffff"))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(int(size * 0.22), int(size * 0.55), int(size * 0.44), int(size * 0.76))
        p.drawLine(int(size * 0.40), int(size * 0.76), int(size * 0.80), int(size * 0.26))
    else:
        p.setBrush(QBrush(QColor(bg_hex)))
        pen = QPen(QColor(border_hex))
        pen.setWidth(2)
        p.setPen(pen)
        path = QPainterPath()
        path.addRoundedRect(QRectF(1.0, 1.0, size - 2, size - 2), radius, radius)
        p.drawPath(path)
    p.end()
    return pm


class ImageConversionWorker(QThread):
    progress_signal = Signal(int, int)
    task_started_signal = Signal(str)
    task_finished_signal = Signal(object)
    all_done_signal = Signal()
    single_progress_signal = Signal(int)

    def __init__(self, tasks, ffmpeg_mgr=None, system_pil_python: Optional[str] = None):
        super().__init__()
        self.tasks = tasks
        self.ffmpeg_mgr = ffmpeg_mgr
        self.system_pil_python: Optional[str] = system_pil_python
        self._is_running = True

    def _pil_local_available(self):
        try:
            from PIL import Image
            return True
        except Exception:
            return False

    def _apply_scale(self, img, scale_mode):
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

    def _convert_single_pil_local(self, task: ImageConversionTask) -> ImageConversionResult:
        try:
            from PIL import Image, ImageOps
        except Exception as e:
            return ImageConversionResult(False, task, f"Pillow 未安装: {e}")

        try:
            with Image.open(task.input_path) as img:
                img.load()
                exif_bytes = None
                if task.keep_exif:
                    try:
                        exif_bytes = img.info.get("exif") or img.getexif().tobytes() or None
                    except Exception:
                        exif_bytes = None

                img = self._apply_scale(img, task.scale_mode)

                pil_fmt = FORMAT_TO_PIL.get(task.output_format, task.output_format.upper())

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
                qfunc = FORMAT_PIL_SAVE_KWARGS_MAP.get(task.output_format)
                if qfunc:
                    try:
                        kwargs = qfunc(task.quality)
                    except Exception:
                        kwargs = {}
                if exif_bytes and pil_fmt in ("JPEG", "WEBP", "PNG", "TIFF"):
                    kwargs["exif"] = exif_bytes

                save_dir = os.path.dirname(task.output_path)
                if save_dir and not os.path.isdir(save_dir):
                    os.makedirs(save_dir, exist_ok=True)

                img.save(task.output_path, format=pil_fmt, **kwargs)
                out_size = os.path.getsize(task.output_path)
                return ImageConversionResult(
                    True, task,
                    f"成功 → 格式: {pil_fmt}  大小: {out_size/1024:.1f} KB (Pillow 本地)"
                )
        except Exception as e:
            return ImageConversionResult(False, task, f"Pillow 转换失败: {e}")

    def _convert_single_pil_subprocess(self, task: ImageConversionTask) -> ImageConversionResult:
        if not self.system_pil_python:
            return ImageConversionResult(False, task, "未找到外部 Python (带 Pillow)")
        save_dir = os.path.dirname(task.output_path)
        if save_dir and not os.path.isdir(save_dir):
            os.makedirs(save_dir, exist_ok=True)
        sm_str = "none"
        if task.scale_mode:
            sm_str = f"{task.scale_mode[0]}:{task.scale_mode[1]}"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(_PIL_SUBPROCESS_TEMPLATE)
            script_path = f.name
        try:
            cmd = [
                self.system_pil_python, script_path,
                task.input_path, task.output_path, task.output_format,
                str(task.quality), sm_str,
                "1" if task.keep_exif else "0",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0 and os.path.isfile(task.output_path):
                out_size = os.path.getsize(task.output_path)
                pil_fmt = FORMAT_TO_PIL.get(task.output_format, task.output_format.upper())
                return ImageConversionResult(
                    True, task,
                    f"成功 → 格式: {pil_fmt}  大小: {out_size/1024:.1f} KB (系统 Python·Pillow)"
                )
            tail = "\n".join(deque(result.stderr.splitlines(), maxlen=6)) or "(无输出)"
            return ImageConversionResult(
                False, task,
                f"系统 Python·Pillow 失败 (exit={result.returncode})\n--- stderr ---\n{tail}"
            )
        except Exception as e:
            return ImageConversionResult(False, task, f"系统 Python·Pillow 异常: {e}")
        finally:
            try:
                os.remove(script_path)
            except Exception:
                pass

    def _convert_single_ffmpeg(self, task: ImageConversionTask) -> ImageConversionResult:
        if not self.ffmpeg_mgr or not self.ffmpeg_mgr.available or not self.ffmpeg_mgr.ffmpeg_path:
            return ImageConversionResult(False, task, "FFmpeg 未就绪 (Pillow 也不可用)")
        try:
            save_dir = os.path.dirname(task.output_path)
            if save_dir and not os.path.isdir(save_dir):
                os.makedirs(save_dir, exist_ok=True)
            cmd = [self.ffmpeg_mgr.ffmpeg_path, "-y", "-i", task.input_path]

            fmt = task.output_format.lower()
            vf_parts = []
            extra = ["-frames:v", "1"]
            suffix_override = None

            def q_scale():
                return max(1, 31 - int(task.quality / (100.0 / 30)))

            if fmt == "jpeg" or fmt == "jpg":
                extra += ["-q:v", str(q_scale()), "-pix_fmt", "yuvj420p"]
            elif fmt == "png":
                extra += ["-pix_fmt", "rgba"]
            elif fmt == "webp":
                if task.quality >= 100:
                    extra += ["-lossless", "1"]
                else:
                    extra += ["-q:v", str(max(0, min(100, task.quality)))]
            elif fmt == "tiff":
                extra += ["-c:v", "tiff", "-compression_algo", "raw"]
            elif fmt == "bmp":
                extra += ["-c:v", "bmp", "-pix_fmt", "bgra"]
            elif fmt == "gif":
                extra += ["-loop", "0", "-f", "gif"]
            elif fmt == "ico":
                vf_parts.append(
                    "scale='if(gte(iw,ih),min(256,iw),-1)':"
                    "'if(gte(iw,ih),-1,min(256,ih))',"
                    "pad=256:256:(ow-iw)/2:(oh-ih)/2:color=0x00000000,setsar=1"
                )
                extra += ["-c:v", "png", "-f", "ico", "-update", "1"]
                suffix_override = "ico"
            elif fmt == "avif":
                extra += [
                    "-c:v", "libaom-av1", "-cpu-used", "5",
                    "-crf", str(max(0, min(63, int(63 * (100 - task.quality) / 100.0))))
                ]

            if task.scale_mode is not None:
                mode, val = task.scale_mode
                if mode == "percent":
                    vf_parts.insert(0, f"scale=ceil(iw*{val}/100/2)*2:ceil(ih*{val}/100/2)*2")
                elif mode == "max":
                    vf_parts.insert(
                        0,
                        f"scale='if(gte(iw,ih),if(gte(iw,{val}),{val},iw),-1)':"
                        f"'if(gte(iw,ih),-1,if(gte(ih,{val}),{val},ih))'"
                    )

            if vf_parts:
                cmd += ["-vf", ",".join(vf_parts)]
            cmd += extra
            if suffix_override and not task.output_path.lower().endswith("." + suffix_override):
                pass
            cmd.append(task.output_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0 and os.path.isfile(task.output_path) and os.path.getsize(task.output_path) > 0:
                out_size = os.path.getsize(task.output_path)
                return ImageConversionResult(
                    True, task,
                    f"成功 → 大小: {out_size/1024:.1f} KB (FFmpeg 兜底)"
                )
            tail = "\n".join(deque(result.stderr.splitlines(), maxlen=8)) or "(无输出)"
            return ImageConversionResult(
                False, task,
                f"FFmpeg 失败 (代码: {result.returncode})\n--- stderr ---\n{tail}"
            )
        except Exception as e:
            return ImageConversionResult(False, task, f"FFmpeg 异常: {e}")

    def run(self):
        total = len(self.tasks)
        ok = 0
        fail = 0
        for idx, task in enumerate(self.tasks, start=1):
            if not self._is_running:
                break
            self.task_started_signal.emit(os.path.basename(task.input_path))
            self.single_progress_signal.emit(5)
            QThread.msleep(10)
            self.single_progress_signal.emit(35)

            res = None
            used_engines = []
            if self._pil_local_available():
                res = self._convert_single_pil_local(task)
                used_engines.append("pillow_local")
            if (res is None or not res.success) and self._is_running and self.system_pil_python:
                res = self._convert_single_pil_subprocess(task)
                used_engines.append("pillow_system")
            if (res is None or not res.success) and self._is_running:
                res = self._convert_single_ffmpeg(task)
                used_engines.append("ffmpeg")

            self.single_progress_signal.emit(100)
            self.task_finished_signal.emit(res)
            if res is not None and res.success:
                ok += 1
            else:
                fail += 1
            self.progress_signal.emit(idx, total)

        self.all_done_signal.emit()

    def cancel(self):
        self._is_running = False


class PipInstallWorker(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, pip_target=None, packages=None):
        super().__init__()
        if pip_target:
            self.pip_target = pip_target
        elif getattr(sys, 'frozen', False):
            self.pip_target = shutil.which("python3") or shutil.which("python") or "python3"
        else:
            self.pip_target = sys.executable
        self.packages = packages or ["pillow", "pillow-heif", "pillow-avif-plugin"]

    def run(self):
        try:
            cmd = [
                self.pip_target, "-m", "pip", "install", "--upgrade",
                *self.packages
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                tail = "\n".join(result.stderr.splitlines()[-12:])
                self.finished_signal.emit(False, f"pip install 失败 (exit={result.returncode}): {tail}")
                return
            self.finished_signal.emit(True, "Pillow 安装成功！下次启动会自动作为主引擎使用。")
        except Exception as e:
            self.finished_signal.emit(False, f"pip 安装异常: {e}")


class ImageConverterWidget(QWidget):
    task_monitor_signal = Signal(str)
    log_signal = Signal(str, str)
    task_progress_signal = Signal(str, str, int)
    task_result_signal = Signal(str, str, bool, str)
    def __init__(self, ffmpeg_mgr, default_output_dir: str = ""):
        super().__init__()
        self.ffmpeg_mgr = ffmpeg_mgr
        self.worker = None
        self.theme_colors = ThemeManager.instance().current_colors
        self._default_output_dir = (default_output_dir or "").strip()
        self._current_task_filename = ""
        self._module_name = "🖼️ 图片"

        self.pil_local_available = False
        try:
            from PIL import Image  # noqa: F401
            self.pil_local_available = True
        except Exception:
            self.pil_local_available = False
        self.system_pil_python: Optional[str] = _find_pil_backup_python()

        self._setup_ui()
        self._apply_widget_styles()
        if self._default_output_dir and not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_dir)

    def _setup_ui(self):
        c = self.theme_colors
        self.setMinimumWidth(700)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 20)
        layout.setSpacing(14)

        title_label = QLabel("🖼️  图片格式转换")
        title_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {self.theme_colors['text']};")
        subtitle_label = QLabel("支持 PNG / JPEG / WEBP / TIFF / AVIF / ICO 等主流格式批量互转 (Pillow + FFmpeg 双引擎)")
        subtitle_label.setStyleSheet(f"font-size: 13px; color: {self.theme_colors['text_secondary']};")

        title_layout = QVBoxLayout()
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        title_layout.setSpacing(4)
        layout.addLayout(title_layout)

        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        file_group = QGroupBox("待转换图片")
        file_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {self.theme_colors['text']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                background-color: {self.theme_colors['card']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(12, 16, 12, 12)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setAcceptDrops(True)
        self.file_list.dragEnterEvent = self._drag_enter
        self.file_list.dropEvent = self._drop
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._show_file_context_menu)
        self.file_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self.theme_colors['bg']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 6px;
                color: {self.theme_colors['text']};
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {self.theme_colors['border']};
            }}
            QListWidget::item:selected {{
                background-color: {self.theme_colors['primary']};
                color: white;
            }}
        """)

        file_btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ 添加图片")
        self.add_btn.clicked.connect(self._add_files)
        self.remove_btn = QPushButton("➖ 移除选中")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("🗑 清空全部")
        self.clear_btn.clicked.connect(self._clear_files)
        for btn in [self.add_btn, self.remove_btn, self.clear_btn]:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme_colors['card_hover']};
                    color: {self.theme_colors['text']};
                    border: 1px solid {self.theme_colors['border']};
                    border-radius: 4px;
                    padding: 8px 12px;
                }}
                QPushButton:hover {{
                    background-color: {self.theme_colors['primary']};
                    color: white;
                    border-color: {self.theme_colors['primary']};
                }}
            """)
        file_btn_layout.addWidget(self.add_btn)
        file_btn_layout.addWidget(self.remove_btn)
        file_btn_layout.addWidget(self.clear_btn)
        file_btn_layout.addStretch()

        file_layout.addWidget(self.file_list)
        file_layout.addLayout(file_btn_layout)
        top_layout.addWidget(file_group, 3)

        settings_group = QGroupBox("转换设置")
        settings_group.setMinimumWidth(560)
        settings_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {self.theme_colors['text']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 4px;
                background-color: {self.theme_colors['card']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(18, 6, 18, 14)
        settings_layout.setSpacing(10)
        settings_layout.setSizeConstraint(settings_layout.SizeConstraint.SetMinimumSize)

        input_style = f"""
            QComboBox, QLineEdit, QSpinBox {{
                background-color: {self.theme_colors['bg']};
                color: {self.theme_colors['text']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 22px;
            }}
            QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
                border-color: {self.theme_colors['primary']};
            }}
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
                border-color: {self.theme_colors['success']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {self.theme_colors['bg']};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {self.theme_colors['accent']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
                background: {self.theme_colors['accent']};
                border: 2px solid #ffffff;
            }}
        """

        def create_setting_row(label_text, right_widget):
            row_widget = QWidget()
            row_widget.setMinimumHeight(44)
            row_widget.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
            )
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)

            lab = QLabel(label_text)
            lab.setStyleSheet(
                get_cjk_font_qss(
                    font_size_px=14,
                    color=self.theme_colors['text'],
                    extra="font-weight: 400; padding: 0; background: transparent;"
                )
            )
            lab.setMinimumWidth(100)
            lab.setMaximumWidth(100)
            lab.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
            )
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            row.addWidget(lab, 0)
            row.addWidget(right_widget, 1)
            row.setStretch(0, 0)
            row.setStretch(1, 1)
            return row_widget

        self.format_combo = QComboBox()
        for key, info in SUPPORTED_IMAGE_FORMATS.items():
            self.format_combo.addItem(info["desc"], key)
        self.format_combo.setStyleSheet(input_style)
        self.format_combo.currentIndexChanged.connect(self._refresh_quality_enabled)
        settings_layout.addWidget(create_setting_row("输出格式", self.format_combo))

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("留空 = 在源文件同目录输出")
        self.output_path_edit.setStyleSheet(input_style)
        self.output_browse_btn = QPushButton("📂 浏览")
        self.output_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_colors['card_hover']};
                color: {self.theme_colors['text']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background-color: {self.theme_colors['primary']};
                color: white;
                border-color: {self.theme_colors['primary']};
            }}
        """)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)

        out_wrapper = QWidget()
        out_wrapper.setMinimumHeight(36)
        out_wrap_layout = QHBoxLayout(out_wrapper)
        out_wrap_layout.setContentsMargins(0, 0, 0, 0)
        out_wrap_layout.setSpacing(8)
        out_wrap_layout.addWidget(self.output_path_edit, 1)
        out_wrap_layout.addWidget(self.output_browse_btn, 0)
        settings_layout.addWidget(create_setting_row("输出目录", out_wrapper))

        self.quality_combo = QComboBox()
        for name, val in QUALITY_PRESETS:
            self.quality_combo.addItem(name, val)
        self.quality_combo.setCurrentIndex(1)
        self.quality_combo.setStyleSheet(input_style)
        settings_layout.addWidget(create_setting_row("输出质量", self.quality_combo))

        self.scale_combo = QComboBox()
        for name, val in SCALE_MODE_PRESETS:
            self.scale_combo.addItem(name, val)
        self.scale_combo.setStyleSheet(input_style)
        settings_layout.addWidget(create_setting_row("尺寸缩放", self.scale_combo))

        # 「保留 EXIF」按钮整体右移（对齐到下拉框的位置 = 96 标签宽 + 12 间距 = 108px）
        self.keep_exif_check = QPushButton(
            QIcon(_make_checkbox_icon_pixmap(False, self.theme_colors['accent'],
                                             bg_hex=self.theme_colors['bg'],
                                             border_hex=self.theme_colors['border'])),
            "  保留 EXIF 元数据"
        )
        self.keep_exif_check.setCheckable(True)
        self.keep_exif_check.setChecked(True)
        self.keep_exif_check.setIconSize(QSize(22, 22))
        self.keep_exif_check.setCursor(Qt.PointingHandCursor)
        self.keep_exif_check.setMinimumHeight(38)
        self.keep_exif_check.setStyleSheet(f"""
            QPushButton {{
                color: {self.theme_colors['text']};
                font-size: 14px;
                font-weight: 500;
                padding: 6px 12px 6px 10px;
                border-radius: 6px;
                border: none;
                background-color: transparent;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hex_with_alpha(c['accent'], 0.10)};
            }}
            QPushButton:checked {{
                background-color: {hex_with_alpha(c['accent'], 0.18)};
                color: {c['text']};
                font-weight: 600;
            }}
        """)
        def _on_exif_toggled(c):
            self.keep_exif_check.setIcon(QIcon(_make_checkbox_icon_pixmap(
                c, self.theme_colors['accent'],
                bg_hex=self.theme_colors['bg'],
                border_hex=self.theme_colors['border'])))
        self.keep_exif_check.toggled.connect(_on_exif_toggled)
        cb_layout = QHBoxLayout()
        cb_layout.addSpacing(108)
        cb_layout.addWidget(self.keep_exif_check)
        cb_layout.addStretch()
        settings_layout.addLayout(cb_layout)

        self.overwrite_check = QPushButton(
            QIcon(_make_checkbox_icon_pixmap(False, self.theme_colors['accent'],
                                             bg_hex=self.theme_colors['bg'],
                                             border_hex=self.theme_colors['border'])),
            "  重名文件 — 直接覆盖 (否则自动重命名)"
        )
        self.overwrite_check.setCheckable(True)
        self.overwrite_check.setChecked(False)
        self.overwrite_check.setIconSize(QSize(22, 22))
        self.overwrite_check.setCursor(Qt.PointingHandCursor)
        self.overwrite_check.setMinimumHeight(38)
        self.overwrite_check.setStyleSheet(self.keep_exif_check.styleSheet())
        def _on_over_toggled(c):
            self.overwrite_check.setIcon(QIcon(_make_checkbox_icon_pixmap(
                c, self.theme_colors['accent'],
                bg_hex=self.theme_colors['bg'],
                border_hex=self.theme_colors['border'])))
        self.overwrite_check.toggled.connect(_on_over_toggled)
        cb2 = QHBoxLayout()
        cb2.addSpacing(108)
        cb2.addWidget(self.overwrite_check)
        cb2.addStretch()
        settings_layout.addLayout(cb2)

        settings_layout.addStretch(1)
        top_layout.addWidget(settings_group, 2)
        layout.addWidget(top_widget, 1)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.convert_btn = QPushButton("▶  开始转换")
        self.convert_btn.setMinimumHeight(46)
        self.convert_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_colors["success"]};
                color: white;
                font-weight: bold;
                font-size: 15px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #2eb872;
            }}
            QPushButton:disabled {{
                background-color: #2a3a4a;
                color: #555555;
            }}
        """)
        self.convert_btn.clicked.connect(self._start_conversion)

        self.stop_btn = QPushButton("⏹  停止")
        self.stop_btn.setMinimumHeight(46)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_colors["accent"]};
                color: white;
                font-weight: bold;
                font-size: 15px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #c0392b;
            }}
            QPushButton:disabled {{
                background-color: #2a3a4a;
                color: #555555;
            }}
        """)
        self.stop_btn.clicked.connect(self._stop_conversion)

        self.open_output_btn = QPushButton("📂 打开输出目录")
        self.open_output_btn.setMinimumHeight(46)
        self.open_output_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_colors["card"]};
                color: {self.theme_colors["text"]};
                font-weight: 500;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid {self.theme_colors["border"]};
            }}
            QPushButton:hover {{
                background-color: {self.theme_colors["card_hover"]};
                border-color: {self.theme_colors["success"]};
            }}
        """)
        self.open_output_btn.clicked.connect(self._open_output_dir)

        action_layout.addWidget(self.convert_btn, 2)
        action_layout.addWidget(self.stop_btn, 1)
        action_layout.addStretch()
        action_layout.addWidget(self.open_output_btn, 1)
        layout.addLayout(action_layout)

        self._refresh_quality_enabled()

    def _refresh_quality_enabled(self):
        fmt = self.format_combo.currentData()
        info = SUPPORTED_IMAGE_FORMATS.get(fmt, {})
        need_q = info.get("quality", True)
        self.quality_combo.setEnabled(need_q)

    def _drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._add_file(path)
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for f in files:
                        p = os.path.join(root, f)
                        ext = os.path.splitext(f)[1].lower().lstrip(".")
                        if ext in INPUT_IMAGE_FORMATS:
                            self._add_file(p)

    def _add_files(self):
        exts = " ".join(f"*.{e}" for e in INPUT_IMAGE_FORMATS)
        filter_str = f"图片文件 ({exts});;所有文件 (*)"
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片文件", "", filter_str)
        for f in files:
            self._add_file(f)

    def _add_file(self, path: str):
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole) == path:
                return
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        icon = "🖼️" if ext in INPUT_IMAGE_FORMATS else "📁"
        try:
            sz = os.path.getsize(path) / 1024.0
            size_str = f"  [{sz:.1f} KB]" if sz < 4096 else f"  [{sz/1024:.2f} MB]"
        except Exception:
            size_str = ""
        item = QListWidgetItem(f"  {icon}  {os.path.basename(path)}{size_str}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.file_list.addItem(item)

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _clear_files(self):
        self.file_list.clear()

    def _show_file_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("➖  移除")
        action = menu.exec(self.file_list.mapToGlobal(position))
        if action == remove_action:
            self._remove_selected()

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_path_edit.setText(path)

    def _open_output_dir(self):
        path = self.output_path_edit.text().strip()
        if not path:
            for i in range(self.file_list.count()):
                p = self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                d = os.path.dirname(p)
                if d and os.path.isdir(d):
                    path = d
                    break
        if not path:
            path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if not os.path.isdir(path):
            return
        if os.name == 'nt':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])

    def _build_tasks(self):
        tasks = []
        output_format = self.format_combo.currentData()
        output_dir = self.output_path_edit.text().strip()
        try:
            quality = int(self.quality_combo.currentData())
        except Exception:
            quality = 92
        scale_mode = self.scale_combo.currentData()
        keep_exif = self.keep_exif_check.isChecked()
        overwrite = self.overwrite_check.isChecked()
        ext = SUPPORTED_IMAGE_FORMATS[output_format]["ext"]

        selected_items = self.file_list.selectedItems()
        items_to_convert = selected_items if selected_items else [
            self.file_list.item(i) for i in range(self.file_list.count())
        ]

        for item in items_to_convert:
            input_path = item.data(Qt.ItemDataRole.UserRole)
            if output_dir:
                base = os.path.splitext(os.path.basename(input_path))[0]
                out_path = os.path.join(output_dir, base + ext)
            else:
                base = os.path.splitext(input_path)[0]
                out_path = base + ext

            if not overwrite:
                counter = 1
                original = out_path
                while os.path.isfile(out_path):
                    out_path = os.path.splitext(original)[0] + f"_{counter}" + ext
                    counter += 1

            tasks.append(ImageConversionTask(
                input_path=input_path,
                output_path=out_path,
                output_format=output_format,
                quality=quality,
                scale_mode=scale_mode,
                keep_exif=keep_exif,
                overwrite=overwrite
            ))
        return tasks

    def _ensure_engine_ready(self) -> bool:
        if self.pil_local_available:
            return True
        if self.system_pil_python:
            return True
        if self.ffmpeg_mgr and self.ffmpeg_mgr.available:
            return True
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setWindowTitle("图片转换缺少依赖")
        dlg.setTextFormat(Qt.TextFormat.RichText)
        dlg.setText(
            "当前环境缺少 <b>Pillow</b> 图片主引擎，FFmpeg 也未就绪。<br><br>"
            "<b>推荐方案：一键安装 Pillow（及增强插件）</b><br>"
            "<code style='font-size:12px;'>pip install pillow pillow-heif pillow-avif-plugin</code><br><br>"
            "pillow-heif 开启 HEIC/AVIF，pillow-avif-plugin 获得最佳 AVIF 质量。<br>"
            "安装完成后重启程序即可使用。"
        )
        btn_install = dlg.addButton("一键安装 Pillow（推荐）", QMessageBox.ButtonRole.AcceptRole)
        btn_anyway = dlg.addButton("仍继续（仅 FFmpeg 兜底）", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked is btn_install:
            self._trigger_install_pillow()
            return False
        if clicked is btn_anyway:
            if self.ffmpeg_mgr and self.ffmpeg_mgr.available:
                return True
            QMessageBox.warning(self, "无法继续", "FFmpeg 也不可用，请先安装 Pillow 或配置 FFmpeg。")
            return False
        return False

    def _trigger_install_pillow(self):
        if self.install_worker and self.install_worker.isRunning():
            QMessageBox.information(self, "提示", "Pillow 安装正在进行中，请稍候…")
            return
        self.install_worker = PipInstallWorker()
        self.install_worker.finished_signal.connect(self._on_pillow_installed)
        self.convert_btn.setEnabled(False)
        self.install_worker.start()

    def _on_pillow_installed(self, success: bool, msg: str):
        if success:
            QMessageBox.information(self, "安装成功", msg + "\n\n重启程序后，Pillow 会自动作为主引擎使用。")
        else:
            QMessageBox.critical(
                self, "安装失败",
                msg + "\n\n请手动执行：\n"
                + (self.install_worker.pip_target if hasattr(self, 'install_worker') and self.install_worker else "python3") + " -m pip install --upgrade pillow pillow-heif pillow-avif-plugin"
            )
        self.convert_btn.setEnabled(not (self.worker and self.worker.isRunning()))

    def _start_conversion(self):
        if not self._ensure_engine_ready():
            return

        tasks = self._build_tasks()
        if not tasks:
            QMessageBox.information(self, "提示", "请先添加要转换的图片文件。")
            return

        if self.worker and self.worker.isRunning():
            return

        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = ImageConversionWorker(
            tasks, self.ffmpeg_mgr,
            system_pil_python=self.system_pil_python
        )
        self.worker.progress_signal.connect(self._on_overall_progress)
        self.worker.task_started_signal.connect(self._on_task_started)
        self.worker.task_finished_signal.connect(self._on_task_finished)
        self.worker.all_done_signal.connect(self._on_all_done)
        self.worker.single_progress_signal.connect(self._on_single_progress)
        self.worker.start()

        output_format = self.format_combo.currentData()
        self.log_signal.emit(
            "info",
            f"🖼️ 图片转换启动：共 {len(tasks)} 个文件 → 输出格式 {str(output_format or '').upper()}"
        )

    def _stop_conversion(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.stop_btn.setEnabled(False)
            self.log_signal.emit("warning", "🖼️ 图片转换已被用户停止")

    def _on_overall_progress(self, current, total):
        pass

    def _on_task_started(self, name):
        self._current_task_filename = name
        self.task_monitor_signal.emit(name)
        self.log_signal.emit("info", f"🖼️ 正在转换: {name}")
        self.task_progress_signal.emit(self._module_name, name, 0)

    @Slot(int)
    def _on_single_progress(self, progress: int):
        if self._current_task_filename:
            self.task_progress_signal.emit(
                self._module_name, self._current_task_filename, progress
            )

    def _on_task_finished(self, result: ImageConversionResult):
        basename = os.path.basename(getattr(result.task, "input_path", ""))
        full_path = getattr(result.task, "input_path", "")
        filename = basename if basename else os.path.basename(full_path) or ""
        msg = (getattr(result, "message", "") or "").strip()
        first_line = msg.splitlines()[0] if msg else ""
        if len(first_line) > 120:
            first_line = first_line[:117] + "..."
        success = bool(getattr(result, "success", False))
        if success:
            self.log_signal.emit("success", f"🖼️ {basename} — {first_line or '转换成功'}")
        else:
            self.log_signal.emit("error", f"🖼️ {basename} — {first_line or '转换失败'}")
        self.task_result_signal.emit(self._module_name, filename, success, msg)

    def _on_all_done(self):
        if self._current_task_filename:
            self.task_progress_signal.emit(
                self._module_name, self._current_task_filename, 100
            )
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._current_task_filename = ""
        self.task_monitor_signal.emit("")
        self.log_signal.emit("info", "🖼️ 图片转换全部完成")

    # ==================== 主题 / 默认输出目录支持 ====================

    def _make_checkbox_icon_pixmap(self, checked: bool, accent_hex: str, size=22, radius=5):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.theme_colors
        if checked:
            p.setBrush(QBrush(QColor(accent_hex)))
            p.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
            p.drawPath(path)
            pen = QPen(QColor("#ffffff"))
            pen.setWidth(3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(int(size * 0.22), int(size * 0.55), int(size * 0.44), int(size * 0.76))
            p.drawLine(int(size * 0.40), int(size * 0.76), int(size * 0.80), int(size * 0.26))
        else:
            p.setBrush(QBrush(QColor(c["bg"])))
            pen = QPen(QColor(c["border"]))
            pen.setWidth(2)
            p.setPen(pen)
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, size - 2, size - 2), radius, radius)
            p.drawPath(path)
        p.end()
        return pm

    def _refresh_keep_exif_icon(self):
        c = self.theme_colors
        checked = self.keep_exif_check.isChecked()
        self.keep_exif_check.setIcon(
            QIcon(self._make_checkbox_icon_pixmap(checked, c["accent"]))
        )

    @Slot(str)
    def set_default_output_dir(self, path: str):
        self._default_output_dir = (path or "").strip()
        current = self.output_path_edit.text().strip()
        if not current:
            self.output_path_edit.setText(self._default_output_dir)

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        self.theme_colors = colors
        self._apply_widget_styles()
        self._refresh_keep_exif_icon()

    def _apply_widget_styles(self):
        c = self.theme_colors

        # --- 标题 ---
        root_layout = self.layout()
        first_vl = root_layout.itemAt(0)
        if first_vl and first_vl.layout():
            tl = first_vl.layout()
            if tl.count() >= 2:
                t_lab = tl.itemAt(0).widget()
                s_lab = tl.itemAt(1).widget()
                if isinstance(t_lab, QLabel):
                    t_lab.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {c['text']};")
                if isinstance(s_lab, QLabel):
                    s_lab.setStyleSheet(f"font-size: 13px; color: {c['text_secondary']};")

        # --- 分组框通用样式 ---
        gb_style = f"""
            QGroupBox {{
                font-weight: bold;
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                background-color: {c['card']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """
        for gb in self.findChildren(QGroupBox):
            gb.setStyleSheet(gb_style)

        # --- 文件列表 ---
        self.file_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                color: {c['text']};
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {c['border']};
            }}
            QListWidget::item:selected {{
                background-color: {c['primary']};
                color: white;
            }}
        """)

        # --- 文件操作按钮 ---
        btn_file_op = f"""
            QPushButton {{
                background-color: {c['card_hover']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                background-color: {c['primary']};
                color: white;
                border-color: {c['primary']};
            }}
        """
        for btn in (self.add_btn, self.remove_btn, self.clear_btn):
            btn.setStyleSheet(btn_file_op)

        # --- 输入控件通用 ---
        input_style = f"""
            QComboBox, QLineEdit, QSpinBox {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 6px 10px;
                color: {c['text']};
                min-height: 24px;
            }}
            QComboBox:hover, QLineEdit:hover, QSpinBox:hover,
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
                border: 1px solid {c['primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                selection-background-color: {c['primary']};
                color: {c['text']};
            }}
        """
        for w in (self.format_combo, self.output_path_edit,
                  self.quality_combo, self.scale_combo):
            try:
                w.setStyleSheet(input_style)
            except Exception:
                pass

        # --- 浏览按钮 ---
        self.output_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['card_hover']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background-color: {c['primary']};
                color: white;
                border-color: {c['primary']};
            }}
        """)

        # --- 保留 EXIF 按钮 ---
        self.keep_exif_check.setStyleSheet(f"""
        QPushButton {{
            color: {c['text']};
            font-size: 14px;
            font-weight: 500;
            padding: 6px 12px 6px 10px;
            border-radius: 6px;
            border: none;
            background-color: transparent;
            text-align: left;
        }}
        QPushButton:hover {{
            background-color: {c['card_hover']};
        }}
        QPushButton:checked {{
            background-color: {c['border']};
            color: {c['text']};
            font-weight: 600;
        }}
        """)

        # --- 底部三大操作按钮 ---
        self.convert_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c["success"]};
                color: white;
                font-weight: bold;
                font-size: 15px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {c.get('success_hover', '#2eb872')};
            }}
            QPushButton:disabled {{
                background-color: {c.get('btn_disabled_bg', '#2a3a4a')};
                color: {c.get('btn_disabled_text', '#555555')};
            }}
        """)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c["accent"]};
                color: white;
                font-weight: bold;
                font-size: 15px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {c.get('accent_hover', '#c0392b')};
            }}
            QPushButton:disabled {{
                background-color: {c.get('btn_disabled_bg', '#2a3a4a')};
                color: {c.get('btn_disabled_text', '#555555')};
            }}
        """)
        self.open_output_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c["card"]};
                color: {c["text"]};
                font-weight: 500;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid {c["border"]};
            }}
            QPushButton:hover {{
                background-color: {c["card_hover"]};
                border-color: {c["success"]};
            }}
        """)