#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务管理器：队列、并发、取消、状态机、超时。

执行模型：
  - 全局 TaskManager，audio/video/image/doc 四模块各自独立 asyncio.Semaphore
    控制并发（= 设置 max_parallel[module]），模块间名额互不占用；
  - GLOBAL_CEILING 总信号量套在模块信号量外层，作为保护性上限
    （防止四模块全开 8 路时线程爆炸）；
  - 转换执行用 loop.run_in_executor 包裹同步引擎函数（线程池）；
  - should_abort 通过 cancelled set 实现，cb=lambda: task_id in cancelled；
  - 任务状态机：pending → running → (paused|done|failed|cancelled)
    paused 仅对排队中任务生效（引擎无暂停能力，如实实现并在文案说明）；
  - 单文件超时：timeout>0 时用 wait_for 包 executor future，
    超时后把 task_id 加入 cancelled 让后台线程感知中止并清理半成品。
"""

import asyncio
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import super_pool, ws
from .engines import audio_engine, video_engine, image_engine, doc_engine
from .state import MODULES

# =====================================================================
# 常量
# =====================================================================

# 保护性总上限：四模块并行数全开（8×4=32）时，仍最多 16 路并发执行，
# 避免线程池与系统负载爆炸。仅作为安全阀，正常配置下不会触发。
GLOBAL_CEILING = 16

MODULE_LABEL = {
    "audio": "🎵 音频",
    "video": "🎬 视频",
    "image": "🖼️ 图片",
    "doc": "📄 文档",
}

ENGINE_MAP = {
    "audio": audio_engine.run,
    "video": video_engine.run,
    "image": image_engine.convert_image,
    "doc": doc_engine.convert_doc,
}

# 各模块引擎任务字段默认值（鸭子类型任务对象缺失时补齐）
DEFAULTS_BY_MODULE: Dict[str, Dict[str, Any]] = {
    "audio": {"bitrate": None, "sample_rate": None, "channels": None, "normalize": False},
    "video": {"video_bitrate": None, "audio_bitrate": None, "extract_audio": False, "hardware_accel": None},
    "image": {"quality": 92, "scale_mode": None, "keep_exif": True},
    "doc": {"pdf_dpi": 200, "keep_original": True},
}

# 输出扩展名表（用于计算 out_path）
EXT_MAP = {
    "audio": audio_engine.SUPPORTED_AUDIO_FORMATS,
    "image": image_engine.SUPPORTED_IMAGE_FORMATS,
    "doc": doc_engine.SUPPORTED_DOC_FORMATS,
    "video": video_engine.SUPPORTED_VIDEO_FORMATS,
}


# =====================================================================
# 数据类
# =====================================================================

@dataclass
class TaskRecord:
    """单个转换任务的运行状态记录。"""
    task_id: int
    batch_id: str
    module: str
    filename: str
    input_path: str
    output_path: str
    output_format: str
    params: Dict[str, Any]
    # 当前下发尝试令牌：每次（重新）提交唯一，结果按令牌精确匹配，
    # 避免排队取消后迟到的旧执行冒领重试结果
    attempt: int = 0
    status: str = "pending"          # pending/running/paused/done/failed/cancelled
    progress: int = 0
    success: Optional[bool] = None
    message: str = ""
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0


class EngineTask:
    """鸭子类型任务对象：由 TaskRecord + params 构建，供引擎函数使用。

    引擎函数通过 getattr/属性访问 task 字段（input_path / output_path /
    output_format / bitrate / normalize 等），这里把 params 合并到对象上。
    """

    def __init__(self, rec: TaskRecord):
        self.input_path = rec.input_path
        self.output_path = rec.output_path
        self.output_format = rec.output_format
        self.task_id = rec.task_id
        for k, v in rec.params.items():
            setattr(self, k, v)
        for k, v in DEFAULTS_BY_MODULE.get(rec.module, {}).items():
            if not hasattr(self, k):
                setattr(self, k, v)


# =====================================================================
# 工具
# =====================================================================

def unique_output_path(path: str, overwrite: bool = False) -> str:
    """返回可写的输出路径：已存在时自动加 _1/_2 后缀（等价旧 unique_output_path）。"""
    if overwrite or not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"


def compute_output_path(input_path: str, module: str, output_format: str,
                        output_dir: str, overwrite: bool,
                        ext_module: Optional[str] = None) -> str:
    """按输出目录规则生成 out_path（沿用旧 _build_tasks 逻辑）。

    ext_module：扩展名查表所用的模块，默认=module。视频"提取音频"时
    实际产物是音频（如 mp3），需传 "audio"，否则在视频表里查不到
    音频格式会错误地回退为原视频扩展名（.mp4）。
    """
    ext_map = EXT_MAP.get(ext_module or module, {})
    info = ext_map.get(output_format)
    ext = info["ext"] if info else os.path.splitext(input_path)[1] or ".out"
    if output_dir:
        base = os.path.splitext(os.path.basename(input_path))[0]
        out = os.path.join(output_dir, base + ext)
    else:
        base = os.path.splitext(input_path)[0]
        out = base + ext
    return unique_output_path(out, overwrite)


# =====================================================================
# 任务管理器
# =====================================================================

class TaskManager:
    """全局任务管理器：队列驱动 + 信号量限流 + 取消/暂停/重试。"""

    def __init__(self, settings):
        self._settings = settings
        self._tasks: Dict[int, TaskRecord] = {}
        self._queue: "asyncio.Queue[int]" = asyncio.Queue()
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._global_sem: Optional[asyncio.Semaphore] = None
        self._workers: List[asyncio.Task] = []
        self._cancelled: set = set()
        self._paused: set = set()
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._history: List[Dict[str, Any]] = []

        # 超级模式状态：进程上下文 / 管理器 / 引擎（多进程×每进程多线程）
        self._super_enabled = False
        self._super_nproc = 0
        self._super_nthreads = 0
        self._super_ctx = None
        self._super_mgr = None
        self._super_engine: Optional[super_pool.SuperEngine] = None
        self._super_sem: Optional[asyncio.Semaphore] = None
        self._super_reader: Optional[asyncio.Task] = None
        # attempt token -> asyncio.Future（结果经 report_q 按令牌交付）
        self._super_futures: Dict[int, Any] = {}
        self._next_attempt = 1

    # ---- 生命周期 ----
    async def start(self) -> None:
        """按各模块 max_parallel 启动工作协程（每模块独立信号量）。"""
        mp = self._parallel_map()
        self._global_sem = asyncio.Semaphore(GLOBAL_CEILING)
        for m in MODULES:
            self._semaphores[m] = asyncio.Semaphore(mp[m])
        # 工作协程数 = 全局上限：任务先被任意 worker 取出，再由
        # 全局信号量 + 模块信号量限流，模块之间名额互不占用。
        self._workers = [asyncio.create_task(self._worker_loop()) for _ in range(GLOBAL_CEILING)]

    def _parallel_map(self) -> Dict[str, int]:
        """从 settings 读取各模块并行数（缺省按 2）。"""
        raw = self._settings.get("max_parallel", {})
        mp: Dict[str, int] = {m: 2 for m in MODULES}
        if isinstance(raw, dict):
            for m in MODULES:
                try:
                    mp[m] = max(1, min(8, int(raw.get(m, 2))))
                except Exception:
                    pass
        return mp

    async def set_max_parallel(self, module: str, value: int) -> None:
        """热更新单个模块并行数（设置页保存后即时生效）。

        信号量不可改上限，直接换成新实例：
          - 增大 → 更大的信号量，排队任务由空闲 worker 自然取走；
          - 减小 → 更小的信号量，不打断运行中任务（其名额随完成释放），
            后续任务需等名额释放后才能获得。
        """
        if module not in self._semaphores:
            return
        value = max(1, min(8, int(value)))
        self._semaphores[module] = asyncio.Semaphore(value)

    async def shutdown(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        # 超级模式：停读取协程；通知转换进程排空后退出；最后关管理器
        if self._super_reader is not None:
            self._super_reader.cancel()
        if self._super_engine is not None:
            self._super_engine.request_stop()
            await asyncio.get_running_loop().run_in_executor(
                None, self._drain_engine, self._super_engine
            )
        if self._super_mgr is not None:
            # 客户端被 terminate 时可能泄漏引用计数导致挂起：限时等待
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None, self._super_mgr.shutdown
                    ),
                    timeout=2.5,
                )
            except Exception:
                pass

    @staticmethod
    def _drain_engine(engine) -> None:
        """阻塞等待转换进程退出（3s），仍存活则强制结束。"""
        engine.join(3)
        if engine.alive_count():
            engine.terminate()

    # ---- 超级模式（多进程 × 每进程多线程） ----
    async def apply_super(self, enabled: bool, nproc: int, nthreads: int) -> None:
        """开关超级模式并设置进程数/每进程并发数（设置保存后即时生效）。

        - 开启且进程数或线程数变化：创建新引擎（新常驻进程组）；
          旧引擎收到哨兵后排空在途任务自然退出，不打断转换，结果照常交付；
        - 关闭：同理发停止哨兵释放进程；ctx/mgr/队列/读取协程保留复用。
        """
        nproc = max(2, min(8, int(nproc)))
        nthreads = max(1, min(8, int(nthreads)))
        loop = asyncio.get_running_loop()
        async with self._lock:
            if not enabled:
                self._super_enabled = False
                self._super_nproc = 0
                self._super_nthreads = 0
                self._super_sem = None
                old = self._super_engine
                self._super_engine = None
                if old is not None:
                    old.request_stop()
                    loop.run_in_executor(None, self._drain_engine, old)
                return

            # created_new：是否为首次初始化（失败时需整体回滚）
            created_new = self._super_ctx is None
            try:
                if created_new:
                    # Linux 用 fork（启动快、继承已加载的 PyAV）；其余平台默认 spawn
                    ctx_name = "fork" if sys.platform.startswith("linux") else None
                    self._super_ctx = (
                        mp.get_context(ctx_name) if ctx_name else mp.get_context()
                    )
                    # report_q/cancelled 经 Manager 代理跨引擎共享
                    # （代理对象可 pickle）；task_q 由每个引擎私有自建
                    self._super_mgr = self._super_ctx.Manager()
                    self._super_report_q = self._super_mgr.Queue()
                    self._super_cancelled = self._super_mgr.list()
                    self._super_reader = asyncio.create_task(self._pump_super())
                if (self._super_engine is None
                        or self._super_nproc != nproc
                        or self._super_nthreads != nthreads):
                    old = self._super_engine
                    self._super_engine = super_pool.SuperEngine(
                        self._super_ctx, self._super_mgr, nproc, nthreads,
                        self._super_report_q, self._super_cancelled,
                    )
                    self._super_sem = asyncio.Semaphore(
                        self._super_engine.total_slots
                    )
                    self._super_nproc = nproc
                    self._super_nthreads = nthreads
                    if old is not None:
                        # 旧进程排空在途任务后退出（不取消，结果经 future 交付）
                        old.request_stop()
                        loop.run_in_executor(None, self._drain_engine, old)
                self._super_enabled = True
            except Exception:
                # 首次创建偶发失败（多线程进程中 fork Manager 时序问题等）：
                # 记录完整 traceback（日志页可查），回滚半初始化状态，
                # 用户再次保存即可重建（自愈）
                import traceback
                detail = traceback.format_exc()
                if created_new:
                    if self._super_reader is not None:
                        self._super_reader.cancel()
                    if self._super_mgr is not None:
                        try:
                            self._super_mgr.shutdown()
                        except Exception:
                            pass
                    self._super_ctx = None
                    self._super_mgr = None
                    self._super_reader = None
                self._super_engine = None
                self._super_sem = None
                self._super_nproc = 0
                self._super_nthreads = 0
                self._super_enabled = False
                ws.push_log("error", f"超级模式初始化失败（再次保存可重试）：\n{detail}")
                await ws.manager.broadcast(
                    ws.msg_log("error", f"超级模式初始化失败（再次保存可重试）：\n{detail}")
                )
                raise

    async def _pump_super(self) -> None:
        """读取转换进程上行：进度→广播；结果→交付对应 future。"""
        loop = asyncio.get_running_loop()
        while True:
            try:
                item = await loop.run_in_executor(
                    None, self._super_report_q.get
                )
            except Exception:
                break
            if not item:
                continue
            kind = item[0]
            if kind == "progress":
                _, task_id, pct = item
                rec = self._tasks.get(task_id)
                if rec is None:
                    continue
                rec.progress = pct
                await ws.manager.broadcast(
                    ws.msg_progress(rec.module, task_id, pct)
                )
            elif kind == "result":
                _, attempt, ok, msg = item
                # 仅匹配本次尝试的 future；排队取消后的迟到旧结果自动丢弃
                fut = self._super_futures.pop(attempt, None)
                if fut is not None and not fut.done():
                    fut.set_result((ok, msg))

    def _submit_super(self, rec: TaskRecord) -> Any:
        """下发任务到转换进程组，返回等待结果的 asyncio future。"""
        attempt = self._next_attempt
        self._next_attempt += 1
        rec.attempt = attempt
        fut = asyncio.get_running_loop().create_future()
        self._super_futures[attempt] = fut
        fields = {
            "module": rec.module,
            "input_path": rec.input_path,
            "output_path": rec.output_path,
            "output_format": rec.output_format,
            "task_id": rec.task_id,
            "attempt": attempt,
            "params": rec.params,
        }
        self._super_engine.submit(fields)
        return fut

    def _new_batch_id(self) -> str:
        return f"batch-{int(time.time() * 1000)}"

    # ---- 提交 ----
    async def submit(self, module: str, files: List[Dict[str, str]], output_dir: str,
                     output_format: str, params: Dict[str, Any],
                     overwrite: bool) -> List[TaskRecord]:
        """提交一批任务：生成 out_path、创建记录并入队。返回本批次任务列表。"""
        batch_id = self._new_batch_id()
        created: List[TaskRecord] = []
        async with self._lock:
            for f in files:
                input_path = f.get("path", "")
                filename = os.path.basename(input_path)
                task_id = self._next_id
                self._next_id += 1

                if not os.path.isfile(input_path):
                    rec = TaskRecord(
                        task_id=task_id, batch_id=batch_id, module=module,
                        filename=filename, input_path=input_path,
                        output_path="", output_format=output_format,
                        params=dict(params), status="failed",
                        success=False, message=f"文件不存在或不可读：{input_path}",
                        finished_at=time.time(),
                    )
                    self._tasks[task_id] = rec
                    await self._record_finish(rec)
                    created.append(rec)
                    continue

                # 视频提取音频：产物是音频流，按音频格式表确定扩展名
                is_extract_audio = (module == "video"
                                    and bool(params.get("extract_audio")))
                out_path = compute_output_path(
                    input_path, module, output_format, output_dir, overwrite,
                    ext_module="audio" if is_extract_audio else None,
                )
                # 确保输出目录存在（audio/video 引擎不自动建目录）
                try:
                    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                except Exception:
                    pass
                rec = TaskRecord(
                    task_id=task_id, batch_id=batch_id, module=module,
                    filename=filename, input_path=input_path,
                    output_path=out_path, output_format=output_format,
                    params=dict(params),
                )
                self._tasks[task_id] = rec
                self._queue.put_nowait(task_id)
                created.append(rec)
        return created

    # ---- 工作循环 ----
    async def _worker_loop(self) -> None:
        while True:
            task_id = await self._queue.get()
            await self._process_task(task_id)

    async def _process_task(self, task_id: int) -> None:
        rec = self._tasks.get(task_id)
        if rec is None:
            return
        # 超级模式：由总名额信号量限流（N×T），不再经过模块信号量/全局上限
        if self._super_enabled and self._super_engine is not None:
            if self._super_sem is None:
                return
            async with self._super_sem:
                await self._run_one(rec)
            return
        # 普通模式：先拿全局兜底上限，再拿模块信号量
        async with self._global_sem:
            module_sem = self._semaphores.get(rec.module)
            if module_sem is None:
                return
            async with module_sem:
                await self._run_one(rec)

    async def _run_one(self, rec: TaskRecord) -> None:
        """已获得全局 + 模块名额后，执行单个任务的主体逻辑。"""
        task_id = rec.task_id

        # 排队中暂停：等待恢复（每 200ms 检查一次）
        while task_id in self._paused:
            if task_id in self._cancelled:
                break
            await asyncio.sleep(0.2)

        if task_id in self._cancelled:
            await self._finish(rec, "cancelled", False, "已取消")
            return

        rec.status = "running"
        rec.started_at = time.time()
        await ws.manager.broadcast(ws.msg_task_start(rec.module, rec.task_id, rec.filename))
        await self._emit_log("info", f"{MODULE_LABEL[rec.module]} 开始转换: {rec.filename}")

        loop = asyncio.get_running_loop()
        use_super = self._super_enabled and self._super_engine is not None

        if use_super:
            # 超级模式：下发到转换进程组；进度/结果由 _pump_super 经
            # report_q 读取；中止通过共享 cancelled 列表
            engine_awaitable = self._submit_super(rec)
        else:
            # 普通模式：同步引擎丢线程池，进度回调 4 次/秒节流
            # （>=250ms），100 强制发送
            last_emit = {"t": 0.0}

            def progress_cb(percent: int) -> None:
                rec.progress = max(0, min(100, int(percent)))
                now = time.monotonic()
                if rec.progress == 100 or (now - last_emit["t"]) >= 0.25:
                    last_emit["t"] = now
                    asyncio.run_coroutine_threadsafe(
                        ws.manager.broadcast(ws.msg_progress(rec.module, rec.task_id, rec.progress)),
                        loop,
                    )

            def abort_cb() -> bool:
                return task_id in self._cancelled

            engine_awaitable = loop.run_in_executor(
                None, ENGINE_MAP[rec.module], EngineTask(rec), progress_cb, abort_cb
            )

        timeout_s = int(self._settings.get("task_timeout_minutes", 0) or 0) * 60
        started = time.monotonic()
        try:
            if timeout_s > 0:
                ok, msg = await asyncio.wait_for(engine_awaitable, timeout=timeout_s)
            else:
                ok, msg = await engine_awaitable
        except asyncio.TimeoutError:
            # 通知转换进程感知中止（引擎会删除半成品），随后标记失败
            self._cancelled.add(task_id)
            if self._super_engine is not None:
                self._super_engine.request_cancel(task_id)
            self._delete_partial(rec)
            ok, msg = False, f"转换超时（>{timeout_s} 秒），已终止"
        except BaseException as e:
            # 引擎重建等场景 future 理论上不会被取消（队列共享）；
            # CancelledError 属 BaseException，协程取消时继续向上抛
            if isinstance(e, asyncio.CancelledError):
                raise
            self._delete_partial(rec)
            ok, msg = False, f"转换异常: {e}"
        finally:
            # 清除取消标记：保证同 id 重试不会被立即中止
            if self._super_engine is not None:
                self._super_engine.clear_cancel(task_id)

        rec.duration_ms = (time.monotonic() - started) * 1000.0

        if task_id in self._cancelled and not ok:
            await self._finish(rec, "cancelled", False, "已取消")
        else:
            status = "done" if ok else "failed"
            await self._finish(rec, status, ok, msg)

    # ---- 结束 ----
    async def _finish(self, rec: TaskRecord, status: str, success: bool, message: str) -> None:
        rec.status = status
        rec.success = bool(success)
        rec.message = message
        rec.finished_at = time.time()
        await ws.manager.broadcast(ws.msg_task_result(
            rec.module, rec.task_id, bool(success), message, rec.duration_ms
        ))
        await self._record_finish(rec)

    async def _record_finish(self, rec: TaskRecord) -> None:
        """写历史 + 发日志（成功/失败/取消 分别处理）。"""
        if rec.status == "done":
            level = "success"
        elif rec.status == "cancelled":
            level = "warning"
        else:
            level = "error"
        first_line = (rec.message or "").splitlines()[0] or ("转换成功" if rec.success else "转换失败")
        await self._emit_log(level, f"{MODULE_LABEL[rec.module]} {rec.filename} — {first_line}")

        entry = {
            "task_id": rec.task_id,
            "module": rec.module,
            "filename": rec.filename,
            "input_path": rec.input_path,
            "output_path": rec.output_path,
            "output_format": rec.output_format,
            "status": rec.status,
            "success": rec.success,
            "message": rec.message,
            "duration_ms": rec.duration_ms,
            "finished_at": rec.finished_at,
        }
        self._history.append(entry)
        if len(self._history) > 50:
            self._history = self._history[-50:]

    async def _emit_log(self, level: str, message: str) -> None:
        ws.push_log(level, message)
        await ws.manager.broadcast(ws.msg_log(level, message))

    # ---- 控制 ----
    async def cancel(self, task_id: int) -> Dict[str, Any]:
        """取消任务：加入 cancelled 集合并置状态。"""
        rec = self._tasks.get(task_id)
        if rec is None:
            return {"ok": False, "message": f"任务 {task_id} 不存在"}
        if rec.status in ("done", "failed", "cancelled"):
            return {"ok": False, "message": f"任务 {task_id} 已结束（{rec.status}），无法取消"}
        self._cancelled.add(task_id)
        self._paused.discard(task_id)
        # 超级模式：通过共享取消列表通知转换进程中止
        if self._super_engine is not None:
            self._super_engine.request_cancel(task_id)
        if rec.status == "pending":
            # 已下发到队列的任务撤不回：立即作废本次尝试的 future，
            # 迟到的旧执行结果回来时找不到 future，自动忽略
            fut = self._super_futures.pop(rec.attempt, None)
            if fut is not None and not fut.done():
                fut.cancel()
            await self._finish(rec, "cancelled", False, "已取消")
        # running 状态由引擎解码循环感知 abort 后自行结束
        return {"ok": True, "message": f"已请求取消任务 {task_id}"}

    async def retry(self, task_id: int) -> Dict[str, Any]:
        """重试已结束（done/failed/cancelled）的任务。"""
        rec = self._tasks.get(task_id)
        if rec is None:
            return {"ok": False, "message": f"任务 {task_id} 不存在"}
        if rec.status not in ("done", "failed", "cancelled"):
            return {"ok": False, "message": f"任务 {task_id} 仍在进行中（{rec.status}），无法重试"}
        if not os.path.isfile(rec.input_path):
            return {"ok": False, "message": f"源文件不存在：{rec.input_path}"}
        # 重置状态并入队
        rec.status = "pending"
        rec.success = None
        rec.message = ""
        rec.progress = 0
        rec.duration_ms = 0.0
        rec.started_at = 0.0
        rec.finished_at = 0.0
        self._cancelled.discard(task_id)
        self._paused.discard(task_id)
        # 超级模式：清除共享取消标记，否则重新下发会被立即中止
        if self._super_engine is not None:
            self._super_engine.clear_cancel(task_id)
        # 重新生成唯一输出路径
        rec.output_path = unique_output_path(
            rec.output_path, overwrite=False
        ) if os.path.exists(rec.output_path) else rec.output_path
        self._queue.put_nowait(task_id)
        return {"ok": True, "message": f"任务 {task_id} 已重新入队"}

    async def pause(self, task_id: int) -> Dict[str, Any]:
        """暂停任务：仅对排队中（pending）任务生效。"""
        rec = self._tasks.get(task_id)
        if rec is None:
            return {"ok": False, "message": f"任务 {task_id} 不存在"}
        if rec.status == "running":
            return {"ok": False, "message": "引擎无暂停能力，暂停仅对排队中的任务生效"}
        if rec.status != "pending":
            return {"ok": False, "message": f"任务 {task_id} 状态为 {rec.status}，无法暂停"}
        self._paused.add(task_id)
        rec.status = "paused"
        await ws.manager.broadcast({
            "type": "task_paused", "module": rec.module, "task_id": rec.task_id,
        })
        return {"ok": True, "message": f"任务 {task_id} 已暂停（排队中）"}

    async def resume(self, task_id: int) -> Dict[str, Any]:
        """恢复暂停的任务。"""
        rec = self._tasks.get(task_id)
        if rec is None:
            return {"ok": False, "message": f"任务 {task_id} 不存在"}
        if rec.status != "paused":
            return {"ok": False, "message": f"任务 {task_id} 当前不是暂停状态"}
        self._paused.discard(task_id)
        rec.status = "pending"
        await ws.manager.broadcast({
            "type": "task_resumed", "module": rec.module, "task_id": rec.task_id,
        })
        return {"ok": True, "message": f"任务 {task_id} 已恢复"}

    # ---- 查询 ----
    def task_to_dict(self, rec: TaskRecord) -> Dict[str, Any]:
        return {
            "task_id": rec.task_id,
            "batch_id": rec.batch_id,
            "module": rec.module,
            "filename": rec.filename,
            "input_path": rec.input_path,
            "output_path": rec.output_path,
            "output_format": rec.output_format,
            "status": rec.status,
            "progress": rec.progress,
            "success": rec.success,
            "message": rec.message,
            "duration_ms": rec.duration_ms,
            "created_at": rec.created_at,
            "finished_at": rec.finished_at,
        }

    def get_active(self) -> List[Dict[str, Any]]:
        """当前进行中（pending/running/paused）的任务列表。"""
        active = [
            rec for rec in self._tasks.values()
            if rec.status in ("pending", "running", "paused")
        ]
        return [self.task_to_dict(r) for r in active]

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        rec = self._tasks.get(task_id)
        return self.task_to_dict(rec) if rec else None

    # ---- 清理 ----
    @staticmethod
    def _delete_partial(rec: TaskRecord) -> None:
        try:
            if rec.output_path and os.path.exists(rec.output_path):
                os.remove(rec.output_path)
        except Exception:
            pass
