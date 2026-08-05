
import os
import sys
import subprocess
import re
from collections import deque
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QTextEdit, QGroupBox, QSplitter, QMessageBox, QMenu, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QStandardPaths, QTime, QRectF, QSize
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QPixmap, QPainter, QColor, QPen, QBrush,
    QPainterPath, QIcon
)
from utils import COLORS, ConversionTask, ConversionResult, BaseConversionWorker, get_cjk_font_qss, ThemeManager

# 音频专用配置 (大幅扩充)
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

INPUT_AUDIO_FORMATS = [
    "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus",
    "aiff", "aif", "amr", "ape", "au", "ac3", "dts", "tta", "wv", "mp2", "spx"
]

class AudioConversionWorker(BaseConversionWorker):
    def _build_cmd(self, task: ConversionTask, stream_copy: bool):
        cmd = [self.ffmpeg_path, "-i", task.input_path, "-y"]
        if stream_copy:
            cmd.extend(["-c", "copy", "-map", "0"])
        else:
            if task.sample_rate:
                cmd.extend(["-ar", str(task.sample_rate)])
            if task.channels:
                cmd.extend(["-ac", str(task.channels)])
            if task.normalize:
                cmd.extend(["-af", "loudnorm=I=-16:LRA=11:TP=-1.5"])
            if task.bitrate:
                cmd.extend(["-b:a", task.bitrate])
            cmd.extend(["-f", task.output_format])
        return cmd

    def _can_stream_copy(self, task: ConversionTask) -> bool:
        if task.sample_rate or task.channels or task.normalize or task.bitrate:
            return False
        return True

    def _run_ffmpeg_with_cancel(self, cmd):
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )

        progress_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        duration_regex = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
        duration = 0.0
        last_percent = -1
        stderr_tail = deque(maxlen=10)

        for line in process.stderr:
            stderr_tail.append(line.rstrip())

            if not self._is_running:
                process.terminate()
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
            f"   3) 或改用 MP3/WAV 等常见格式（精简版一般保留这些格式的编码器）"
        )

    def _convert_single(self, task: ConversionTask) -> ConversionResult:
        try:
            unsupported_hint = self._check_muxer_unsupported(task.output_format)
            if unsupported_hint:
                return ConversionResult(
                    success=False,
                    task=task,
                    message="FFmpeg 封装器缺失（预检查拦截，未启动转换）：\n" + unsupported_hint
                )

            attempts = []
            if self._can_stream_copy(task):
                attempts.append(("stream_copy", True))
            attempts.append(("encode", False))

            last_error = None
            last_tail = None
            last_duration = 0.0
            for mode_name, stream_copy in attempts:
                cmd = self._build_cmd(task, stream_copy)
                cmd.append(task.output_path)

                status, duration, stderr_tail = self._run_ffmpeg_with_cancel(cmd)
                if status == "cancelled":
                    return ConversionResult(False, task, "用户取消")
                if duration and duration > last_duration:
                    last_duration = duration

                if status == 0:
                    if mode_name == "stream_copy":
                        return ConversionResult(
                            success=True,
                            task=task,
                            message="转换成功（-c copy 流直拷，无损且快速）",
                            duration_ms=(duration or 0.0) * 1000.0
                        )
                    return ConversionResult(
                        success=True,
                        task=task,
                        message="转换成功",
                        duration_ms=(duration or 0.0) * 1000.0
                    )
                else:
                    last_error = status
                    last_tail = stderr_tail

            tail_msg = "\n".join(last_tail).strip() or "(无详细输出)"
            base_err = (
                f"FFmpeg 错误 (代码: {last_error})\n"
                f"(已尝试 {len(attempts)} 种策略：{', '.join(m for m, _ in attempts)})\n"
                f"--- stderr 末尾 ---\n{tail_msg}"
            )
            full_err = self._enrich_muxer_error_from_stderr(
                base_err, "\n".join(last_tail), task.output_format
            )
            enc_hint = self._extract_encoder_hint_from_stderr(
                "\n".join(last_tail), task.output_format
            )
            full_err += enc_hint
            return ConversionResult(
                success=False,
                task=task,
                message=full_err
            )
        except Exception as e:
            return ConversionResult(
                success=False,
                task=task,
                message=str(e)
            )

class AudioConverterWidget(QWidget):
    task_monitor_signal = Signal(str)
    log_signal = Signal(str, str)
    def __init__(self, ffmpeg_mgr, default_output_dir: str = ""):
        super().__init__()
        self.ffmpeg_mgr = ffmpeg_mgr
        self.worker = None
        self.theme_colors = ThemeManager.instance().current_colors
        self._default_output_dir = (default_output_dir or "").strip()
        self._setup_ui()
        self._apply_widget_styles()
        if self._default_output_dir and not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_dir)
        try:
            ThemeManager.instance().theme_changed.connect(self.reapply_theme)
        except Exception:
            pass

    def _setup_ui(self):
        # 设置全局布局约束
        self.setMinimumWidth(700)
        self.resize(1000, 700)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # === 标题区域 ===
        title_label = QLabel("🎵 音频格式转换")
        title_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLORS['text']};")
        subtitle_label = QLabel("支持 MP3, WAV, FLAC, DTS 等 18 种主流/专业音频格式互转")
        subtitle_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")
        
        title_layout = QVBoxLayout()
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        title_layout.setSpacing(4)
        layout.addLayout(title_layout)

        # === 主内容区（左右面板） ===
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)
        layout.addWidget(top_widget, 1)

        # 文件列表
        file_group = QGroupBox("待转换文件")
        file_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                background-color: {COLORS['card']};
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
                background-color: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text']};
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['primary']};
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
                    background-color: {COLORS['card_hover']};
                    color: {COLORS['text']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    padding: 8px 12px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['primary']};
                    color: white;
                    border-color: {COLORS['primary']};
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
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                background-color: {COLORS['card']};
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
                background-color: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
                color: {COLORS['text']};
                min-height: 24px;
            }}
            QComboBox:hover, QLineEdit:hover, QComboBox:focus, QLineEdit:focus {{
                border: 1px solid {COLORS['primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['card']};
                border: 1px solid {COLORS['border']};
                selection-background-color: {COLORS['primary']};
                color: {COLORS['text']};
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
                    color=COLORS['text'],
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
        for key, info in SUPPORTED_AUDIO_FORMATS.items():
            self.format_combo.addItem(info["desc"], key)
        settings_layout.addLayout(create_setting_row("输出格式", self.format_combo))

        # 输出目录 (特殊处理：带按钮)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("默认与源文件同目录")
        self.output_path_edit.setStyleSheet(input_style)
        self.output_browse_btn = QPushButton("浏览")
        self.output_browse_btn.setFixedWidth(70)
        self.output_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
        """)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)
        
        output_layout = QHBoxLayout()
        output_layout.setSpacing(12)
        output_label = QLabel("输出目录")
        output_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        output_label.setMinimumWidth(85)
        output_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred
        )
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_path_edit, 1)
        output_layout.addWidget(self.output_browse_btn)
        settings_layout.addLayout(output_layout)

        # 比特率
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.setStyleSheet(input_style)
        for name, value in BITRATE_PRESETS.items():
            self.bitrate_combo.addItem(name, value)
        settings_layout.addLayout(create_setting_row("比特率", self.bitrate_combo))

        # 采样率
        self.sample_combo = QComboBox()
        self.sample_combo.setStyleSheet(input_style)
        for name, value in SAMPLE_RATE_PRESETS.items():
            self.sample_combo.addItem(name, value)
        settings_layout.addLayout(create_setting_row("采样率", self.sample_combo))

        # 声道
        self.channel_combo = QComboBox()
        self.channel_combo.setStyleSheet(input_style)
        for name, value in CHANNEL_PRESETS.items():
            self.channel_combo.addItem(name, value)
        settings_layout.addLayout(create_setting_row("声道", self.channel_combo))

        # 音量归一化
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
                p.setBrush(QBrush(QColor(COLORS['bg'])))
                pen = QPen(QColor(COLORS['border']))
                pen.setWidth(2)
                p.setPen(pen)
                path = QPainterPath()
                path.addRoundedRect(QRectF(1.0, 1.0, size - 2, size - 2), radius, radius)
                p.drawPath(path)
            p.end()
            return pm

        self.normalize_check = QPushButton(QIcon(_make_checkbox_icon_pixmap(False, COLORS['accent'])),
                                            "  音量归一化 (Normalize)")
        self.normalize_check.setCheckable(True)
        self.normalize_check.setIconSize(QSize(22, 22))
        self.normalize_check.setCursor(Qt.PointingHandCursor)
        self.normalize_check.setStyleSheet(f"""
        QPushButton {{
            color: {COLORS['text']};
            font-size: 14px;
            font-weight: 500;
            padding: 6px 12px 6px 10px;
            border-radius: 6px;
            border: none;
            background-color: transparent;
            text-align: left;
        }}
        QPushButton:hover {{
            background-color: rgba(233, 69, 96, 0.10);
        }}
        QPushButton:checked {{
            background-color: rgba(233, 69, 96, 0.18);
            color: #ffffff;
            font-weight: 600;
        }}
""")

        def _on_normalize_toggled(checked: bool):
            self.normalize_check.setIcon(QIcon(_make_checkbox_icon_pixmap(checked, COLORS['accent'])))
        self.normalize_check.toggled.connect(_on_normalize_toggled)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.addSpacing(97)
        checkbox_layout.addWidget(self.normalize_check)
        checkbox_layout.addStretch()
        settings_layout.addLayout(checkbox_layout)
        
        settings_layout.addStretch()
        top_layout.addWidget(settings_group, 2)

        # === 底部操作栏 ===
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.convert_btn = QPushButton("▶  开始转换")
        self.convert_btn.setMinimumHeight(46)
        self.convert_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS["success"]};
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
                background-color: {COLORS["accent"]};
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
                background-color: {COLORS["card"]};
                color: {COLORS["text"]};
                font-weight: 500;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid {COLORS["border"]};
            }}
            QPushButton:hover {{
                background-color: {COLORS["card_hover"]};
                border-color: {COLORS["success"]};
            }}
        """)
        self.open_output_btn.clicked.connect(self._open_output_dir)

        action_layout.addWidget(self.convert_btn, 2)
        action_layout.addWidget(self.stop_btn, 1)
        action_layout.addStretch()
        action_layout.addWidget(self.open_output_btn, 1)
        layout.addLayout(action_layout)

    # === 事件处理 ===
    def _drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._add_file(path)

    def _add_files(self):
        exts = " ".join(f"*.{e}" for e in INPUT_AUDIO_FORMATS)
        filter_str = f"音频文件 ({exts});;所有文件 (*)"
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频文件", "", filter_str)
        for f in files:
            self._add_file(f)

    def _add_file(self, path: str):
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole) == path:
                return
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        icon = "🎵" if ext in INPUT_AUDIO_FORMATS else "📁"
        item = QListWidgetItem(f"  {icon}  {os.path.basename(path)}")
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
        bitrate = self.bitrate_combo.currentData()
        sample_rate = self.sample_combo.currentData()
        channels = self.channel_combo.currentData()
        normalize = self.normalize_check.isChecked()
        ext = SUPPORTED_AUDIO_FORMATS[output_format]["ext"]

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

            tasks.append(ConversionTask(
                input_path=input_path,
                output_path=out_path,
                output_format=output_format,
                bitrate=bitrate,
                sample_rate=sample_rate,
                channels=channels,
                normalize=normalize
            ))
        return tasks

    def _start_conversion(self):
        if not self.ffmpeg_mgr.available:
            QMessageBox.warning(self, "FFmpeg 未就绪", "未检测到 FFmpeg，转换功能不可用。")
            return
        if self.file_list.count() == 0:
            QMessageBox.information(self, "提示", "请先添加要转换的音频文件。")
            return

        tasks = self._build_tasks()
        total = len(tasks)

        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = AudioConversionWorker(
            tasks,
            self.ffmpeg_mgr.ffmpeg_path,
            self.ffmpeg_mgr.supported_muxers
        )
        self.worker.progress_signal.connect(self._on_progress)

        self.worker.task_started_signal.connect(self._on_task_started)
        self.worker.task_finished_signal.connect(self._on_task_finished)
        self.worker.all_done_signal.connect(self._on_all_done)
        self.worker.start()

        output_format = self.format_combo.currentData()
        self.log_signal.emit(
            "info",
            f"🎵 音频转换启动：共 {total} 个文件 → 输出格式 {output_format.upper()}"
        )

    def _stop_conversion(self):
        if self.worker:
            self.worker.stop()
            self.log_signal.emit("warning", "🎵 音频转换已被用户停止")

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        pass

    @Slot(str)
    def _on_task_started(self, filename: str):
        self.task_monitor_signal.emit(filename)
        self.log_signal.emit("info", f"🎵 正在转换: {filename}")

    @Slot(object)
    def _on_task_finished(self, result):
        basename = os.path.basename(getattr(result.task, "input_path", ""))
        msg = (getattr(result, "message", "") or "").strip()
        first_line = msg.splitlines()[0] if msg else ""
        if len(first_line) > 120:
            first_line = first_line[:117] + "..."
        if getattr(result, "success", False):
            self.log_signal.emit("success", f"🎵 {basename} — {first_line or '转换成功'}")
        else:
            self.log_signal.emit("error", f"🎵 {basename} — {first_line or '转换失败'}")

    @Slot()
    def _on_all_done(self):
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.task_monitor_signal.emit("")
        self.log_signal.emit("info", "🎵 音频转换全部完成")
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

    def _refresh_normalize_icon(self):
        c = self.theme_colors
        checked = self.normalize_check.isChecked()
        self.normalize_check.setIcon(QIcon(self._make_checkbox_icon_pixmap(checked, c["accent"])))

    @Slot(str)
    def set_default_output_dir(self, path: str):
        """外部设置面板更改默认输出目录时触发。仅当用户尚未在此模块手动指定目录时生效。"""
        self._default_output_dir = (path or "").strip()
        current = self.output_path_edit.text().strip()
        if not current:
            self.output_path_edit.setText(self._default_output_dir)

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        """ThemeManager.theme_changed 信号触发时刷新局部硬编码样式。"""
        self.theme_colors = colors
        self._apply_widget_styles()
        self._refresh_normalize_icon()

    def _apply_widget_styles(self):
        """根据当前 self.theme_colors 重新应用所有硬编码 QSS。"""
        c = self.theme_colors

        title_label = self.findChild(QLabel, "")
        # --- 标题 ---
        # 标题是布局里第一个 QLabel，用更稳妥的方式重新找：遍历布局里的前两个 QLabel
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
        self.findChild(QGroupBox, "").setStyleSheet(gb_style) if False else None
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

        # --- 输入控件（下拉框/输入框）通用 ---
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
        for w in (self.format_combo, self.bitrate_combo, self.sample_combo,
                  self.channel_combo, self.output_path_edit):
            w.setStyleSheet(input_style)

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

        # --- 设置行标签（create_setting_row 中的 QLabel）样式统一由全局处理，这里只处理输出目录独立 label ---
        # 输出 label（在 output_layout 中，非 create_setting_row 创建）
        # 找到 output_layout 中第一个 QLabel
        for i in range(self.layout().count()):
            pass  # 无需特殊处理，使用 get_cjk_font_qss 颜色已在 _setup_ui 中设置，但我们需要统一更新：
        # 简化：直接根据 objectName 或 walk 所有内嵌 QLabel 设置 text 颜色 (除标题和日志外)
        # 此处为避免复杂度，仅更新 normalize_check 与状态标签等硬编码样式，其余依赖全局 QSS

        # --- 音量归一化按钮 ---
        accent_rgba_10 = f"rgba{tuple(int(c['accent'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (int(255*0.10),)}".replace("(", "(").replace(" ", "")
        # 简化：不解析 rgba，直接用 hex
        self.normalize_check.setStyleSheet(f"""
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
        # 开始转换
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
        # 停止
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
        # 打开输出目录
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