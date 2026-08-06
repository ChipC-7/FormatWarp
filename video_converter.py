
import os
import sys
import subprocess
import re
from collections import deque
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QTextEdit, QGroupBox, QMessageBox, QMenu, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QStandardPaths, QTime, QRectF, QSize
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QPixmap, QPainter, QColor, QPen, QBrush,
    QPainterPath, QIcon
)
from utils import BaseConversionWorker, get_cjk_font_qss, ThemeManager, hex_with_alpha

# 视频专用配置 (大幅扩充)
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

INPUT_VIDEO_FORMATS = [
    "mp4", "mkv", "avi", "mov", "webm", "flv", "ts", "wmv", "mpg", "mpeg", "m4v",
    "3gp", "ogv", "vob", "asf", "m2ts", "rmvb", "rm", "divx", "f4v"
]

class VideoConversionTask:
    def __init__(self, input_path, output_path, output_format, video_bitrate=None, audio_bitrate=None, extract_audio=False, hardware_accel=None):
        self.input_path = input_path
        self.output_path = output_path
        self.output_format = output_format
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.extract_audio = extract_audio
        self.hardware_accel = hardware_accel  # None=自动, "cpu"=CPU, "nvenc"/"qsv"/"amf"/"vtb"=硬件加速

class VideoConversionResult:
    def __init__(self, success, task, message):
        self.success = success
        self.task = task
        self.message = message

class VideoConversionWorker(BaseConversionWorker):
    def _build_cmd(self, task: VideoConversionTask, stream_copy: bool):
        cmd = [self.ffmpeg_path, "-i", task.input_path, "-y"]
        alias_table = None
        if task.extract_audio:
            cmd.extend(["-vn"])
            if task.audio_bitrate:
                cmd.extend(["-b:a", task.audio_bitrate])
            alias_table = EXTRACT_AUDIO_FORMAT_ALIAS_TO_REAL_EXT
        else:
            alias_table = VIDEO_FORMAT_ALIAS_TO_REAL_EXT
            if task.output_format == "gif":
                cmd.extend(["-vf", "fps=15,scale=480:-1:flags=lanczos", "-loop", "0"])
            elif stream_copy:
                cmd.extend(["-c", "copy", "-map", "0"])
            else:
                # ===== GPU 硬件加速 =====
                hw = task.hardware_accel
                gpu_encoder = self._resolve_gpu_encoder(hw)
                if gpu_encoder:
                    cmd.extend(["-c:v", gpu_encoder])
                    if task.video_bitrate:
                        cmd.extend(["-b:v", task.video_bitrate])
                    else:
                        cmd.extend(["-cq", "23"])
                    cmd.extend(["-preset", "p4", "-rc", "vbr"])
                elif task.video_bitrate:
                    cmd.extend(["-b:v", task.video_bitrate])
                else:
                    if task.output_format in ["mp4", "mkv", "mov"]:
                        cmd.extend(["-crf", "23", "-preset", "medium"])
                    elif task.output_format == "webm":
                        cmd.extend(["-crf", "30", "-b:v", "0"])
        return cmd, alias_table

    @staticmethod
    def _resolve_gpu_encoder(hw_key: str) -> str:
        """将 hardware_accel key 映射为 FFmpeg 编码器名。"""
        mapping = {
            "nvenc": "h264_nvenc",
            "qsv":   "h264_qsv",
            "amf":   "h264_amf",
            "vtb":   "h264_videotoolbox",
        }
        return mapping.get(hw_key, "")

    def _can_stream_copy(self, task: VideoConversionTask) -> bool:
        if task.extract_audio:
            return not task.audio_bitrate
        if task.output_format == "gif":
            return False
        return not task.video_bitrate

    def _run_ffmpeg_with_cancel(self, cmd, temp_output_path, _final_output_path, need_rename):
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace'
        )

        duration = self._get_media_duration(cmd[2])
        progress_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        duration_regex = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")

        last_percent = -1
        stderr_tail = deque(maxlen=10)

        for line in process.stderr:
            stderr_tail.append(line.rstrip())

            if not self._is_running:
                process.terminate()
                if need_rename and os.path.exists(temp_output_path):
                    try:
                        os.remove(temp_output_path)
                    except OSError:
                        pass
                return "cancelled", None, stderr_tail

            if duration <= 0:
                dmatch = duration_regex.search(line)
                if dmatch:
                    dh, dm, ds = map(float, dmatch.groups())
                    duration = dh * 3600 + dm * 60 + ds

            match = progress_regex.search(line)
            if match and duration > 0:
                h, m, s = map(float, match.groups())
                current_time = h * 3600 + m * 60 + s
                percent = min(99, int((current_time / duration) * 100))
                if percent != last_percent:
                    self.single_progress_signal.emit(percent)
                    last_percent = percent

        process.wait()
        return process.returncode, duration, stderr_tail

    def _extract_encoder_hint_from_stderr(self, stderr_text: str, output_format: str) -> str:
        patterns = [
            r"Automatic encoder selection failed",
            r"is probably disabled.*Please choose an encoder manually",
            r"Error selecting an encoder",
            r"Encoder not found",
            r"Unrecognized codec option",
            r"codec.*not found",
        ]
        import re
        matched = any(re.search(p, stderr_text, re.IGNORECASE) for p in patterns)
        if not matched:
            return ""
        return (
            "\n\n--- 编码器缺失诊断 ---\n"
            f"当前 FFmpeg 是精简版，缺少「{output_format.upper()}」格式所需的编码器。\n"
            f"👉 解决方案：\n"
            f"   1) 推荐用完整版 FFmpeg：apt install ffmpeg 或下载官方构建\n"
            f"   2) 或在 FFmpeg 设置里手动指定完整版 ffmpeg 路径\n"
            f"   3) 或改用 MP4/MKV 等常见格式（精简版一般保留这些格式的编码器）"
        )

    # GPU 错误关键词：匹配硬件编码器初始化失败、设备不可用等
    GPU_ERROR_PATTERNS = [
        "No capable devices found",
        "InitializeEncoder failed",
        "Cannot load nvcuda",
        "dll.*not found",
        "AMF",
        "Error initializing an encoder",
        "encoder.*not found",
        "Invalid data found when processing the input",
        "hw_device_ctx",
        "No device available",
        "failed to create encoder",
        "Cannot load",
    ]

    @classmethod
    def _is_gpu_failure(cls, stderr_text: str) -> bool:
        """判断 stderr 是否包含 GPU 编码失败的特征。"""
        if not stderr_text:
            return False
        import re
        for pattern in cls.GPU_ERROR_PATTERNS:
            if re.search(pattern, stderr_text, re.IGNORECASE):
                return True
        return False

    def _convert_single(self, task: VideoConversionTask) -> VideoConversionResult:
        try:
            unsupported_hint = self._check_muxer_unsupported(task.output_format)
            if unsupported_hint:
                return VideoConversionResult(
                    False, task,
                    "FFmpeg 封装器缺失（预检查拦截，未启动转换）：\n" + unsupported_hint
                )

            attempts = []
            if self._can_stream_copy(task):
                attempts.append(("stream_copy", True, None))
            # GPU 编码尝试
            if task.hardware_accel and task.hardware_accel not in ("cpu",):
                attempts.append(("encode_gpu", False, task.hardware_accel))
            # CPU 编码兜底
            attempts.append(("encode_cpu", False, None))

            last_error = None
            last_tail = None
            gpu_failed = False
            gpu_fallback_note = ""

            for mode_name, stream_copy, hw_override in attempts:
                # GPU 失败后回退：覆盖为 CPU
                effective_task = task
                if hw_override is None and gpu_failed:
                    effective_task = VideoConversionTask(
                        task.input_path, task.output_path, task.output_format,
                        task.video_bitrate, task.audio_bitrate, task.extract_audio,
                        hardware_accel=None
                    )
                elif hw_override is not None:
                    effective_task = VideoConversionTask(
                        task.input_path, task.output_path, task.output_format,
                        task.video_bitrate, task.audio_bitrate, task.extract_audio,
                        hardware_accel=hw_override
                    )

                base_cmd, alias_table = self._build_cmd(effective_task, stream_copy)

                real_ext = alias_table.get(task.output_format)
                final_output_path = task.output_path
                temp_output_path = final_output_path
                need_rename = False

                if real_ext and not final_output_path.lower().endswith(real_ext.lower()):
                    base_no_ext = os.path.splitext(final_output_path)[0]
                    temp_output_path = base_no_ext + real_ext
                    need_rename = True
                    if os.path.exists(temp_output_path):
                        try:
                            os.remove(temp_output_path)
                        except OSError:
                            pass

                cmd = list(base_cmd)
                cmd.append(temp_output_path)

                status, _d, stderr_tail = self._run_ffmpeg_with_cancel(
                    cmd, temp_output_path, final_output_path, need_rename
                )

                if status == "cancelled":
                    return VideoConversionResult(False, task, "用户取消")

                if status == 0:
                    if need_rename:
                        try:
                            if os.path.exists(final_output_path):
                                os.remove(final_output_path)
                            os.replace(temp_output_path, final_output_path)
                        except OSError as e:
                            return VideoConversionResult(
                                False, task,
                                f"转换成功，但重命名失败: {temp_output_path} → {final_output_path}: {e}"
                            )
                    if mode_name == "stream_copy":
                        return VideoConversionResult(
                            True, task, "转换成功（-c copy 流直拷，无损且快速）"
                        )
                    msg = "转换成功"
                    if gpu_failed:
                        msg += "（硬件加速失败，已自动降级为 CPU 编码）"
                    return VideoConversionResult(True, task, msg)
                else:
                    last_error = status
                    last_tail = stderr_tail
                    # 检测 GPU 失败，标记以便下次回退
                    if mode_name == "encode_gpu" and self._is_gpu_failure("\n".join(stderr_tail)):
                        gpu_failed = True
                        continue
                    # 非 GPU 失败或已回退过，不再重试
                    if gpu_failed and mode_name == "encode_cpu":
                        break

            tail_msg = "\n".join(last_tail).strip() or "(无详细输出)"
            base_err = (
                f"FFmpeg 错误 (代码: {last_error})\n"
                f"(已尝试 {len(attempts)} 种策略：{', '.join(m for m, _, _ in attempts)})\n"
                f"--- stderr 末尾 ---\n{tail_msg}"
            )
            full_err = self._enrich_muxer_error_from_stderr(
                base_err, "\n".join(last_tail), task.output_format
            )
            enc_hint = self._extract_encoder_hint_from_stderr(
                "\n".join(last_tail), task.output_format
            )
            full_err += enc_hint
            if gpu_failed:
                full_err += "\n\n⚠️ 硬件加速编码失败，已自动降级为 CPU 编码，但 CPU 编码也失败了。"
            return VideoConversionResult(False, task, full_err)
        except Exception as e:
            return VideoConversionResult(False, task, str(e))

    def _get_media_duration(self, path: str) -> float:
        try:
            ffprobe_path = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
            cmd = [
                ffprobe_path, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return float(result.stdout.strip())
        except Exception:
            return 0.0

class VideoConverterWidget(QWidget):
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
        self._module_name = "🎬 视频"
        self._setup_ui()
        self._apply_widget_styles()
        if self._default_output_dir and not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_dir)

    def _setup_ui(self):
        c = self.theme_colors
        # 设置全局布局约束
        self.setMinimumWidth(700)
        self.resize(1000, 700)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # === 标题区域 ===
        title_label = QLabel("🎬 视频格式转换")
        title_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {self.theme_colors['text']};")
        subtitle_label = QLabel("支持 16 种视频格式互转，支持提取音频，支持视频转 GIF 动图")
        subtitle_label.setStyleSheet(f"font-size: 13px; color: {self.theme_colors['text_secondary']};")
        
        title_layout = QVBoxLayout()
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        title_layout.setSpacing(4)
        layout.addLayout(title_layout)

        # === 主内容区 ===

        # --- 上半部分 ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        # 文件列表
        file_group = QGroupBox("待转换文件")
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
        self.file_list.setDragEnabled(True)
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
        self.add_btn = QPushButton("➕ 添加文件")
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

        # 转换设置 (核心修复区)
        settings_group = QGroupBox("转换设置")
        settings_group.setMinimumWidth(420)  # 防止布局崩溃的底线
        settings_group.setStyleSheet(f"""
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
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(16)

        # 通用控件样式
        input_style = f"""
            QComboBox, QLineEdit {{
                background-color: {self.theme_colors['bg']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 4px;
                padding: 6px 10px;
                color: {self.theme_colors['text']};
                min-height: 24px;
            }}
            QComboBox:hover, QLineEdit:hover, QComboBox:focus, QLineEdit:focus {{
                border: 1px solid {self.theme_colors['primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {self.theme_colors['card']};
                border: 1px solid {self.theme_colors['border']};
                selection-background-color: {self.theme_colors['primary']};
                color: {self.theme_colors['text']};
            }}
        """

        # 👇 核心修复：定义抗挤压设置行函数
        def create_setting_row(label_text: str, widget):
            """创建抗挤压设置行（核心修复）"""
            row_layout = QHBoxLayout()
            row_layout.setSpacing(12)
            
            # 左侧标签：强制固定宽度 + 中文字体兜底
            label = QLabel(label_text)
            label.setStyleSheet(
                get_cjk_font_qss(
                    font_size_px=14,
                    color=self.theme_colors['text'],
                    extra="font-weight: 400;"
                )
            )
            label.setMinimumWidth(85)  # 安全阈值
            label.setMaximumWidth(100)  # 防止过宽
            label.setSizePolicy(
                QSizePolicy.Policy.Fixed,  # 👈 关键！固定宽度
                QSizePolicy.Policy.Preferred
            )
            
            # 右侧控件：限制伸缩权重
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, 
                QSizePolicy.Policy.Preferred
            )
            
            row_layout.addWidget(label)
            row_layout.addWidget(widget, 1)  # 1=权重，防止右侧控件占满
            
            return row_layout

        # 输出格式
        self.format_combo = QComboBox()
        self.format_combo.setStyleSheet(input_style)
        for key, info in SUPPORTED_VIDEO_FORMATS.items():
            self.format_combo.addItem(info["desc"], key)
        settings_layout.addLayout(create_setting_row("输出格式", self.format_combo))

        # 输出目录
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("默认与源文件同目录")
        self.output_path_edit.setStyleSheet(input_style)
        self.output_browse_btn = QPushButton("浏览")
        self.output_browse_btn.setFixedWidth(70)
        self.output_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_colors['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton:hover {{
                background-color: {self.theme_colors['primary_hover']};
            }}
        """)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)
        
        output_layout = QHBoxLayout()
        output_layout.setSpacing(12)
        output_label = QLabel("输出目录")
        output_label.setStyleSheet(f"color: {self.theme_colors['text_secondary']}; font-size: 13px;")
        output_label.setMinimumWidth(85)
        output_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred
        )
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_path_edit, 1)
        output_layout.addWidget(self.output_browse_btn)
        settings_layout.addLayout(output_layout)

        # 视频比特率
        self.v_bitrate_combo = QComboBox()
        self.v_bitrate_combo.setStyleSheet(input_style)
        for name, value in VIDEO_BITRATE_PRESETS.items():
            self.v_bitrate_combo.addItem(name, value)
        settings_layout.addLayout(create_setting_row("视频码率", self.v_bitrate_combo))

        # 硬件加速开关 + 下拉框
        self.hwaccel_check = QCheckBox("启用硬件加速 (GPU)")
        self.hwaccel_check.setChecked(True)
        self.hwaccel_check.setCursor(Qt.PointingHandCursor)
        self.hwaccel_check.toggled.connect(self._on_hwaccel_toggled)
        settings_layout.addLayout(create_setting_row("", self.hwaccel_check))

        self.hwaccel_combo = QComboBox()
        self.hwaccel_combo.setStyleSheet(input_style)
        settings_layout.addLayout(create_setting_row("选择加速引擎", self.hwaccel_combo))

        # GPU 提示标签
        self.hwaccel_hint = QLabel("")
        self.hwaccel_hint.setStyleSheet(
            f"color: {self.theme_colors['text_secondary']}; font-size: 11px; padding: 0 0 4px 0;"
        )
        self.hwaccel_hint.setWordWrap(True)
        settings_layout.addWidget(self.hwaccel_hint)

        # 创建完 hwaccel_hint 后再填充下拉框（_populate_hwaccel_combo 会更新提示）
        self._populate_hwaccel_combo()

        # 提取音频选项
        def _make_checkbox_icon_pixmap(checked: bool, accent_hex: str, size=22, radius=5):
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
                p.setBrush(QBrush(QColor(self.theme_colors['bg'])))
                pen = QPen(QColor(self.theme_colors['border']))
                pen.setWidth(2)
                p.setPen(pen)
                path = QPainterPath()
                path.addRoundedRect(QRectF(1.0, 1.0, size - 2, size - 2), radius, radius)
                p.drawPath(path)
            p.end()
            return pm

        self.extract_audio_check = QPushButton(
            QIcon(_make_checkbox_icon_pixmap(False, self.theme_colors['accent'])),
            "  仅提取音频 (忽略视频画面)"
        )
        self.extract_audio_check.setCheckable(True)
        self.extract_audio_check.setIconSize(QSize(22, 22))
        self.extract_audio_check.setCursor(Qt.PointingHandCursor)
        self.extract_audio_check.setStyleSheet(f"""
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

        def _on_extract_toggled_icon(checked: bool):
            self.extract_audio_check.setIcon(
                QIcon(_make_checkbox_icon_pixmap(checked, self.theme_colors['accent']))
            )
        self.extract_audio_check.toggled.connect(_on_extract_toggled_icon)
        self.extract_audio_check.toggled.connect(self._toggle_extract_audio)
        self.hwaccel_combo.currentIndexChanged.connect(lambda _: self._update_hwaccel_hint())
        
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addSpacing(97)
        checkbox_layout.addWidget(self.extract_audio_check)
        checkbox_layout.addStretch()
        settings_layout.addLayout(checkbox_layout)

        # 音频比特率 (默认隐藏)
        self.a_bitrate_widget = QWidget()
        a_bitrate_layout = QHBoxLayout(self.a_bitrate_widget)
        a_bitrate_layout.setContentsMargins(0, 0, 0, 0)
        self.a_bitrate_combo = QComboBox()
        self.a_bitrate_combo.setStyleSheet(input_style)
        for name, value in AUDIO_BITRATE_PRESETS.items():
            self.a_bitrate_combo.addItem(name, value)
        settings_layout.addLayout(create_setting_row("音频码率", self.a_bitrate_widget))
        self.a_bitrate_widget.hide()

        settings_layout.addStretch()
        top_layout.addWidget(settings_group, 2)
        layout.addWidget(top_widget, 1)

        # === 底部操作栏 ===
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

    # === 事件处理 ===

    def _populate_hwaccel_combo(self):
        """根据 FFmpeg 检测到的硬件编码器填充下拉框。"""
        self.hwaccel_combo.blockSignals(True)
        self.hwaccel_combo.clear()
        if not self.hwaccel_check.isChecked():
            # 未启用 GPU 加速时，只显示 CPU 选项
            self.hwaccel_combo.addItem("CPU 软件编码", "cpu")
            self.hwaccel_combo.setEnabled(False)
        else:
            self.hwaccel_combo.addItem("自动选择 (推荐)", None)
            self.hwaccel_combo.addItem("CPU 软件编码", "cpu")
            if self.ffmpeg_mgr and self.ffmpeg_mgr.available:
                gpu_encs = self.ffmpeg_mgr.detect_gpu_encoders()
                for key, display_name in gpu_encs.items():
                    self.hwaccel_combo.addItem(f"{display_name} (已就绪)", key)
            self.hwaccel_combo.setEnabled(True)
        self.hwaccel_combo.blockSignals(False)
        self._update_hwaccel_hint()

    def _on_hwaccel_toggled(self, checked: bool):
        """GPU 加速开关切换。"""
        self._populate_hwaccel_combo()

    def _update_hwaccel_hint(self):
        """根据当前选择更新 GPU 提示文案。"""
        if not self.hwaccel_check.isChecked():
            self.hwaccel_hint.setText("硬件加速已关闭，将使用 CPU 软件编码")
            return
        data = self.hwaccel_combo.currentData()
        if data is None:
            gpu_encs = self.ffmpeg_mgr.detect_gpu_encoders() if self.ffmpeg_mgr and self.ffmpeg_mgr.available else {}
            if gpu_encs:
                self.hwaccel_hint.setText(f"💡 检测到 {', '.join(gpu_encs.values())} 硬件，已自动开启加速；转换失败将自动降级为 CPU 编码")
            else:
                self.hwaccel_hint.setText("💡 未检测到可用硬件编码器，将使用 CPU 软件编码")
        elif data == "cpu":
            self.hwaccel_hint.setText("使用 CPU 软件编码，兼容性最好但速度较慢")
        else:
            self.hwaccel_hint.setText("💡 硬件加速模式下转换速度可提升 5-20 倍；如转换失败将自动降级为 CPU 编码")

    def _toggle_extract_audio(self, checked):
        self.a_bitrate_widget.setVisible(checked)
        self.v_bitrate_combo.setEnabled(not checked)
        # 提取音频时禁用 GPU 选项
        self.hwaccel_check.setEnabled(not checked)
        self.hwaccel_combo.setEnabled(not checked and self.hwaccel_check.isChecked())
        if checked:
            self.hwaccel_hint.setText("提取音频时无需视频编码，硬件加速已自动禁用")
        else:
            self._update_hwaccel_hint()
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        if checked:
            for key, info in EXTRACT_AUDIO_FORMATS.items():
                self.format_combo.addItem(info["desc"], key)
        else:
            for key, info in SUPPORTED_VIDEO_FORMATS.items():
                self.format_combo.addItem(info["desc"], key)
        self.format_combo.blockSignals(False)

    def _drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._add_file(path)

    def _add_files(self):
        exts = " ".join(f"*.{e}" for e in INPUT_VIDEO_FORMATS)
        filter_str = f"视频文件 ({exts});;所有文件 (*)"
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频文件", "", filter_str)
        if not files:
            files, _ = QFileDialog.getOpenFileNames(self, "选择视频文件", "", "所有文件 (*)")
        for f in files:
            self._add_file(f)

    def _add_file(self, path: str):
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole) == path:
                return
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        icon = "🎬" if ext in INPUT_VIDEO_FORMATS else "📁"
        item = QListWidgetItem(f"  {icon}  {os.path.basename(path)}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.file_list.addItem(item)

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _open_in_explorer(self, path: str):
        if not os.path.isdir(path):
            return
        if os.name == 'nt':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_path_edit.setText(path)

    def _open_output_dir(self):
        path = self.output_path_edit.text().strip()
        if not path:
            path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        self._open_in_explorer(path)

    def _show_file_context_menu(self, position):
        menu = QMenu()
        remove_action = menu.addAction("➖  移除")
        action = menu.exec(self.file_list.mapToGlobal(position))
        if action == remove_action:
            self._remove_selected()

    def _clear_files(self):
        self.file_list.clear()

    def _build_tasks(self):
        tasks = []
        output_format = self.format_combo.currentData()
        output_dir = self.output_path_edit.text().strip()
        video_bitrate = self.v_bitrate_combo.currentData()
        extract_audio = self.extract_audio_check.isChecked()
        audio_bitrate = self.a_bitrate_combo.currentData() if extract_audio else None
        hardware_accel = None
        if not extract_audio and self.hwaccel_check.isChecked():
            hardware_accel = self.hwaccel_combo.currentData()

        if extract_audio:
            ext = EXTRACT_AUDIO_FORMATS[output_format]["ext"]
        else:
            ext = SUPPORTED_VIDEO_FORMATS[output_format]["ext"]

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

            counter = 1
            original_out = out_path
            while os.path.exists(out_path):
                base_name = os.path.splitext(os.path.basename(original_out))[0]
                out_path = os.path.join(
                    os.path.dirname(original_out),
                    f"{base_name}_{counter}{ext}"
                )
                counter += 1

            tasks.append(VideoConversionTask(
                input_path=input_path,
                output_path=out_path,
                output_format=output_format,
                video_bitrate=video_bitrate,
                audio_bitrate=audio_bitrate,
                extract_audio=extract_audio,
                hardware_accel=hardware_accel
            ))
        return tasks

    def _start_conversion(self):
        if not self.ffmpeg_mgr.available:
            QMessageBox.warning(self, "FFmpeg 未就绪", "未检测到 FFmpeg，转换功能不可用。")
            return
        if self.file_list.count() == 0:
            QMessageBox.information(self, "提示", "请先添加要转换的视频文件。")
            return

        tasks = self._build_tasks()
        total = len(tasks)

        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = VideoConversionWorker(
            tasks,
            self.ffmpeg_mgr.ffmpeg_path,
            self.ffmpeg_mgr.supported_muxers
        )
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.task_started_signal.connect(self._on_task_started)
        self.worker.task_finished_signal.connect(self._on_task_finished)
        self.worker.all_done_signal.connect(self._on_all_done)
        self.worker.single_progress_signal.connect(self._on_single_progress)
        self.worker.start()

        output_format = self.format_combo.currentData()
        self.log_signal.emit(
            "info",
            f"🎬 视频转换启动：共 {total} 个文件 → 输出格式 {str(output_format or '').upper()}"
        )

    def _stop_conversion(self):
        if self.worker:
            self.worker.stop()
            self.log_signal.emit("warning", "🎬 视频转换已被用户停止")

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        pass

    @Slot(str)
    def _on_task_started(self, filename: str):
        self._current_task_filename = filename
        self.task_monitor_signal.emit(filename)
        self.log_signal.emit("info", f"🎬 正在转换: {filename}")
        self.task_progress_signal.emit(self._module_name, filename, 0)

    @Slot(int)
    def _on_single_progress(self, progress: int):
        if self._current_task_filename:
            self.task_progress_signal.emit(
                self._module_name, self._current_task_filename, progress
            )

    @Slot(object)
    def _on_task_finished(self, result):
        basename = os.path.basename(getattr(result.task, "input_path", ""))
        full_path = getattr(result.task, "input_path", "")
        filename = basename if basename else os.path.basename(full_path) or ""
        msg = (getattr(result, "message", "") or "").strip()
        first_line = msg.splitlines()[0] if msg else ""
        if len(first_line) > 120:
            first_line = first_line[:117] + "..."
        success = bool(getattr(result, "success", False))
        if success:
            self.log_signal.emit("success", f"🎬 {basename} — {first_line or '转换成功'}")
        else:
            self.log_signal.emit("error", f"🎬 {basename} — {first_line or '转换失败'}")
        self.task_result_signal.emit(self._module_name, filename, success, msg)

    @Slot()
    def _on_all_done(self):
        if self._current_task_filename:
            self.task_progress_signal.emit(
                self._module_name, self._current_task_filename, 100
            )
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._current_task_filename = ""
        self.task_monitor_signal.emit("")
        self.log_signal.emit("info", "🎬 视频转换全部完成")
        QMessageBox.information(self, "完成", "所有转换任务已处理完毕！")

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

    def _refresh_extract_audio_icon(self):
        c = self.theme_colors
        checked = self.extract_audio_check.isChecked()
        self.extract_audio_check.setIcon(
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
        self._refresh_extract_audio_icon()

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
            QComboBox, QLineEdit {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 6px 10px;
                color: {c['text']};
                min-height: 24px;
            }}
            QComboBox:hover, QLineEdit:hover, QComboBox:focus, QLineEdit:focus {{
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
        for w in (self.format_combo, self.v_bitrate_combo,
                  self.a_bitrate_combo, self.output_path_edit,
                  self.hwaccel_combo):
            try:
                w.setStyleSheet(input_style)
            except Exception:
                pass

        # --- 浏览按钮 ---
        self.output_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton:hover {{
                background-color: {c['primary_hover']};
            }}
        """)

        # --- 仅提取音频按钮 ---
        self.extract_audio_check.setStyleSheet(f"""
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

        # --- GPU 提示标签 ---
        self.hwaccel_hint.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 11px; padding: 0 0 4px 0;"
        )

        # --- 硬件加速复选框 ---
        self.hwaccel_check.setStyleSheet(f"""
            QCheckBox {{
                color: {c['text']};
                font-size: 14px;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid {c['border']};
                background-color: {c['card']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {c['accent']};
                border-color: {c['accent']};
                image: none;
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