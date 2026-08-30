#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebSocket /ws：连接管理 + 广播 + 消息模型 + 日志环形缓冲。

消息协议（server→client）：
  {"type":"task_start",   "module":"audio","task_id":3,"filename":"a.mp3"}
  {"type":"progress",     "module":"audio","task_id":3,"percent":42}
  {"type":"task_result",  "module":"audio","task_id":3,"success":true,
   "message":"...","duration_ms":123}
  {"type":"log",          "level":"info|success|warning|error","message":"..."}
  {"type":"engine_status", "engine":{...}}          # 连接建立时先推一次
client→server：
  {"type":"ping"}                                    # 服务端回 {"type":"pong"}
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List

from fastapi import WebSocket

# =====================================================================
# 日志环形缓冲（供 GET /api/logs 读取）
# =====================================================================

MAX_LOG_ITEMS = 200
LOG_BUFFER: List[Dict[str, Any]] = []


def push_log(level: str, message: str) -> None:
    """记录一条日志到环形缓冲。"""
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "message": message,
    }
    LOG_BUFFER.append(entry)
    if len(LOG_BUFFER) > MAX_LOG_ITEMS:
        del LOG_BUFFER[: len(LOG_BUFFER) - MAX_LOG_ITEMS]


def get_logs(limit: int = 200) -> List[Dict[str, Any]]:
    return list(LOG_BUFFER[-limit:])


# =====================================================================
# 连接管理
# =====================================================================

class ConnectionManager:
    """WebSocket 连接集合与广播。"""

    def __init__(self):
        self._connections: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """向所有已连接客户端广播一条消息。"""
        async with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                self._connections.discard(ws)


manager = ConnectionManager()


# =====================================================================
# 消息模型
# =====================================================================

def msg_task_start(module: str, task_id: int, filename: str) -> Dict[str, Any]:
    return {"type": "task_start", "module": module, "task_id": task_id, "filename": filename}


def msg_progress(module: str, task_id: int, percent: int) -> Dict[str, Any]:
    return {"type": "progress", "module": module, "task_id": task_id, "percent": int(percent)}


def msg_task_result(module: str, task_id: int, success: bool, message: str,
                    duration_ms: float = 0.0) -> Dict[str, Any]:
    return {
        "type": "task_result",
        "module": module,
        "task_id": task_id,
        "success": bool(success),
        "message": message,
        "duration_ms": duration_ms,
    }


def msg_log(level: str, message: str) -> Dict[str, Any]:
    return {"type": "log", "level": level, "message": message}


def msg_engine_status(engine: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "engine_status", "engine": engine}


def msg_pong() -> Dict[str, Any]:
    return {"type": "pong", "ts": time.time()}
