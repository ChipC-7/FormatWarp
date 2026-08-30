#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FormatWarp FastAPI 后端入口。

- REST 路由（/api/...）+ WebSocket /ws；
- lifespan：探测引擎（PyAV / Pillow / 文档链）、加载设置、启动任务管理器；
- 端口重试：默认 8765，被占用则 +1（最多 5 次），实际端口写 stdout
  "FORMATWARP_PORT=xxxx" 供 Tauri Rust 壳解析。

启动方式：
  uvicorn backend.app:app --port 8765
  或直接 python -m backend.app（自动端口重试）
"""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import tasks as tasks_mod
from . import ws
from .models import CreateTaskRequest, OpenPathRequest, SettingsModel
from .state import SettingsStore
from .engines import audio_engine, video_engine, image_engine, doc_engine

import av_engine  # 项目根目录的 av_engine（backend.engines.__init__ 已加 sys.path）

APP_VERSION = "3.0.0"

# =====================================================================
# 引擎探测
# =====================================================================

def probe_engines() -> Dict[str, Any]:
    """探测各引擎可用性（供 /api/health 与 engine_status 推送）。"""
    av_ok, av_version = av_engine.check_av_available()
    gpu = av_engine.detect_gpu_encoders() if av_ok else {}
    av_extra = {"muxers": 0, "encoders": 0}
    if av_ok:
        caps = av_engine.get_supported_formats()
        av_extra["muxers"] = len(caps.get("muxers", set()))
        av_extra["encoders"] = len(caps.get("encoders", set()))
    return {
        "av": {
            "available": av_ok,
            "version": av_version,
            "gpu": gpu,
            "muxers": av_extra["muxers"],
            "encoders": av_extra["encoders"],
        },
        "pillow": image_engine.pillow_available(),
        "doc": doc_engine.probe(),
    }


def disk_free_gb() -> float:
    """默认输出目录或家目录所在盘的剩余空间（GB）。"""
    try:
        return round(shutil.disk_usage("/").free / (1024 ** 3), 2)
    except Exception:
        return 0.0


# =====================================================================
# FastAPI 应用与 lifespan
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动探测 + 配置 + 任务管理器
    engine_status = probe_engines()
    settings = SettingsStore()
    tm = tasks_mod.TaskManager(settings)
    await tm.start()

    app.state.engine_status = engine_status
    app.state.settings = settings
    app.state.tm = tm

    ws.push_log("info", f"后端启动完成，引擎状态: PyAV={engine_status['av']['available']} "
                        f"Pillow={engine_status['pillow']}")
    try:
        yield
    finally:
        await tm.shutdown()


app = FastAPI(title="FormatWarp 后端", version=APP_VERSION, lifespan=lifespan)

# 开发期允许任意来源（Tauri WebView 生产环境由 Rust 侧管控）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tm() -> tasks_mod.TaskManager:
    return app.state.tm


def _settings() -> SettingsStore:
    return app.state.settings


# =====================================================================
# 健康检查
# =====================================================================

@app.get("/api/health")
async def health() -> Dict[str, Any]:
    """引擎与磁盘健康状态（含当前生效的各模块并行数）。"""
    return {
        "ok": True,
        "port": 0,  # 实际端口由启动脚本填充（Rust 壳解析 FORMATWARP_PORT）
        "version": APP_VERSION,
        "engines": probe_engines(),
        "disk_free_gb": disk_free_gb(),
        "parallel": dict(_settings().get("max_parallel", {})),
    }


# =====================================================================
# 格式信息
# =====================================================================

FORMATS_INFO_MAP = {
    "audio": audio_engine.formats_info,
    "video": video_engine.formats_info,
    "image": image_engine.formats_info,
    "doc": doc_engine.formats_info,
}


def _precheck_outputs(outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐个输出格式做编码器/封装器预检，附加 supported / unsupported_reason。

    av_engine.check_output_supported 返回 None 表示可输出；返回文案表示
    不受支持，该文案直接作为前端置灰悬停的提示。
    """
    checked: List[Dict[str, Any]] = []
    for o in outputs:
        item = {"key": o["key"], "desc": o["desc"], "ext": o["ext"]}
        reason = av_engine.check_output_supported(item["key"])
        if reason is None:
            item["supported"] = True
        else:
            item["supported"] = False
            item["unsupported_reason"] = reason
        checked.append(item)
    return checked


@app.get("/api/formats")
async def formats(module: str = Query(...)) -> Dict[str, Any]:
    """按模块返回输入格式、输出格式与预设表。

    - audio/video：每个输出格式带 supported 预检标记（缺编码器/封装器的
      格式在 UI 置灰，从源头避免无效提交）；
    - video：另返回 extract_audio_outputs（「提取音频」的 8 种音频格式，
      同样带 supported 标记），前端据此渲染第二组下拉，无需硬编码；
    - image/doc：输出格式默认全部 supported。
    """
    info_fn = FORMATS_INFO_MAP.get(module)
    if info_fn is None:
        return {"error": f"未知模块：{module}（可选 audio/video/image/doc）"}
    info = info_fn()
    if module == "video":
        # 拆分「提取音频」格式为独立数组（video_engine 把两类格式混在 outputs）
        regular, extract = [], []
        for o in info.get("outputs", []):
            (extract if o.get("extract_audio") else regular).append(o)
        info["outputs"] = _precheck_outputs(regular)
        info["extract_audio_outputs"] = _precheck_outputs(extract)
    elif module == "audio":
        info["outputs"] = _precheck_outputs(info.get("outputs", []))
    else:
        # image/doc：默认全部支持
        for o in info.get("outputs", []):
            o["supported"] = True
    return info


# =====================================================================
# 任务
# =====================================================================

@app.post("/api/tasks")
async def create_tasks(req: CreateTaskRequest) -> Dict[str, Any]:
    """提交一批转换任务，立即返回 batch_id 与任务列表。"""
    tm = _tm()
    if not req.files:
        return {"error": "files 不能为空"}
    records = await tm.submit(
        req.module, [f.model_dump() for f in req.files],
        req.output_dir, req.output_format, req.params, req.overwrite,
    )
    batch_id = records[0].batch_id if records else None
    return {
        "batch_id": batch_id,
        "tasks": [tm.task_to_dict(r) for r in records],
    }


@app.get("/api/tasks")
async def list_tasks() -> Dict[str, Any]:
    """返回进行中任务与最近历史（50 条）。"""
    tm = _tm()
    return {"active": tm.get_active(), "history": tm.get_history()}


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: int) -> Dict[str, Any]:
    return await _tm().cancel(task_id)


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: int) -> Dict[str, Any]:
    return await _tm().retry(task_id)


@app.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: int) -> Dict[str, Any]:
    return await _tm().pause(task_id)


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: int) -> Dict[str, Any]:
    return await _tm().resume(task_id)


# =====================================================================
# 设置
# =====================================================================

@app.get("/api/settings")
async def get_settings() -> Dict[str, Any]:
    return _settings().as_dict()


@app.post("/api/settings")
async def set_settings(payload: SettingsModel) -> Dict[str, Any]:
    s = _settings()
    s.set_many(payload.model_dump())
    # 按模块热更新并行数：设置保存后即时生效（无需重启）
    for module, value in payload.max_parallel.items():
        await _tm().set_max_parallel(module, value)
    return {"ok": True, "settings": s.as_dict()}


# =====================================================================
# 打开文件管理器
# =====================================================================

@app.post("/api/open_path")
async def open_path(payload: OpenPathRequest) -> Dict[str, Any]:
    """用系统文件管理器打开指定路径。"""
    path = payload.path.strip()
    if not path or not os.path.exists(path):
        return {"ok": False, "message": f"路径不存在：{path}"}
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], timeout=10)
        else:
            subprocess.run(["xdg-open", path], timeout=10)
        return {"ok": True, "message": "已请求打开"}
    except Exception as e:
        return {"ok": False, "message": f"打开失败：{e}"}


# =====================================================================
# 日志
# =====================================================================

@app.get("/api/logs")
async def logs(limit: int = Query(200, ge=1, le=500)) -> List[Dict[str, Any]]:
    return ws.get_logs(limit)


# =====================================================================
# WebSocket /ws
# =====================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await ws.manager.connect(websocket)
    try:
        # 连接建立时先推一次引擎状态
        await websocket.send_json(ws.msg_engine_status(probe_engines()))
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json(ws.msg_pong())
            elif data.get("type") == "engine_status":
                await websocket.send_json(ws.msg_engine_status(probe_engines()))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws.manager.disconnect(websocket)


# =====================================================================
# 端口重试启动（Rust 壳侧载）
# =====================================================================

def find_free_port(base: int = 8765, attempts: int = 5) -> int:
    """从 base 起尝试绑定，返回第一个可用端口。"""
    for port in range(base, base + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return base  # 全部占用则交回 uvicorn 报错


def main() -> None:
    """启动入口：端口重试 + stdout 上报 FORMATWARP_PORT + uvicorn。

    - `python -m backend.app` 直接运行；
    - 打包后的 sidecar 由 backend/sidecar_entry.py 调用本函数
      （避免相对导入在 PyInstaller/Nuitka 冻结环境下失效）。
    """
    import uvicorn

    port = find_free_port()
    # 供 Tauri Rust 壳解析
    print(f"FORMATWARP_PORT={port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
