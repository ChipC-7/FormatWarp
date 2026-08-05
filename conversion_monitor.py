#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont

from utils import COLORS, ThemeManager


class ConversionMonitorWidget(QWidget):
    """转换监控模块 —— 实时显示所有模块中正在转换的文件。"""

    def __init__(self):
        super().__init__()
        self.theme_colors = ThemeManager.instance().current_colors
        self._active_tasks: dict[str, QListWidgetItem] = {}  # key -> item
        self._setup_ui()
        self._apply_widget_styles()
        try:
            ThemeManager.instance().theme_changed.connect(self.reapply_theme)
        except Exception:
            pass

    def _setup_ui(self):
        self.setMinimumWidth(700)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 标题
        title_label = QLabel("📊 转换监控")
        title_label.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {COLORS['text']};"
        )
        subtitle_label = QLabel("实时查看各模块正在转换的文件")
        subtitle_label.setStyleSheet(
            f"font-size: 13px; color: {COLORS['text_secondary']};"
        )
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        # 状态提示
        self.status_label = QLabel("当前没有正在进行的转换任务")
        self.status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 14px; padding: 8px 0;"
        )
        layout.addWidget(self.status_label)

        # 任务列表
        self.task_list = QListWidget()
        self.task_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {COLORS['card']};
                border-radius: 6px;
                padding: 12px 16px;
                margin: 4px 0px;
                color: {COLORS['text']};
                font-size: 14px;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['card_hover']};
            }}
        """)
        self.task_list.setMinimumHeight(300)
        layout.addWidget(self.task_list)

        # 底部提示
        hint_label = QLabel("切换回其他模块进行转换操作，本页面会自动显示转换进度")
        hint_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; padding: 4px 0;"
        )
        layout.addWidget(hint_label)

        layout.addStretch()

    # ==================== 公共接口 ====================

    @Slot(str, str)
    def add_task(self, module_name: str, filename: str):
        """添加一个正在转换的任务。"""
        key = f"{module_name}:{filename}"
        if key in self._active_tasks:
            return
        item = QListWidgetItem(f"  {module_name}  —  {filename}")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        font = item.font()
        font.setPointSize(12)
        item.setFont(font)
        self.task_list.insertItem(0, item)
        self._active_tasks[key] = item
        self._update_status()

    @Slot(str, str)
    def remove_task(self, module_name: str, filename: str):
        """移除一个已完成的任务。"""
        key = f"{module_name}:{filename}"
        if key not in self._active_tasks:
            return
        row = self.task_list.row(self._active_tasks[key])
        self.task_list.takeItem(row)
        del self._active_tasks[key]
        self._update_status()

    @Slot(str)
    def clear_module(self, module_name: str):
        """清除指定模块的所有任务。"""
        keys_to_remove = [k for k in self._active_tasks if k.startswith(f"{module_name}:")]
        for key in keys_to_remove:
            row = self.task_list.row(self._active_tasks[key])
            self.task_list.takeItem(row)
            del self._active_tasks[key]
        self._update_status()

    @Slot()
    def clear_all(self):
        """清除所有任务。"""
        self.task_list.clear()
        self._active_tasks.clear()
        self._update_status()

    def _update_status(self):
        count = len(self._active_tasks)
        if count == 0:
            self.status_label.setText("当前没有正在进行的转换任务")
            self.status_label.setStyleSheet(
                f"color: {self.theme_colors.get('text_secondary', '#a0a0a0')}; "
                f"font-size: 14px; padding: 8px 0;"
            )
        else:
            self.status_label.setText(f"正在转换 {count} 个文件…")
            self.status_label.setStyleSheet(
                f"color: {self.theme_colors.get('success', '#00d9ff')}; "
                f"font-weight: 600; font-size: 14px; padding: 8px 0;"
            )

    # ==================== 主题 ====================

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        self.theme_colors = colors
        self._apply_widget_styles()
        self._update_status()

    def _apply_widget_styles(self):
        c = self.theme_colors
        self.task_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {c['card']};
                border-radius: 6px;
                padding: 12px 16px;
                margin: 4px 0px;
                color: {c['text']};
                font-size: 14px;
            }}
            QListWidget::item:hover {{
                background-color: {c['card_hover']};
            }}
        """)