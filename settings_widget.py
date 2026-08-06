import os
from PySide6.QtCore import Qt, Signal, Slot, QSettings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QLineEdit,
    QPushButton, QFileDialog, QApplication,
)

from utils import (
    ThemeManager, get_cjk_font_qss, APP_NAME, ORG_NAME,
)


class SettingsWidget(QWidget):
    """全局设置面板：默认输出目录 + 界面外观主题（暗/亮两套）。"""

    default_output_dir_changed = Signal(str)

    def __init__(self, parent=None, initial_theme: str = "dark",
                 initial_output_dir: str = ""):
        super().__init__(parent)
        self.theme_colors = ThemeManager.instance().current_colors
        self._default_output_dir = (initial_output_dir or "").strip()
        self._current_theme = (initial_theme or "dark").lower()
        if self._current_theme not in ("dark", "light"):
            self._current_theme = "dark"
        self._settings = QSettings(ORG_NAME, APP_NAME)
        self._setup_ui()
        self._apply_widget_styles()
        self._update_theme_button_states()

    # ---------------------- UI ----------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(20)

        header = QLabel("⚙️  全局设置")
        header.setObjectName("titleLabel")
        subtitle = QLabel(
            "默认输出文件夹 & 界面外观主题，修改后立即生效，并在下次启动时自动加载。"
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        root.addWidget(header)
        root.addWidget(subtitle)
        root.addSpacing(4)

        # -------- Group 1: 默认输出文件夹 --------
        self.output_group = QGroupBox("默认输出文件夹")
        out_layout = QVBoxLayout(self.output_group)
        out_layout.setContentsMargins(16, 24, 16, 16)
        out_layout.setSpacing(12)

        hint = QLabel(
            "四个转换模块在新建任务时，若未在该模块中单独指定输出目录，"
            "将自动使用此处设置的默认路径。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        out_layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.output_path_edit = QLineEdit(self._default_output_dir)
        self.output_path_edit.setPlaceholderText(
            "留空 = 在源文件同目录输出（默认）"
        )
        self.output_path_edit.editingFinished.connect(self._on_path_edited)
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.setFixedWidth(110)
        self.browse_btn.clicked.connect(self._on_browse)
        self.reset_path_btn = QPushButton("重置（同目录）")
        self.reset_path_btn.setFixedWidth(160)
        self.reset_path_btn.clicked.connect(self._on_reset_path)
        row.addWidget(self.output_path_edit, 1)
        row.addWidget(self.browse_btn, 0)
        row.addWidget(self.reset_path_btn, 0)
        out_layout.addLayout(row)

        self.current_path_label = QLabel(self._format_current_path_hint())
        self.current_path_label.setObjectName("hintLabel")
        out_layout.addWidget(self.current_path_label)

        root.addWidget(self.output_group)

        # -------- Group 2: 界面外观 --------
        self.appearance_group = QGroupBox("界面外观")
        app_layout = QVBoxLayout(self.appearance_group)
        app_layout.setContentsMargins(16, 24, 16, 16)
        app_layout.setSpacing(12)

        theme_hint = QLabel(
            "选择主题后将立即全局生效（包含四个转换模块及所有控件），"
            "跨会话自动保存。"
        )
        theme_hint.setObjectName("hintLabel")
        theme_hint.setWordWrap(True)
        app_layout.addWidget(theme_hint)

        themes_row = QHBoxLayout()
        themes_row.setSpacing(16)

        self.dark_btn = QPushButton("🌙  暗色主题")
        self.dark_btn.setMinimumHeight(88)
        self.dark_btn.setCheckable(True)
        self.dark_btn.clicked.connect(lambda: self._on_select_theme("dark"))

        self.light_btn = QPushButton("☀️  亮色主题")
        self.light_btn.setMinimumHeight(88)
        self.light_btn.setCheckable(True)
        self.light_btn.clicked.connect(lambda: self._on_select_theme("light"))

        themes_row.addWidget(self.dark_btn, 1)
        themes_row.addWidget(self.light_btn, 1)
        app_layout.addLayout(themes_row)

        root.addWidget(self.appearance_group)
        root.addStretch(1)

    # ---------------------- 路径 ----------------------

    def _format_current_path_hint(self) -> str:
        p = (self._default_output_dir or "").strip()
        if not p:
            return "当前：留空，转换结果默认保存在各源文件所在目录。"
        if not os.path.isdir(p):
            return (
                f"当前：{p}\n"
                f"（路径不存在，将在首次使用时自动创建）"
            )
        return f"当前：{p}"

    def _on_browse(self):
        start_dir = self._default_output_dir or os.path.expanduser("~")
        if start_dir and not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(
            self, "选择默认输出文件夹", start_dir
        )
        if d:
            self._set_output_path(d, persist=True)

    def _on_reset_path(self):
        self._set_output_path("", persist=True)

    def _on_path_edited(self):
        self._set_output_path(self.output_path_edit.text().strip(), persist=True)

    def _set_output_path(self, path: str, persist: bool = False):
        self._default_output_dir = path or ""
        self.output_path_edit.setText(self._default_output_dir)
        self.current_path_label.setText(self._format_current_path_hint())
        if persist:
            # 同时写 QSettings + 信号通知四个模块
            self._settings.setValue("Settings/default_output_dir",
                                    self._default_output_dir)
            self._settings.sync()
            self.default_output_dir_changed.emit(self._default_output_dir)

    def set_default_output_dir(self, path: str):
        """供外部（比如 main 里 QSettings 加载）刷新 UI 显示，不重复发信号。"""
        self._set_output_path((path or "").strip(), persist=False)

    # ---------------------- 主题 ----------------------

    def _on_select_theme(self, theme_name: str):
        if theme_name == self._current_theme:
            return
        self._current_theme = theme_name
        app = QApplication.instance()
        if app is not None:
            new_colors = ThemeManager.instance().apply_theme(app, theme_name)
            self.theme_colors = new_colors
            self._settings.setValue("Settings/theme", theme_name)
            self._settings.sync()
            self._update_theme_button_states()
            self._apply_widget_styles()
        else:
            self._update_theme_button_states()

    def _update_theme_button_states(self):
        dark_on = (self._current_theme == "dark")
        self.dark_btn.setChecked(dark_on)
        self.light_btn.setChecked(not dark_on)

    @Slot(dict)
    def reapply_theme(self, colors: dict):
        """ThemeManager.theme_changed 通知时刷新局部样式和选中态。"""
        self.theme_colors = colors
        self._current_theme = ThemeManager.instance().current_theme
        self._update_theme_button_states()
        self._apply_widget_styles()

    # ---------------------- 样式 ----------------------

    def _apply_widget_styles(self):
        c = self.theme_colors
        group_style = f"""
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
        """
        self.output_group.setStyleSheet(group_style)
        self.appearance_group.setStyleSheet(group_style)

        btn_base = f"""
            QPushButton {{
                background-color: {c["card"]};
                color: {c["text"]};
                border: 1px solid {c["border"]};
                border-radius: 10px;
                padding: 12px 16px;
                font-size: 15px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {c["card_hover"]};
                border-color: {c["success"]};
            }}
            QPushButton:pressed {{
                background-color: {c["border"]};
            }}
        """
        btn_checked = f"""
            QPushButton {{
                background-color: {c["card_hover"]};
                color: {c["success"]};
                border: 2px solid {c["success"]};
                border-radius: 10px;
                padding: 12px 16px;
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {c["success_hover"]};
            }}
        """
        self.dark_btn.setStyleSheet(
            btn_checked if self._current_theme == "dark" else btn_base
        )
        self.light_btn.setStyleSheet(
            btn_checked if self._current_theme == "light" else btn_base
        )

        action_style = f"""
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
        """
        self.browse_btn.setStyleSheet(action_style)
        self.reset_path_btn.setStyleSheet(action_style)

        self.output_path_edit.setStyleSheet(f"""
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
        """)
