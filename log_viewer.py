#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行日志模块 —— 显示各转换模块关键事件 + FFmpeg 引擎状态。"""

from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QGroupBox,
)

from utils import ThemeManager


# 日志级别 -> 主题颜色键 / 图标
LEVEL_COLOR_KEYS = {
    "info":    "text_secondary",
    "success": "success",
    "warning": "warning",
    "error":   "error",
}
LEVEL_ICONS = {
    "info":    "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error":   "❌",
}

# 最多保留的日志条数
MAX_LOG_ITEMS = 500


class LogViewerWidget(QWidget):
    """运行日志模块：左侧 QListWidget 倒序显示日志，顶部展示 FFmpeg 引擎状态。"""

    def __init__(self, ffmpeg_mgr=None):
        super().__init__()
        self.theme_colors = ThemeManager.instance().current_colors
        self.ffmpeg_mgr = ffmpeg_mgr
        self._setup_ui()
        self._apply_widget_styles()

    # ==================== UI ====================

    def _setup_ui(self):
        self.setMinimumWidth(700)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # === 标题 ===
        self.title_label = QLabel("📋 运行日志")
        self.title_label.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {self.theme_colors['text']};"
        )
        self.subtitle_label = QLabel("实时显示各模块转换事件与 FFmpeg 引擎状态")
        self.subtitle_label.setStyleSheet(
            f"font-size: 13px; color: {self.theme_colors['text_secondary']};"
        )
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        # === 引擎状态卡片 ===
        self.engine_group = QGroupBox("引擎状态")
        eng_layout = QVBoxLayout(self.engine_group)
        eng_layout.setContentsMargins(16, 24, 16, 16)
        eng_layout.setSpacing(6)

        self.engine_status_label = QLabel("检测中…")
        self.engine_status_label.setWordWrap(True)
        self.engine_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.engine_status_label.setStyleSheet(
            "font-family: 'JetBrains Mono', 'Consolas', monospace;"
            " font-size: 12px; color: " + self.theme_colors["text"] + ";"
        )
        eng_layout.addWidget(self.engine_status_label)

        layout.addWidget(self.engine_group)

        # === 日志列表头 ===
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        log_title = QLabel("事件日志")
        log_title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {self.theme_colors['text']};"
        )
        header_layout.addWidget(log_title)
        header_layout.addStretch()

        self.clear_btn = QPushButton("🗑 清空日志")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear)
        header_layout.addWidget(self.clear_btn)
        layout.addLayout(header_layout)

        # === 日志列表 ===
        self.log_list = QListWidget()
        self.log_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.log_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self.theme_colors['bg']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: transparent;
                border-bottom: 1px solid {self.theme_colors['border']};
                padding: 6px 8px;
                color: {self.theme_colors['text']};
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.log_list, 1)

        # 底部提示
        hint_label = QLabel(
            f"最多保留最近 {MAX_LOG_ITEMS} 条日志；新事件将出现在顶部。"
        )
        hint_label.setStyleSheet(
            f"color: {self.theme_colors['text_secondary']}; font-size: 12px; padding: 4px 0;"
        )
        layout.addWidget(hint_label)

    # ==================== 公共接口 ====================

    @Slot(str, str)
    def append_log(self, level: str, message: str):
        """追加一条日志。level ∈ {info, success, warning, error}。"""
        level = (level or "info").lower()
        if level not in LEVEL_ICONS:
            level = "info"
        ts = datetime.now().strftime("%H:%M:%S")
        text = f"[{ts}] {LEVEL_ICONS[level]} {message}"

        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, level)
        color_key = LEVEL_COLOR_KEYS[level]
        color_hex = self.theme_colors.get(color_key, self.theme_colors.get("text"))
        item.setForeground(QColor(color_hex))

        self.log_list.insertItem(0, item)
        # 限制最大条数
        while self.log_list.count() > MAX_LOG_ITEMS:
            self.log_list.takeItem(self.log_list.count() - 1)

    @Slot()
    def _on_clear(self):
        self.log_list.clear()
        self.append_log("info", "日志已清空")

    @Slot(object)
    def update_engine_status(self, ffmpeg_mgr=None):
        """刷新 FFmpeg 引擎状态显示。"""
        mgr = ffmpeg_mgr if ffmpeg_mgr is not None else self.ffmpeg_mgr
        if mgr is None:
            self.engine_status_label.setText("未注入 FFmpeg 管理器")
            return
        self.ffmpeg_mgr = mgr

        if getattr(mgr, "available", False):
            mux_n = len(getattr(mgr, "supported_muxers", set()))
            enc_n = len(getattr(mgr, "supported_encoders", set()))
            if mux_n >= 80 and enc_n >= 80:
                quality = "完整版 ✅"
            elif mux_n < 30 or enc_n < 30:
                quality = "精简版 ⚠️"
            else:
                quality = "标准版"
            text = (
                f"状态:  ✓ 已就绪  {quality}\n"
                f"版本:  {getattr(mgr, 'version', '') or '(未知)'}\n"
                f"来源:  {getattr(mgr, 'source', '')}\n"
                f"路径:  {getattr(mgr, 'ffmpeg_path', '')}\n"
                f"能力:  {mux_n} 个封装器 / {enc_n} 个编码器"
            )
        else:
            text = (
                "状态:  ✗ 未检测到 FFmpeg\n"
                "提示:  音视频转换不可用；图片转换仍可使用 Pillow 引擎。"
            )
        self.engine_status_label.setText(text)

    # ==================== 主题 ====================

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        self.theme_colors = colors
        self._apply_widget_styles()
        # 重新着色已有日志条目（使用 UserRole 存储的级别，避免遍历文本）
        for i in range(self.log_list.count()):
            item = self.log_list.item(i)
            level = item.data(Qt.ItemDataRole.UserRole) or "info"
            color_key = LEVEL_COLOR_KEYS.get(level, "text")
            item.setForeground(
                QColor(self.theme_colors.get(color_key, self.theme_colors.get("text")))
            )

    def _apply_widget_styles(self):
        c = self.theme_colors

        self.title_label.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {c['text']};"
        )
        self.subtitle_label.setStyleSheet(
            f"font-size: 13px; color: {c['text_secondary']};"
        )

        group_style = f"""
            QGroupBox {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 12px;
                margin-top: 12px;
                padding-top: 16px;
                padding-bottom: 8px;
                padding-left: 16px;
                padding-right: 16px;
                font-weight: bold;
                color: {c['text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                color: {c['success']};
            }}
        """
        self.engine_group.setStyleSheet(group_style)

        self.engine_status_label.setStyleSheet(
            "font-family: 'JetBrains Mono', 'Consolas', monospace;"
            " font-size: 12px; color: " + c["text"] + ";"
        )

        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['card']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {c['card_hover']};
                border-color: {c['accent']};
                color: {c['accent']};
            }}
        """)

        self.log_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: transparent;
                border-bottom: 1px solid {c['border']};
                padding: 6px 8px;
                color: {c['text']};
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 12px;
            }}
        """)
