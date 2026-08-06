
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import platform
import shutil
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QMessageBox, QLabel,
    QPushButton, QFileDialog, QStatusBar, QDialog, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, QSettings, QSize, Slot
from PySide6.QtGui import QFont, QColor

from utils import APP_NAME, APP_VERSION, ORG_NAME, FFmpegManager, get_main_stylesheet, apply_global_cjk_font, ThemeManager
from audio_converter import AudioConverterWidget
from video_converter import VideoConverterWidget
from image_converter import ImageConverterWidget
from doc_converter import DocConverterWidget
from settings_widget import SettingsWidget
from conversion_monitor import ConversionMonitorWidget
from log_viewer import LogViewerWidget


class LoadingDialog(QDialog):
    """启动加载界面：显示应用名 + 进度条 + 当前状态文字。"""

    def __init__(self, colors: dict | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setModal(True)
        self.setFixedSize(440, 220)

        c = colors or ThemeManager.instance().current_colors

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 24)
        layout.setSpacing(8)

        # Logo + 应用名
        title_label = QLabel(f"🛠️  {APP_NAME}")
        title_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {c['text']};"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet(
            f"font-size: 12px; color: {c['text_secondary']};"
        )
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        layout.addStretch()

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # 状态文字
        self.status_label = QLabel("正在初始化…")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {c['text_secondary']};"
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # 主题背景 + 圆角
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c['bg']};
                border-radius: 12px;
            }}
            QProgressBar {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {c['success']};
                border-radius: 4px;
            }}
        """)

    def set_progress(self, value: int, status: str = ""):
        """更新进度条与状态文字，并立即刷新 UI。"""
        self.progress_bar.setValue(value)
        if status:
            self.status_label.setText(status)
        QApplication.processEvents()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        # 加载界面：先显示，覆盖整个初始化过程
        self._loading = LoadingDialog(ThemeManager.instance().current_colors)
        self._loading.show()
        QApplication.processEvents()

        self._loading.set_progress(10, "加载用户偏好…")
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.ffmpeg_mgr = FFmpegManager()

        # ---- 从 QSettings 加载用户偏好（在创建任何 Widget 之前） ----
        saved_theme = (self.settings.value("Settings/theme", "dark") or "dark").lower()
        if saved_theme not in ("dark", "light"):
            saved_theme = "dark"
        self._saved_default_output_dir = (self.settings.value("Settings/default_output_dir", "") or "").strip()

        self._loading.set_progress(25, "应用主题…")
        # 先让 ThemeManager 应用主题，确保创建 Widget 时 ThemeManager.instance().current_colors 已是正确值
        self._initial_colors = ThemeManager.instance().apply_theme(
            QApplication.instance(), saved_theme
        )

        self._loading.set_progress(45, "初始化转换模块…")
        self._setup_ui()

        self._loading.set_progress(75, "连接全局信号…")
        self._connect_global_signals()

        self._loading.set_progress(90, "加载窗口设置…")
        self._load_settings()

        self._loading.set_progress(100, "启动完成")
        # 至少显示 400ms，避免一闪而过
        QTimer.singleShot(400, self._loading.close)

        # 延迟执行 FFmpeg 检测
        QTimer.singleShot(600, self._check_ffmpeg)

    def _apply_widget_styles(self):
        c = ThemeManager.instance().current_colors
        self.nav_widget.setStyleSheet(f"background-color: {c['bg']};")
        self.nav_title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {c['text']};")
        self.nav_version_label.setStyleSheet(f"font-size: 12px; color: {c['text_secondary']};")
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {c["bg"]};
                color: {c["text_secondary"]};
                border-top: 1px solid {c["border"]};
            }}
        """)

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        self._apply_widget_styles()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 左侧导航栏 ===
        self.nav_widget = QWidget()
        self.nav_widget.setFixedWidth(240)
        # 初始样式在 _apply_widget_styles中统一重绘
        nav_layout = QVBoxLayout(self.nav_widget)
        nav_layout.setContentsMargins(0, 20, 0, 20)
        nav_layout.setSpacing(0)

        # Logo & 标题
        logo_layout = QVBoxLayout()
        logo_label = QLabel("🛠️")
        logo_label.setStyleSheet("font-size: 40px;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.nav_title_label = QLabel(APP_NAME)
        self.nav_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.nav_version_label = QLabel(f"v{APP_VERSION}")
        self.nav_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        logo_layout.addWidget(logo_label)
        logo_layout.addWidget(self.nav_title_label)
        logo_layout.addWidget(self.nav_version_label)
        logo_layout.setSpacing(2)
        nav_layout.addLayout(logo_layout)
        nav_layout.addSpacing(30)

        # 导航列表
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        
        nav_items = [
            ("音频转换", 0),
            ("视频转换", 1),
            ("图片转换", 2),
            ("文档转换", 3),
            ("转换监控", 4),
            ("运行日志", 5),
            ("全局设置", 6),
        ]
        
        for text, index in nav_items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.nav_list.addItem(item)
            
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        nav_layout.addWidget(self.nav_list)
        nav_layout.addStretch()

        main_layout.addWidget(self.nav_widget)

        # === 右侧内容区 ===
        self.content_stack = QStackedWidget()
        # 使用全局样式背景（全局 QSS 会设置 bg；这里保留与主题一致的兜底）
        self.content_stack.setStyleSheet(f"padding: 20px;")
        
        # 从 QSettings 加载的默认输出目录（已在 __init__ 中读取）
        default_out = getattr(self, "_saved_default_output_dir", "")

        # 实例化各个模块并加入堆叠组件（把全局默认输出目录传进去）
        self.audio_widget = AudioConverterWidget(self.ffmpeg_mgr, default_output_dir=default_out)
        self.video_widget = VideoConverterWidget(self.ffmpeg_mgr, default_output_dir=default_out)
        self.image_widget = ImageConverterWidget(self.ffmpeg_mgr, default_output_dir=default_out)
        self.doc_widget   = DocConverterWidget(default_output_dir=default_out)
        self.monitor_widget = ConversionMonitorWidget()
        self.log_widget = LogViewerWidget(self.ffmpeg_mgr)
        self.settings_widget = SettingsWidget(
            initial_theme=ThemeManager.instance().current_theme,
            initial_output_dir=default_out,
        )

        self.content_stack.addWidget(self.audio_widget)    # index 0
        self.content_stack.addWidget(self.video_widget)    # index 1
        self.content_stack.addWidget(self.image_widget)    # index 2
        self.content_stack.addWidget(self.doc_widget)      # index 3
        self.content_stack.addWidget(self.monitor_widget)  # index 4
        self.content_stack.addWidget(self.log_widget)      # index 5
        self.content_stack.addWidget(self.settings_widget) # index 6
        
        
        main_layout.addWidget(self.content_stack, 1)
        
        # 状态栏（样式统一由 _apply_widget_styles 统一设置
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 统一重绘 MainWindow 内部局部样式（替换上述 nav / title / status bar
        self._apply_widget_styles()

    def _on_nav_changed(self, index):
        current_item = self.nav_list.currentItem()
        if not current_item:
            return
            
        target_index = current_item.data(Qt.ItemDataRole.UserRole)
        self.content_stack.setCurrentIndex(target_index)

    def _connect_global_signals(self):
        tm = ThemeManager.instance()
        # 主题变化 -> 各模块重绘局部样式
        tm.theme_changed.connect(self.reapply_theme)
        tm.theme_changed.connect(self.audio_widget.reapply_theme)
        tm.theme_changed.connect(self.video_widget.reapply_theme)
        tm.theme_changed.connect(self.image_widget.reapply_theme)
        tm.theme_changed.connect(self.doc_widget.reapply_theme)
        tm.theme_changed.connect(self.monitor_widget.reapply_theme)
        tm.theme_changed.connect(self.log_widget.reapply_theme)
        tm.theme_changed.connect(self.settings_widget.reapply_theme)
        # 默认输出目录变化 -> 四个转换模块同步更新
        self.settings_widget.default_output_dir_changed.connect(
            self.audio_widget.set_default_output_dir
        )
        self.settings_widget.default_output_dir_changed.connect(
            self.video_widget.set_default_output_dir
        )
        self.settings_widget.default_output_dir_changed.connect(
            self.image_widget.set_default_output_dir
        )
        self.settings_widget.default_output_dir_changed.connect(
            self.doc_widget.set_default_output_dir
        )
        # 转换任务信号 -> 监视器
        self.audio_widget.task_monitor_signal.connect(
            lambda name: self.monitor_widget.clear_module("音频") if not name else self.monitor_widget.add_task("音频", name)
        )
        self.video_widget.task_monitor_signal.connect(
            lambda name: self.monitor_widget.clear_module("视频") if not name else self.monitor_widget.add_task("视频", name)
        )
        self.image_widget.task_monitor_signal.connect(
            lambda name: self.monitor_widget.clear_module("图片") if not name else self.monitor_widget.add_task("图片", name)
        )
        self.doc_widget.task_monitor_signal.connect(
            lambda name: self.monitor_widget.clear_module("文档") if not name else self.monitor_widget.add_task("文档", name)
        )
        # 任务进度信号 -> 监视器进度条
        self.audio_widget.task_progress_signal.connect(self.monitor_widget.set_task_progress)
        self.video_widget.task_progress_signal.connect(self.monitor_widget.set_task_progress)
        self.image_widget.task_progress_signal.connect(self.monitor_widget.set_task_progress)
        self.doc_widget.task_progress_signal.connect(self.monitor_widget.set_task_progress)
        # 任务结果信号 -> 监视器结果区
        self.audio_widget.task_result_signal.connect(self.monitor_widget.add_result)
        self.video_widget.task_result_signal.connect(self.monitor_widget.add_result)
        self.image_widget.task_result_signal.connect(self.monitor_widget.add_result)
        self.doc_widget.task_result_signal.connect(self.monitor_widget.add_result)
        # 日志信号 -> 日志查看器
        self.audio_widget.log_signal.connect(self.log_widget.append_log)
        self.video_widget.log_signal.connect(self.log_widget.append_log)
        self.image_widget.log_signal.connect(self.log_widget.append_log)
        self.doc_widget.log_signal.connect(self.log_widget.append_log)

    def _check_ffmpeg(self):
        custom_path = self.settings.value("MainWindow/custom_ffmpeg", "")
        if self.ffmpeg_mgr.detect_auto(custom_path):
            self._ffmpeg_success()
        else:
            self._ffmpeg_failed()

    def _ffmpeg_success(self):
        self.status_bar.showMessage(
            f"✓ FFmpeg 已就绪 [{self.ffmpeg_mgr.source}]  |  {self.ffmpeg_mgr.ffmpeg_path}", 5000
        )
        self.log_widget.update_engine_status(self.ffmpeg_mgr)
        self.log_widget.append_log(
            "success",
            f"FFmpeg 已就绪：{self.ffmpeg_mgr.source}  |  {self.ffmpeg_mgr.ffmpeg_path}"
        )

    def _ffmpeg_failed(self):
        self.status_bar.showMessage("✗ FFmpeg 未检测到 — 音视频暂不可用（图片转换仍可使用 Pillow 或一键安装）", 0)
        self.log_widget.update_engine_status(self.ffmpeg_mgr)
        self.log_widget.append_log(
            "error",
            "FFmpeg 未检测到 — 音视频转换不可用（图片转换仍可使用 Pillow）"
        )

    def _show_settings_dialog(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("FFmpeg 设置")
        dialog.setText("FFmpeg 环境配置")

        if self.ffmpeg_mgr.available:
            mgr = self.ffmpeg_mgr
            mux_n = len(getattr(mgr, 'supported_muxers', set()))
            enc_n = len(getattr(mgr, 'supported_encoders', set()))
            quality = "完整版 ✅" if (mux_n >= 80 and enc_n >= 80) else ("精简版 ⚠️" if (mux_n < 30 or enc_n < 30) else "标准版")
            version = getattr(mgr, 'version', '') or '(未知)'
            info = (
                f"当前状态: ✓ 已就绪  {quality}\n"
                f"版本: {version}\n"
                f"来源: {mgr.source}\n"
                f"路径: {mgr.ffmpeg_path}\n"
                f"能力: {mux_n} 个封装器 / {enc_n} 个编码器\n\n"
                "操作：\n"
                "  ① 手动指定路径 = 强制使用你选的 ffmpeg（即使它是精简版）\n"
                "  ② 自动选择最佳 = 扫描所有候选并挑选能力最强的\n\n"
                f"👉 如果「{quality}」字样显示为 ⚠️，请点击 [自动选择最佳] 或安装完整版。"
            )
        else:
            info = (
                "✗ 未检测到任何可用的 FFmpeg。\n\n"
                "推荐做法（任选其一）：\n"
                "  • Debian/Ubuntu: sudo apt install ffmpeg\n"
                "  • macOS: brew install ffmpeg\n"
                "  • 或下载官方构建放入项目的 ffmpeg/ 目录\n"
                "  • 或点击 [手动指定路径] 定位 ffmpeg 可执行文件\n"
            )
        dialog.setInformativeText(info)

        btn_manual = dialog.addButton("手动指定路径", QMessageBox.ButtonRole.AcceptRole)
        btn_auto = dialog.addButton("自动选择最佳", QMessageBox.ButtonRole.ActionRole)
        btn_close = dialog.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked is btn_manual:
            self._browse_ffmpeg()
        elif clicked is btn_auto:
            custom_path = self.settings.value("MainWindow/custom_ffmpeg", "")
            if self.ffmpeg_mgr.detect_auto(custom_path):
                self._ffmpeg_success()
                QMessageBox.information(self, "FFmpeg 自动选择成功",
                    f"已自动选择能力最强的 FFmpeg：\n\n"
                    f"来源: {self.ffmpeg_mgr.source}\n"
                    f"路径: {self.ffmpeg_mgr.ffmpeg_path}\n"
                    f"版本: {getattr(self.ffmpeg_mgr,'version','')}\n"
                    f"封装器: {len(self.ffmpeg_mgr.supported_muxers)} 个\n"
                    f"编码器: {len(self.ffmpeg_mgr.supported_encoders)} 个")
            else:
                self._ffmpeg_failed()
                QMessageBox.warning(self, "FFmpeg 未找到", "自动扫描也没有找到任何可用的 FFmpeg，请手动指定路径或安装。")

    def _browse_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ffmpeg 可执行文件",
            "", "ffmpeg (ffmpeg*)" if os.name == 'nt' else "ffmpeg (ffmpeg)"
        )
        if path:
            if self.ffmpeg_mgr.detect_custom(path):
                self.settings.setValue("MainWindow/custom_ffmpeg", path)
                self.status_bar.showMessage(f"✓ FFmpeg 已手动指定  |  {path}", 5000)
                self.log_widget.update_engine_status(self.ffmpeg_mgr)
                self.log_widget.append_log(
                    "success", f"FFmpeg 已手动指定：{path}"
                )
                QMessageBox.information(self, "FFmpeg 设置成功",
                    f"已选择：\n\n"
                    f"路径: {path}\n"
                    f"版本: {getattr(self.ffmpeg_mgr,'version','')}\n"
                    f"封装器: {len(self.ffmpeg_mgr.supported_muxers)} 个\n"
                    f"编码器: {len(self.ffmpeg_mgr.supported_encoders)} 个\n\n"
                    "如果数值很小（例如 <30），说明它是精简版，建议点「自动选择最佳」或换完整版。")
            else:
                QMessageBox.warning(self, "错误", "选择的文件无效或不可执行，请确认 ffmpeg 二进制正确。")

    def _load_settings(self):
        self.settings.beginGroup("MainWindow")
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.settings.endGroup()

    def closeEvent(self, event):
        self.settings.beginGroup("MainWindow")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.endGroup()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    apply_global_cjk_font(app, font_size_px=13)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()