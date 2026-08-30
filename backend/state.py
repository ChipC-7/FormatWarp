#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用配置读写（JSON 文件）+ 日志目录（零 Qt / 零 FastAPI 依赖）。

配置路径：
  - Windows: %APPDATA%/FormatWarp/settings.json
  - macOS:   ~/Library/Application Support/FormatWarp/settings.json
  - Linux:   ~/.local/share/FormatWarp/settings.json
字段：theme / default_output_dir / max_parallel / task_timeout_minutes。
max_parallel 自 v0.2 起为按模块字典 {"audio":2,"video":2,"image":2,"doc":2}；
旧版本（int）在加载时自动迁移为四模块同值并写回，用户无感。
启动不存在时写入默认值。
日志目录沿用旧 get_log_dir() 的滚动文件方案（路径规则一致）。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

APP_NAME = "FormatWarp"

# 四个转换模块（并发额度按模块独立配置）
MODULES = ("audio", "video", "image", "doc")
DEFAULT_PARALLEL = 2


def _default_parallel() -> Dict[str, int]:
    """四模块默认并行数（每模块 2）。"""
    return {m: DEFAULT_PARALLEL for m in MODULES}


DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "dark",
    "default_output_dir": "",
    "max_parallel": _default_parallel(),
    "task_timeout_minutes": 0,
}


def get_config_dir() -> Path:
    """返回平台相关的应用配置目录。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def get_log_dir() -> Path:
    """返回平台相关的日志目录（沿用旧 utils.get_log_dir 规则）。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME / "logs"


class SettingsStore:
    """配置读写：加载/保存/单字段读取/批量写入。"""

    def __init__(self, path: Optional[Path] = None):
        self.path: Path = path if path is not None else (get_config_dir() / "settings.json")
        self._data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        """从磁盘加载配置；文件缺失或损坏时回退默认值。"""
        try:
            if self.path.exists():
                self._data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass
        self._normalize()

    def _normalize(self) -> None:
        """夹取并校验字段取值范围；max_parallel 旧格式 int 自动迁移为字典。"""
        d = self._data
        if d.get("theme") not in ("dark", "light"):
            d["theme"] = "dark"

        # max_parallel：兼容旧格式（int）→ 四模块同值字典，并写回文件
        raw = d.get("max_parallel")
        migrated = False
        if isinstance(raw, dict):
            mp = {m: raw.get(m, DEFAULT_PARALLEL) for m in MODULES}
        else:
            try:
                val = max(1, min(8, int(raw) if raw is not None else DEFAULT_PARALLEL))
            except Exception:
                val = DEFAULT_PARALLEL
            mp = {m: val for m in MODULES}
            migrated = True
        for m in MODULES:
            try:
                mp[m] = max(1, min(8, int(mp[m])))
            except Exception:
                mp[m] = DEFAULT_PARALLEL
        d["max_parallel"] = mp

        try:
            d["task_timeout_minutes"] = max(0, min(120, int(d.get("task_timeout_minutes", 0))))
        except Exception:
            d["task_timeout_minutes"] = 0
        d["default_output_dir"] = str(d.get("default_output_dir", "") or "")

        # 旧格式迁移：立即写回，用户无感
        if migrated:
            self.save()

    def save(self) -> None:
        """写回磁盘（原子替换）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_many(self, data: Dict[str, Any]) -> None:
        """批量写入并持久化。"""
        self._data.update(data)
        self._normalize()
        self.save()

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)
