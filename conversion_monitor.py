#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QProgressBar, QGroupBox,
)
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor

from utils import ThemeManager


class TaskItemWidget(QWidget):
    """单个任务条目：模块名+文件名 + 进度条 + 暂停 + 删除按钮。"""

    delete_clicked = Signal(str)  # task_key

    def __init__(self, module_name: str, filename: str):
        super().__init__()
        self.task_key = f"{module_name}:{filename}"
        self.module_name = module_name
        self.filename = filename
        self._paused = False
        self._progress = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # 左侧：模块名 + 文件名
        self.info_label = QLabel(f"{module_name}  —  {filename}")
        self.info_label.setMinimumWidth(280)
        layout.addWidget(self.info_label)

        # 进度条（确定模式：显示任务进度百分比）
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v%")
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setFixedHeight(18)
        layout.addWidget(self.progress_bar, 1)

        # 暂停/继续按钮
        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setFixedWidth(80)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self.pause_btn)

        # 删除按钮
        self.delete_btn = QPushButton("🗑 删除")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedWidth(80)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.delete_btn)

    def _on_pause_clicked(self):
        self.set_paused(not self._paused)

    def _on_delete_clicked(self):
        self.delete_clicked.emit(self.task_key)

    def set_paused(self, paused: bool):
        if self._paused == paused:
            return
        self._paused = paused
        self.pause_btn.setText("▶ 继续" if paused else "⏸ 暂停")

    def set_progress(self, value: int):
        """更新进度条百分比 (0-100)。"""
        self._progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(self._progress)

    def get_progress(self) -> int:
        return self._progress

    def is_paused(self) -> bool:
        return self._paused

    def apply_theme(self, c: dict):
        self.info_label.setStyleSheet(
            f"font-size: 13px; color: {c['text']};"
        )
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                color: {c['text']};
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {c['success']};
                border-radius: 4px;
            }}
        """)
        btn_style = f"""
            QPushButton {{
                background-color: {c['card']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {c['card_hover']};
                border-color: {c['accent']};
                color: {c['accent']};
            }}
        """
        self.pause_btn.setStyleSheet(btn_style)
        self.delete_btn.setStyleSheet(btn_style)


class ConversionMonitorWidget(QWidget):
    """转换监控模块 —— 实时显示所有模块中正在转换的文件、总进度、成功/失败结果。"""

    def __init__(self):
        super().__init__()
        self.theme_colors = ThemeManager.instance().current_colors
        # key -> (QListWidgetItem, TaskItemWidget)
        self._active_tasks: dict[str, tuple] = {}
        # 累计统计：用于计算总进度和结果区
        self._total_started: int = 0
        self._total_done: int = 0  # 已完成的任务数（成功 + 失败，在移除 active 时累加）
        self._success_accumulated: int = 0  # 已经移出结果区的成功任务累加
        self._failure_accumulated: int = 0
        self._setup_ui()
        self._apply_widget_styles()

    # ==================== UI 构建 ====================

    def _setup_ui(self):
        c = self.theme_colors
        self.setMinimumWidth(700)
        self.resize(1000, 780)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 标题
        title_label = QLabel("📊 转换监控")
        title_label.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {self.theme_colors['text']};"
        )
        subtitle_label = QLabel("实时查看各模块正在转换的文件、总进度与结果")
        subtitle_label.setStyleSheet(
            f"font-size: 13px; color: {self.theme_colors['text_secondary']};"
        )
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        # 顶部操作栏：状态 + 全部暂停 + 全部删除
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
        self.status_label = QLabel("当前没有正在进行的转换任务")
        self.status_label.setStyleSheet(
            f"color: {self.theme_colors['text_secondary']}; font-size: 14px; padding: 8px 0;"
        )
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()

        self.pause_all_btn = QPushButton("⏸ 全部暂停")
        self.pause_all_btn.setCursor(Qt.PointingHandCursor)
        self.pause_all_btn.clicked.connect(self._on_pause_all)
        top_bar.addWidget(self.pause_all_btn)

        self.delete_all_btn = QPushButton("🗑 全部删除")
        self.delete_all_btn.setCursor(Qt.PointingHandCursor)
        self.delete_all_btn.clicked.connect(self._on_delete_all)
        top_bar.addWidget(self.delete_all_btn)
        layout.addLayout(top_bar)

        # 任务列表
        self.task_list = QListWidget()
        self.task_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self.theme_colors['bg']};
                border: 1px solid {self.theme_colors['border']};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {self.theme_colors['card']};
                border-radius: 6px;
                padding: 0px;
                margin: 4px 0px;
            }}
        """)
        self.task_list.setMinimumHeight(220)
        layout.addWidget(self.task_list)

        # ===== 总进度条 =====
        total_group = QGroupBox("总进度")
        total_layout = QVBoxLayout(total_group)
        total_layout.setContentsMargins(16, 22, 16, 14)
        total_layout.setSpacing(8)

        self.total_info_label = QLabel("未开始转换")
        self.total_info_label.setStyleSheet(
            f"font-size: 13px; color: {self.theme_colors['text_secondary']};"
        )
        total_layout.addWidget(self.total_info_label)

        self.total_progress_bar = QProgressBar()
        self.total_progress_bar.setRange(0, 100)
        self.total_progress_bar.setValue(0)
        self.total_progress_bar.setFormat("%v%")
        self.total_progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_progress_bar.setFixedHeight(20)
        total_layout.addWidget(self.total_progress_bar)

        layout.addWidget(total_group)

        # ===== 结果区：成功 / 失败 =====
        result_group = QGroupBox("转换结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(16, 22, 16, 14)
        result_layout.setSpacing(10)

        # 结果计数标题栏
        result_header = QHBoxLayout()
        result_header.setContentsMargins(0, 0, 0, 0)
        result_header.setSpacing(16)

        self.success_count_label = QLabel("✅ 成功: 0")
        self.success_count_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {self.theme_colors['success']};"
        )
        result_header.addWidget(self.success_count_label)

        self.failure_count_label = QLabel("❌ 失败: 0")
        self.failure_count_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {self.theme_colors['error']};"
        )
        result_header.addWidget(self.failure_count_label)

        result_header.addStretch()

        # 清空结果按钮
        self.clear_result_btn = QPushButton("🗑 清空结果")
        self.clear_result_btn.setCursor(Qt.PointingHandCursor)
        self.clear_result_btn.clicked.connect(self._on_clear_result)
        result_header.addWidget(self.clear_result_btn)

        result_layout.addLayout(result_header)

        # 成功 / 失败 两个列表并排
        lists_row = QHBoxLayout()
        lists_row.setContentsMargins(0, 0, 0, 0)
        lists_row.setSpacing(12)

        # 成功列表
        success_col = QVBoxLayout()
        success_col.setSpacing(4)
        success_title = QLabel("成功文件")
        success_title.setStyleSheet(
            f"font-size: 12px; color: {self.theme_colors['text_secondary']};"
        )
        success_col.addWidget(success_title)
        self.success_list = QListWidget()
        self.success_list.setMinimumHeight(140)
        success_col.addWidget(self.success_list, 1)
        lists_row.addLayout(success_col, 1)

        # 失败列表
        failure_col = QVBoxLayout()
        failure_col.setSpacing(4)
        failure_title = QLabel("失败文件")
        failure_title.setStyleSheet(
            f"font-size: 12px; color: {self.theme_colors['text_secondary']};"
        )
        failure_col.addWidget(failure_title)
        self.failure_list = QListWidget()
        self.failure_list.setMinimumHeight(140)
        failure_col.addWidget(self.failure_list, 1)
        lists_row.addLayout(failure_col, 1)

        result_layout.addLayout(lists_row)
        layout.addWidget(result_group)

        # 底部提示
        hint_label = QLabel("切换回其他模块进行转换操作，本页面会自动显示转换进度与结果")
        hint_label.setStyleSheet(
            f"color: {self.theme_colors['text_secondary']}; font-size: 12px; padding: 4px 0;"
        )
        layout.addWidget(hint_label)

    # ==================== 顶部操作按钮 ====================

    @Slot()
    def _on_pause_all(self):
        """切换所有任务的暂停状态：任一未暂停则全部暂停，否则全部继续。"""
        if not self._active_tasks:
            return
        any_running = any(not w.is_paused() for _, w in self._active_tasks.values())
        for _, w in self._active_tasks.values():
            w.set_paused(any_running)
        self._refresh_pause_all_button()

    @Slot()
    def _on_delete_all(self):
        """清空所有正在进行的任务（结果区保留）。"""
        self.task_list.clear()
        self._active_tasks.clear()
        self._refresh_pause_all_button()
        self._update_status()
        self._update_total_progress()

    @Slot()
    def _on_clear_result(self):
        """清空成功/失败结果列表，并把当前结果计数累加进缓存。"""
        self._success_accumulated += self.success_list.count()
        self._failure_accumulated += self.failure_list.count()
        self.success_list.clear()
        self.failure_list.clear()
        self._update_result_counts()

    def _refresh_pause_all_button(self):
        """根据当前任务状态刷新顶部按钮文字。"""
        if not self._active_tasks:
            self.pause_all_btn.setText("⏸ 全部暂停")
            return
        any_running = any(not w.is_paused() for _, w in self._active_tasks.values())
        self.pause_all_btn.setText("⏸ 全部暂停" if any_running else "▶ 全部继续")

    # ==================== 公共接口 ====================

    @Slot(str, str)
    def add_task(self, module_name: str, filename: str):
        """添加一个正在转换的任务。"""
        key = f"{module_name}:{filename}"
        if key in self._active_tasks:
            return
        task_widget = TaskItemWidget(module_name, filename)
        task_widget.apply_theme(self.theme_colors)
        task_widget.delete_clicked.connect(self._on_task_delete)
        task_widget.pause_btn.clicked.connect(self._refresh_pause_all_button)

        item = QListWidgetItem()
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.task_list.insertItem(0, item)
        self.task_list.setItemWidget(item, task_widget)
        item.setSizeHint(task_widget.sizeHint())

        self._active_tasks[key] = (item, task_widget)
        self._total_started += 1
        self._update_status()
        self._update_total_progress()

    @Slot(str, str, int)
    def set_task_progress(self, module_name: str, filename: str, progress: int):
        """更新指定任务的进度条百分比，并刷新总进度。"""
        key = f"{module_name}:{filename}"
        if key in self._active_tasks:
            _, task_widget = self._active_tasks[key]
            task_widget.set_progress(progress)
            self._update_total_progress()

    @Slot(str, str, bool, str)
    def add_result(self, module_name: str, filename: str, success: bool, message: str = ""):
        """记录一条转换结果（加入成功/失败列表），并移除对应活跃任务。"""
        # 先尝试移除活跃任务
        key = f"{module_name}:{filename}"
        if key in self._active_tasks:
            item, task_widget = self._active_tasks[key]
            # 如果任务进度还未满，补到 100 并刷新总进度
            if task_widget.get_progress() < 100:
                task_widget.set_progress(100)
            row = self.task_list.row(item)
            self.task_list.takeItem(row)
            del self._active_tasks[key]
            self._total_done += 1
            self._refresh_pause_all_button()

        # 加入结果列表
        msg = (message or "").strip()
        first_line = msg.splitlines()[0] if msg else ("转换成功" if success else "转换失败")
        if len(first_line) > 140:
            first_line = first_line[:137] + "..."
        display_text = f"{module_name}  —  {filename}    [{first_line}]"
        list_item = QListWidgetItem(display_text)
        list_item.setToolTip(msg)
        list_item.setFlags(list_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if success:
            list_item.setForeground(self.theme_colors.get("success", QColor("#00d9ff")))
            self.success_list.addItem(list_item)
        else:
            list_item.setForeground(self.theme_colors.get("error", QColor("#ff6b6b")))
            self.failure_list.addItem(list_item)

        self._update_status()
        self._update_total_progress()
        self._update_result_counts()

    @Slot(str)
    def _on_task_delete(self, task_key: str):
        """单个任务删除按钮回调（仅从活跃任务列表移除，不计入结果）。"""
        if task_key not in self._active_tasks:
            return
        item, _ = self._active_tasks[task_key]
        row = self.task_list.row(item)
        self.task_list.takeItem(row)
        del self._active_tasks[task_key]
        self._total_done += 1
        self._refresh_pause_all_button()
        self._update_status()
        self._update_total_progress()

    @Slot(str, str)
    def remove_task(self, module_name: str, filename: str):
        """移除一个已完成的任务（保留给旧调用兼容）。"""
        key = f"{module_name}:{filename}"
        if key in self._active_tasks:
            item, task_widget = self._active_tasks[key]
            if task_widget.get_progress() < 100:
                task_widget.set_progress(100)
            row = self.task_list.row(item)
            self.task_list.takeItem(row)
            del self._active_tasks[key]
            self._total_done += 1
            self._refresh_pause_all_button()
            self._update_status()
            self._update_total_progress()

    @Slot(str)
    def clear_module(self, module_name: str):
        """清除指定模块的所有活跃任务（不计入结果）。"""
        keys_to_remove = [k for k in self._active_tasks if k.startswith(f"{module_name}:")]
        for key in keys_to_remove:
            item, _ = self._active_tasks[key]
            row = self.task_list.row(item)
            self.task_list.takeItem(row)
            del self._active_tasks[key]
            self._total_done += 1
        self._refresh_pause_all_button()
        self._update_status()
        self._update_total_progress()

    @Slot()
    def clear_all(self):
        self._on_delete_all()

    # ==================== 内部更新 ====================

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

    def _update_result_counts(self):
        success_total = self._success_accumulated + self.success_list.count()
        failure_total = self._failure_accumulated + self.failure_list.count()
        self.success_count_label.setText(f"✅ 成功: {success_total}")
        self.failure_count_label.setText(f"❌ 失败: {failure_total}")

    def _update_total_progress(self):
        """计算并刷新总进度条。总进度 = (已完成*100 + 活跃任务进度之和) / 启动过的任务总数。"""
        total = self._total_started
        if total == 0:
            self.total_progress_bar.setValue(0)
            self.total_info_label.setText("未开始转换")
            return
        active_progress_sum = sum(
            w.get_progress() for _, w in self._active_tasks.values()
        )
        numerator = self._total_done * 100 + active_progress_sum
        percent = int(round(numerator / total))
        percent = max(0, min(100, percent))
        self.total_progress_bar.setValue(percent)

        done = self._total_done
        running = len(self._active_tasks)
        success_total = self._success_accumulated + self.success_list.count()
        failure_total = self._failure_accumulated + self.failure_list.count()
        pending = max(0, total - done - running)
        self.total_info_label.setText(
            f"总计 {total} 个任务 | 已完成 {done} | 进行中 {running} | "
            f"待处理 {pending} | 成功 {success_total} | 失败 {failure_total}"
        )

    # ==================== 主题 ====================

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        self.theme_colors = colors
        self._apply_widget_styles()
        for _, w in self._active_tasks.values():
            w.apply_theme(colors)
        # 重着色结果列表条目
        success_color = colors.get("success")
        error_color = colors.get("error")
        text_color = colors.get("text")
        for i in range(self.success_list.count()):
            self.success_list.item(i).setForeground(success_color or text_color)
        for i in range(self.failure_list.count()):
            self.failure_list.item(i).setForeground(error_color or text_color)
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
                padding: 0px;
                margin: 4px 0px;
            }}
        """)
        btn_style = f"""
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
        """
        self.pause_all_btn.setStyleSheet(btn_style)
        self.delete_all_btn.setStyleSheet(btn_style)
        self.clear_result_btn.setStyleSheet(btn_style)

        group_style = f"""
            QGroupBox {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 12px;
                margin-top: 12px;
                padding-top: 12px;
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
                color: {c['accent']};
            }}
        """
        # 总进度条区域
        for w in self.findChildren(QGroupBox):
            w.setStyleSheet(group_style)

        self.total_info_label.setStyleSheet(
            f"font-size: 13px; color: {c['text_secondary']};"
        )
        self.total_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                color: {c['text']};
                font-weight: bold;
                font-size: 12px;
            }}
            QProgressBar::chunk {{
                background-color: {c['success']};
                border-radius: 6px;
            }}
        """)
        self.success_count_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {c.get('success', '#00d9ff')};"
        )
        self.failure_count_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {c.get('error', '#ff6b6b')};"
        )
        # 结果列表样式
        for lst in (self.success_list, self.failure_list):
            lst.setStyleSheet(f"""
                QListWidget {{
                    background-color: {c['bg']};
                    border: 1px solid {c['border']};
                    border-radius: 8px;
                    padding: 6px;
                    outline: none;
                }}
                QListWidget::item {{
                    background-color: transparent;
                    padding: 4px 6px;
                    font-size: 12px;
                    color: {c['text']};
                }}
            """)
