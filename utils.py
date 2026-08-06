
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import stat
import platform
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont
try:
    from PySide6.QtWidgets import QApplication
except Exception:
    QApplication = None

# ============ 配置常量 ============
APP_NAME = "格式跃迁"
APP_VERSION = "1.0.1"
ORG_NAME = "FormatWarp"

# 主题配色 —— 暗色（当前默认，完全保持不变）
COLORS_DARK = {
    # 基础背景与卡片
    "bg": "#1a1a2e",
    "card": "#16213e",
    "card_hover": "#1e2a4a",
    "border": "#0f3460",

    # 强调色与主色调
    "primary": "#0f3460",
    "primary_hover": "#1a4a80",
    "primary_light": "#2980b9",

    # 强调色 (Accent)
    "accent": "#e94560",
    "accent_hover": "#ff6b81",

    # 文本颜色
    "text": "#eaeaea",
    "text_secondary": "#a0a0a0",

    # 状态颜色
    "success": "#00d9ff",
    "success_hover": "#00b8d4",
    "warning": "#f9a826",
    "error": "#e94560",
    "error_hover": "#ff4d4f",

    # 禁用按钮硬编码颜色
    "btn_disabled_bg": "#2a2a3e",
    "btn_disabled_text": "#666666",
    "btn_disabled_border": "#333333",
}

# 主题配色 —— 亮色（浅色主题）
COLORS_LIGHT = {
    # 基础背景与卡片
    "bg": "#f4f6fb",
    "card": "#ffffff",
    "card_hover": "#eaf0fb",
    "border": "#c9d6ef",

    # 强调色与主色调
    "primary": "#3a6ea5",
    "primary_hover": "#2e5a88",
    "primary_light": "#4a8bd6",

    # 强调色 (Accent)
    "accent": "#d9405d",
    "accent_hover": "#ff5a78",

    # 文本颜色
    "text": "#1a2440",
    "text_secondary": "#576485",

    # 状态颜色
    "success": "#0a85a0",
    "success_hover": "#086a83",
    "warning": "#e08a00",
    "error": "#d9405d",
    "error_hover": "#ff5a78",

    # 禁用按钮硬编码颜色（亮色下禁用按钮变浅灰）
    "btn_disabled_bg": "#d6ddef",
    "btn_disabled_text": "#8a96b5",
    "btn_disabled_border": "#b4c2e0",
}

# 向后兼容：默认 COLORS 仍然指向暗色（老代码不用改）
COLORS = COLORS_DARK


def hex_with_alpha(hex_color: str, alpha: float) -> str:
    """将 #rrggbb 转为 rgba(r, g, b, a)。"""
    s = hex_color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    a = max(0.0, min(1.0, float(alpha)))
    return f"rgba({r}, {g}, {b}, {a:.2f})"


def get_colors_for_theme(theme_name: Optional[str]) -> dict:
    name = (theme_name or "dark").lower()
    if name == "light":
        return COLORS_LIGHT
    return COLORS_DARK

def get_app_path() -> Path:
    """获取应用程序所在目录（兼容 PyInstaller 打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent

# ============ FFmpeg 检测与管理 ============
FFMPEG_MUXER_FORMAT_MAP = {
    "mp4": "mp4", "mkv": "matroska", "avi": "avi", "mov": "mov",
    "webm": "webm", "flv": "flv", "ts": "mpegts", "m2ts": "mpegts",
    "wmv": "asf", "mpg": "mpeg", "vob": "mpeg", "m4v": "mp4",
    "3gp": "3gp", "ogv": "ogg", "asf": "asf", "gif": "gif",
    "m2ts": "mpegts",
    "mp3": "mp3", "wav": "wav", "flac": "flac",
    "aac": "adts", "ogg": "ogg", "opus": "opus", "m4a": "mp4",
    "ac3": "ac3",
}

class FFmpegManager:
    def __init__(self):
        self.ffmpeg_path: Optional[str] = None
        self.ffprobe_path: Optional[str] = None
        self.available: bool = False
        self.source: str = "未知"
        self.version: str = ""
        self.supported_muxers: set = set()
        self.supported_encoders: set = set()

    @staticmethod
    def _probe_path_capabilities(path: str):
        if not path or not os.path.isfile(path):
            return None
        try:
            import subprocess
            os.environ.pop("LD_LIBRARY_PATH", None)
            os.environ.pop("DYLD_LIBRARY_PATH", None)
            env = os.environ.copy()
            env.pop("LD_LIBRARY_PATH", None)
            env.pop("DYLD_LIBRARY_PATH", None)

            result_v = subprocess.run(
                [path, "-hide_banner", "-version"],
                capture_output=True, text=True, timeout=10, env=env,
                encoding="utf-8", errors="replace"
            )
            if result_v.returncode != 0:
                return None
            version_line = ""
            for line in result_v.stdout.splitlines():
                line = line.strip()
                if line.lower().startswith("ffmpeg version"):
                    version_line = line
                    break
            if not version_line:
                version_line = result_v.stdout.split("\n", 1)[0].strip()

            result_m = subprocess.run(
                [path, "-hide_banner", "-muxers"],
                capture_output=True, text=True, timeout=15, env=env,
                encoding="utf-8", errors="replace"
            )
            muxers = set()
            header_found = False
            for line in result_m.stdout.splitlines():
                if line.startswith(" ---"):
                    header_found = True
                    continue
                if not header_found or len(line) < 4:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    flag = parts[0]
                    if "E" in flag:
                        muxers.add(parts[1])

            result_e = subprocess.run(
                [path, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15, env=env,
                encoding="utf-8", errors="replace"
            )
            encoders = set()
            header_found = False
            for line in result_e.stdout.splitlines():
                if line.startswith(" ---"):
                    header_found = True
                    continue
                if not header_found or len(line) < 4:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    encoders.add(parts[1])

            return {
                "version": version_line,
                "muxers": muxers,
                "encoders": encoders,
            }
        except Exception:
            return None

    def _probe_supported_muxers(self):
        cap = self._probe_path_capabilities(self.ffmpeg_path) if self.ffmpeg_path else None
        if cap is None:
            self.supported_muxers = set()
            self.supported_encoders = set()
            return
        self.version = cap["version"]
        self.supported_muxers = cap["muxers"]
        self.supported_encoders = cap["encoders"]

    def check_output_muxer_supported(self, output_format: str) -> Optional[bool]:
        muxer = FFMPEG_MUXER_FORMAT_MAP.get(output_format)
        if not muxer or not self.supported_muxers:
            return None
        return muxer in self.supported_muxers

    def _collect_candidate_paths(self, custom_path: Optional[str] = None):
        candidates = []
        app_path = get_app_path()
        system = platform.system()
        exe_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"

        if custom_path:
            candidates.append(("自定义", custom_path))

        builtin_root = app_path / "ffmpeg"
        if builtin_root.is_dir():
            flat = builtin_root / exe_name
            if flat.is_file():
                candidates.append(("内置(ffmpeg/)", str(flat)))
            if system == "Windows":
                sub = builtin_root / "windows" / exe_name
                if sub.is_file():
                    candidates.append(("内置(ffmpeg/windows)", str(sub)))
            elif system == "Linux":
                machine = platform.machine().lower()
                subdir = "linux-arm64" if ("aarch64" in machine or "arm64" in machine) else "linux-x64"
                sub = builtin_root / subdir / exe_name
                if sub.is_file():
                    candidates.append((f"内置(ffmpeg/{subdir})", str(sub)))
            elif system == "Darwin":
                sub = builtin_root / "macos" / exe_name
                if sub.is_file():
                    candidates.append(("内置(ffmpeg/macos)", str(sub)))

        sys_which = shutil.which("ffmpeg")
        if sys_which:
            candidates.append(("系统 PATH", sys_which))

        for abs_p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg",
                      "C:/Program Files/FFmpeg/bin/ffmpeg.exe"]:
            if os.path.isfile(abs_p):
                candidates.append((f"已知路径({os.path.dirname(abs_p)})", abs_p))

        return candidates

    def detect_auto(self, custom_path: Optional[str] = None) -> bool:
        candidates = self._collect_candidate_paths(custom_path)
        if not candidates:
            self.available = False
            return False

        scored = []
        for label, path in candidates:
            cap = self._probe_path_capabilities(path)
            if cap is None:
                continue
            m_n = len(cap["muxers"])
            e_n = len(cap["encoders"])
            score = m_n * 50 + e_n
            scored.append((score, label, path, cap))

        if not scored:
            self.available = False
            return False

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_label, top_path, top_cap = scored[0]

        self.ffmpeg_path = top_path
        probe_guess = top_path.replace("ffmpeg", "ffprobe", 1)
        self.ffprobe_path = probe_guess if os.path.isfile(probe_guess) else shutil.which("ffprobe") or top_path
        self.version = top_cap["version"]
        self.supported_muxers = top_cap["muxers"]
        self.supported_encoders = top_cap["encoders"]
        m_n = len(self.supported_muxers)
        e_n = len(self.supported_encoders)
        quality = "完整版" if (m_n >= 80 and e_n >= 80) else ("精简版" if (m_n < 30 or e_n < 30) else "标准版")
        self.source = f"{top_label} · {quality} · {m_n}mux/{e_n}enc"
        self._apply_config_quiet()

        if len(scored) > 1:
            second = scored[1]
            return True
        return True

    def detect_builtin(self) -> bool:
        app_path = get_app_path()
        system = platform.system()
        exe_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
        probe_name = "ffprobe.exe" if system == "Windows" else "ffprobe"

        builtin_dir = app_path / "ffmpeg"
        if system == "Windows":
            builtin_dir = builtin_dir / "windows"
        elif system == "Linux":
            machine = platform.machine().lower()
            builtin_dir = builtin_dir / ("linux-arm64" if ("aarch64" in machine or "arm64" in machine) else "linux-x64")
        elif system == "Darwin":
            builtin_dir = builtin_dir / "macos"

        builtin_ffmpeg = builtin_dir / exe_name
        builtin_ffprobe = builtin_dir / probe_name

        if builtin_ffmpeg.exists():
            cap = self._probe_path_capabilities(str(builtin_ffmpeg))
            if cap is None:
                return False
            if system != "Windows":
                builtin_ffmpeg.chmod(builtin_ffmpeg.stat().st_mode | stat.S_IEXEC)
                if builtin_ffprobe.exists():
                    builtin_ffprobe.chmod(builtin_ffprobe.stat().st_mode | stat.S_IEXEC)
            self.ffmpeg_path = str(builtin_ffmpeg)
            self.ffprobe_path = str(builtin_ffprobe) if builtin_ffprobe.exists() else self.ffmpeg_path
            self.version = cap["version"]
            self.supported_muxers = cap["muxers"]
            self.supported_encoders = cap["encoders"]
            self.source = f"内置 ({system}) · {len(self.supported_muxers)}mux/{len(self.supported_encoders)}enc"
            self._apply_config_quiet()
            return True
        return False

    def detect_custom(self, custom_path: str) -> bool:
        if custom_path and os.path.isfile(custom_path):
            cap = self._probe_path_capabilities(custom_path)
            if cap is None:
                return False
            self.ffmpeg_path = custom_path
            probe_path = custom_path.replace("ffmpeg", "ffprobe", 1)
            self.ffprobe_path = probe_path if os.path.isfile(probe_path) else (shutil.which("ffprobe") or custom_path)
            self.version = cap["version"]
            self.supported_muxers = cap["muxers"]
            self.supported_encoders = cap["encoders"]
            self.source = f"自定义 · {len(self.supported_muxers)}mux/{len(self.supported_encoders)}enc"
            self._apply_config_quiet()
            return True
        return False

    def detect_system(self) -> bool:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg:
            cap = self._probe_path_capabilities(ffmpeg)
            if cap is None:
                return False
            self.ffmpeg_path = ffmpeg
            self.ffprobe_path = ffprobe or ffmpeg
            self.version = cap["version"]
            self.supported_muxers = cap["muxers"]
            self.supported_encoders = cap["encoders"]
            self.source = f"系统 PATH · {len(self.supported_muxers)}mux/{len(self.supported_encoders)}enc"
            self._apply_config_quiet()
            return True
        return False

    def _apply_config_quiet(self):
        if not self.ffmpeg_path:
            return
        try:
            from pydub import AudioSegment
            AudioSegment.converter = self.ffmpeg_path
            AudioSegment.ffmpeg = self.ffmpeg_path
            AudioSegment.ffprobe = self.ffprobe_path
        except ImportError:
            pass
        ffmpeg_dir = str(Path(self.ffmpeg_path).parent)
        current_path = os.environ.get("PATH", "")
        if ffmpeg_dir not in current_path:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path
        self.available = True

    def _apply_config(self):
        self._apply_config_quiet()
        if self.ffmpeg_path and not self.supported_muxers:
            self._probe_supported_muxers()

# ============ 数据类 ============
@dataclass
class ConversionTask:
    input_path: str
    output_path: str
    output_format: str
    bitrate: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    normalize: bool = False

@dataclass
class ConversionResult:
    success: bool
    task: ConversionTask
    message: str
    duration_ms: float = 0.0

# ============ 中文字体 fallback 链 ============
CJK_FONT_FAMILIES = [
    "Noto Sans CJK SC",
    "Source Han Sans CN",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Microsoft YaHei",
    "PingFang SC",
    "SimHei",
    "SimSun",
    "Noto Sans CJK TC",
    "Source Han Sans TW",
]


def _pick_installed_cjk_font_family() -> str:
    try:
        from PySide6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
        for f in CJK_FONT_FAMILIES:
            if f in installed:
                return f
    except Exception:
        pass
    return CJK_FONT_FAMILIES[0]


def get_cjk_font_qss(font_size_px: int = 13, color: Optional[str] = None,
                     extra: Optional[str] = None) -> str:
    families = CJK_FONT_FAMILIES + [
        "Noto Color Emoji", "Apple Color Emoji",
        "Segoe UI Emoji", "Segoe UI Symbol", "Symbola", "sans-serif"
    ]
    family_str = ", ".join(f'"{f}"' for f in families)
    rules = f"font-family: {family_str}; font-size: {font_size_px}px; font-weight: 400;"
    if color:
        rules += f" color: {color};"
    if extra:
        rules += " " + extra.strip()
    if not rules.endswith(";"):
        rules += ";"
    return rules


def apply_global_cjk_font(app, font_size_px: int = 13) -> str:
    try:
        from PySide6.QtWidgets import QStyleFactory
        if "Fusion" in QStyleFactory.keys():
            app.setStyle("Fusion")
    except Exception:
        pass
    family = _pick_installed_cjk_font_family()
    font = QFont(family)
    font.setPixelSize(font_size_px)
    font.setWeight(QFont.Weight.Normal)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferDefault
    )
    if hasattr(app, "setFont"):
        app.setFont(font)
    try:
        default_font = app.font()
        families = [family] + CJK_FONT_FAMILIES[1:] + [
            "Noto Color Emoji", "Apple Color Emoji",
            "Segoe UI Emoji", "Segoe UI Symbol", "Symbola", "sans-serif"
        ]
        default_font.setFamilies(families)
        app.setFont(default_font)
    except Exception:
        pass
    return family

# ============ 转换线程基类 ============
class BaseConversionWorker(QThread):
    progress_signal = Signal(int, int)
    task_started_signal = Signal(str)
    task_finished_signal = Signal(object)
    all_done_signal = Signal()
    single_progress_signal = Signal(int)

    def __init__(self, tasks, ffmpeg_path, supported_muxers=None):
        super().__init__()
        self.tasks = tasks
        self.ffmpeg_path = ffmpeg_path
        self.supported_muxers = supported_muxers if supported_muxers is not None else set()
        self._is_running = True

    def _check_muxer_unsupported(self, output_format: str) -> Optional[str]:
        muxer = FFMPEG_MUXER_FORMAT_MAP.get(output_format)
        if not muxer or not self.supported_muxers:
            return None
        if muxer in self.supported_muxers:
            return None
        return self._format_muxer_hint(output_format, muxer)

    def _enrich_muxer_error_from_stderr(self, base_message: str, stderr_text: str,
                                         output_format: str) -> str:
        if not stderr_text:
            return base_message
        patterns = [
            r"Unable to choose an output format",
            r"Requested output format[^']*'[^']*'\s*is not known",
            r"Error initializing the muxer",
        ]
        import re
        matched = any(re.search(p, stderr_text, re.IGNORECASE) for p in patterns)
        if not matched:
            return base_message
        muxer = FFMPEG_MUXER_FORMAT_MAP.get(output_format, "(unknown)")
        hint = self._format_muxer_hint(output_format, muxer)
        return base_message + "\n\n--- 诊断建议 ---\n" + hint

    def _format_muxer_hint(self, output_format: str, muxer: str) -> str:
        alternatives = [
            f for f, m in FFMPEG_MUXER_FORMAT_MAP.items()
            if m in self.supported_muxers and f in (
                "mp4", "mkv", "avi", "mov", "webm", "flv",
                "mp3", "wav", "flac", "aac", "ogg", "opus", "m4a"
            )
        ]
        if alternatives:
            alt_str = "、".join(f".{a.upper()}" for a in alternatives[:8])
        else:
            alt_str = "MP4 / MKV / MP3 / WAV"
        return (
            f"当前使用的 FFmpeg 是精简版，不支持输出「{output_format.upper()}」格式"
            f" (封装器 muxer='{muxer}' 缺失)。\n"
            f"👉 解决方案：\n"
            f"   1) 换输出格式：推荐 {alt_str}\n"
            f"   2) 换完整版 FFmpeg：安装包含 {muxer} muxer 的官方构建\n"
            f"   3) 或在左侧「⚙️ FFmpeg 设置」里手动指定完整版 ffmpeg 可执行文件路径"
        )

    def run(self):
        total = len(self.tasks)
        for i, task in enumerate(self.tasks):
            if not self._is_running:
                break
            self.progress_signal.emit(i + 1, total)
            self.task_started_signal.emit(os.path.basename(task.input_path))
            result = self._convert_single(task)
            self.task_finished_signal.emit(result)
        self.all_done_signal.emit()

    def _convert_single(self, task):
        raise NotImplementedError("子类必须实现 _convert_single")

    def stop(self):
        self._is_running = False
        self.wait(1000)

# ============ 样式表 ============
def get_main_stylesheet(colors: Optional[dict] = None) -> str:
    c = colors if colors is not None else COLORS
    _fallback = ', '.join(f'"{f}"' for f in CJK_FONT_FAMILIES) + ', "Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji", sans-serif'
    return f"""
        QMainWindow {{
            background-color: {c["bg"]};
        }}
        QWidget {{
            font-family: {_fallback};
            font-size: 13px;
            color: {c["text"]};
        }}
        QGroupBox {{
            background-color: {c["card"]};
            border: 1px solid {c["border"]};
            border-radius: 12px;
            margin-top: 12px;
            padding-top: 16px;
            padding-bottom: 8px;
            padding-left: 16px;
            padding-right: 16px;
            font-weight: bold;
            color: {c["text"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 8px;
            color: {c["success"]};
        }}
        QListWidget {{
            background-color: {c["bg"]};
            border: 1px solid {c["border"]};
            border-radius: 8px;
            padding: 8px;
            outline: none;
        }}
        QListWidget::item {{
            background-color: {c["card"]};
            border-radius: 6px;
            padding: 8px;
            margin: 4px 0px;
            color: {c["text"]};
        }}
        QListWidget::item:selected {{
            background-color: {c["border"]};
            border: 1px solid {c["success"]};
        }}
        QListWidget::item:hover {{
            background-color: {c["card_hover"]};
        }}
        QPushButton {{
            background-color: {c["card"]};
            border: 1px solid {c["border"]};
            border-radius: 8px;
            padding: 8px 16px;
            color: {c["text"]};
            font-weight: 400;
        }}
        QPushButton:hover {{
            background-color: {c["card_hover"]};
            border-color: {c["success"]};
        }}
        QPushButton:pressed {{
            background-color: {c["border"]};
        }}
        QPushButton:disabled {{
            background-color: {c["btn_disabled_bg"]};
            color: {c["btn_disabled_text"]};
            border-color: {c["btn_disabled_border"]};
        }}
        QComboBox {{
            background-color: {c["bg"]};
            border: 1px solid {c["border"]};
            border-radius: 6px;
            padding: 6px 12px;
            min-width: 160px;
            color: {c["text"]};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {c["card"]};
            border: 1px solid {c["border"]};
            border-radius: 6px;
            selection-background-color: {c["border"]};
            padding: 4px;
        }}
        QLineEdit {{
            background-color: {c["bg"]};
            border: 1px solid {c["border"]};
            border-radius: 6px;
            padding: 6px 12px;
            color: {c["text"]};
        }}
        QLineEdit:focus {{
            border-color: {c["success"]};
        }}
        QProgressBar {{
            background-color: {c["bg"]};
            border: 1px solid {c["border"]};
            border-radius: 6px;
            text-align: center;
            color: {c["text"]};
            height: 20px;
        }}
        QProgressBar::chunk {{
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0 {c["success"]},
                stop: 1 {c["accent"]}
            );
            border-radius: 5px;
        }}
        QTextEdit {{
            background-color: {c["bg"]};
            border: 1px solid {c["border"]};
            border-radius: 8px;
            padding: 12px;
            color: {c["text"]};
            font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
            font-size: 12px;
        }}
        QCheckBox {{
            spacing: 8px;
            color: {c["text_secondary"]};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {c["border"]};
            background-color: {c["bg"]};
        }}
        QCheckBox::indicator:checked {{
            background-color: {c["success"]};
            border-color: {c["success"]};
        }}
        QMenu {{
            background-color: {c["card"]};
            border: 1px solid {c["border"]};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 8px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {c["border"]};
        }}
        QSplitter::handle {{
            background-color: {c["border"]};
        }}
        QScrollBar:vertical {{
            background-color: {c["bg"]};
            width: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {c["border"]};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {c["success"]};
        }}
        QLabel#titleLabel {{
            font-size: 26px;
            font-weight: bold;
            color: {c["text"]};
        }}
        QLabel#subtitleLabel {{
            font-size: 13px;
            color: {c["text_secondary"]};
        }}
        QLabel#hintLabel {{
            font-size: 12px;
            color: {c["text_secondary"]};
            padding: 4px 0;
        }}

        /* 针对左侧导航栏的特殊样式 */
        QListWidget#navList {{
            background-color: {c["bg"]};
            border: none;
            outline: none;
            padding-top: 20px;
        }}
        QListWidget#navList::item {{
            background-color: transparent;
            border-radius: 8px;
            padding: 12px 20px;
            margin: 4px 12px;
            font-size: 15px;
            font-weight: 400;
            color: {c["text"]};
        }}
        QListWidget#navList::item:selected {{
            background-color: {c["card"]};
            border: 1px solid {c["border"]};
            color: {c["success"]};
        }}
        QListWidget#navList::item:hover {{
            background-color: {c["card_hover"]};
            color: {c["text"]};
        }}
    """


class ThemeManager(QObject):
    """全局主题管理器（单例），负责切换主题、分发 theme_changed 信号。"""
    _instance: Optional["ThemeManager"] = None
    theme_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme: str = "dark"

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    @property
    def current_theme(self) -> str:
        return self._current_theme

    @property
    def current_colors(self) -> dict:
        return get_colors_for_theme(self._current_theme)

    def apply_theme(self, app, theme_name: str) -> dict:
        name = (theme_name or "dark").lower()
        if name not in ("dark", "light"):
            name = "dark"
        colors = get_colors_for_theme(name)
        self._current_theme = name
        try:
            app.setStyleSheet(get_main_stylesheet(colors))
        except Exception:
            pass
        self.theme_changed.emit(colors)
        return colors