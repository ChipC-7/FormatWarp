#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超级模式引擎：常驻多进程，每个转换进程内部用线程池同时转换多个文件。

模型（N 个进程 × 每进程 T 线程 = N×T 个总并发名额）：
  主进程
    │ task_q     任务下行（字段字典；None=哨兵，进程排空后退出）
    │ report_q   进度/结果上行
    │ cancelled  已取消任务 id 列表（Manager 代理，append/成员判断跨进程）
    ▼
  转换进程 ×N：主循环从 task_q 取任务 → 交给本进程 ThreadPoolExecutor(T)
               内的线程执行；收到哨兵后退出（with 块等待在途任务完成）

实测（30 个 WAV→MP3 / 24 逻辑核）：24 纯线程约 20s，
4 进程 × 每进程 6 线程约 11.6s —— 多进程各自独立 GIL，
突破了 PyAV Python 层编排（GIL/内部锁）导致的纯线程扩展性瓶颈。

只依赖 stdlib + 引擎层（不 import fastapi / tasks / ws）。
"""

import os
import threading
from typing import Any, Dict, List, Optional

from .super_proc import DEFAULTS_BY_MODULE, ENGINE_MAP


# =====================================================================
# 转换进程侧
# =====================================================================

def _build_task(module: str, fields: Dict[str, Any]):
    """由可 pickle 字段构建引擎所需的鸭子类型任务对象。"""
    from types import SimpleNamespace

    task = SimpleNamespace(
        input_path=fields["input_path"],
        output_path=fields["output_path"],
        output_format=fields["output_format"],
        task_id=fields["task_id"],
    )
    for k, v in fields.get("params", {}).items():
        setattr(task, k, v)
    for k, v in DEFAULTS_BY_MODULE.get(module, {}).items():
        if not hasattr(task, k):
            setattr(task, k, v)
    return task


def _do_one(fields: Dict[str, Any], report_q, cancelled) -> None:
    """转换进程的工作线程：执行单个文件并上行进度/结果。"""
    import time

    task_id = fields["task_id"]
    attempt = fields.get("attempt", 0)
    module = fields["module"]
    task = _build_task(module, fields)

    last_emit = {"t": 0.0}

    def progress_cb(percent: int) -> None:
        pct = max(0, min(100, int(percent)))
        now = time.monotonic()
        if pct == 100 or (now - last_emit["t"]) >= 0.25:
            last_emit["t"] = now
            try:
                report_q.put(("progress", task_id, pct), timeout=1)
            except Exception:
                pass

    # 引擎可能每帧都查 abort（音频可达上万次）。直接查 Manager 代理
    # 会产生海量阻塞 IPC：本地缓存结果，至多每 100ms 同步一次，
    # 取消响应延迟 ≤0.1s，肉眼无感知
    cache = {"t": 0.0, "v": False}

    def abort_cb() -> bool:
        now = time.monotonic()
        if (now - cache["t"]) >= 0.1:
            try:
                cache["v"] = task_id in cancelled
            except Exception:
                pass
            cache["t"] = now
        return cache["v"]

    try:
        ok, msg = ENGINE_MAP[module](task, progress_cb, abort_cb)
    except Exception as e:
        ok, msg = False, f"转换异常: {e}"
    try:
        # 结果携带尝试令牌，主进程据此精确匹配 future（迟到的旧尝试被忽略）
        report_q.put(("result", attempt, bool(ok), msg), timeout=5)
    except Exception:
        pass


def _collect_listen_fds():
    """主进程侧：找出本进程所有处于 LISTEN 状态的 socket fd。

    子进程 fork 时会继承这些 fd；若父进程被杀而子进程成为孤儿，
    它们会一直占着端口，导致新后端无法绑定。返回这些 fd 供子进程关闭。
    """
    import glob

    # /proc/net/tcp(6) 中 state 0A = LISTEN；收集其 socket inode
    listen_inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f)
                for line in f:
                    parts = line.split()
                    if len(parts) > 3 and parts[3] == "0A":
                        listen_inodes.add(parts[9])
        except Exception:
            pass
    if not listen_inodes:
        return []
    # 映射本进程 fd -> socket inode
    fds = []
    for fdpath in glob.glob("/proc/self/fd/*"):
        try:
            target = os.readlink(fdpath)
        except OSError:
            continue
        if target.startswith("socket:["):
            inode = target[8:-1]
            if inode in listen_inodes:
                try:
                    fds.append(int(os.path.basename(fdpath)))
                except ValueError:
                    pass
    return fds


def _close_fds(fds) -> None:
    """fork 后第一时间关闭继承的监听 fd（此时尚未创建任何线程）。"""
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def _worker_thread(task_q, report_q, cancelled) -> None:
    """常驻工作线程：完成一个任务才领取下一个。

    关键：每个线程阻塞在自己的 q.get() 上，因此本进程最多在途
    nthreads 个任务，且只在线程空闲时才接新活——避免主循环盲抢
    导致任务在某进程堆积、其他进程空转（受 GIL 影响会拉长墙钟）。
    """
    while True:
        task = task_q.get()  # 阻塞；各线程各取一个
        if task is None:
            break
        _do_one(task, report_q, cancelled)


def _proc_main(nthreads: int, close_fds, task_q, report_q, cancelled) -> None:
    """转换进程主循环：启动 nthreads 个常驻工作线程并等待其退出。"""
    # 必须在创建线程/使用任何 IPC 之前关闭监听 fd
    _close_fds(close_fds)
    threads = []
    for _ in range(nthreads):
        t = threading.Thread(
            target=_worker_thread,
            args=(task_q, report_q, cancelled),
            daemon=True,
        )
        t.start()
        threads.append(t)
    # 等待所有工作线程结束（停止时每个线程收到一个哨兵）
    for t in threads:
        t.join()


# =====================================================================
# 主进程侧
# =====================================================================

class SuperEngine:
    """一组常驻转换进程（共享 Manager 队列）。"""

    def __init__(self, ctx, mgr, nproc: int, nthreads: int,
                 report_q=None, cancelled=None):
        self.ctx = ctx
        self.mgr = mgr
        self.nproc = nproc
        self.nthreads = nthreads
        # task_q 为本引擎私有：重建引擎时旧进程只从自己的队列取哨兵，
        # 不会与新进程互相争抢（共享队列会导致旧进程永远等不到哨兵）。
        # report_q / cancelled 跨引擎共享：旧进程排空期间结果仍可送达。
        self.task_q = mgr.Queue()
        self.report_q = report_q if report_q is not None else mgr.Queue()
        self.cancelled = cancelled if cancelled is not None else mgr.list()
        # fork 前快照本进程的监听 fd：子进程启动即关闭，
        # 保证父进程死后孤儿也不会占住端口
        self.listen_fds = _collect_listen_fds()
        self.procs = []
        for _ in range(nproc):
            p = ctx.Process(
                target=_proc_main,
                args=(nthreads, self.listen_fds,
                      self.task_q, self.report_q, self.cancelled),
                daemon=True,
            )
            p.start()
            self.procs.append(p)

    @property
    def total_slots(self) -> int:
        """总并发名额 = 进程数 × 每进程线程数。"""
        return self.nproc * self.nthreads

    def submit(self, fields: Dict[str, Any]) -> None:
        """下发一个转换任务。"""
        self.task_q.put(fields)

    def request_cancel(self, task_id: int) -> None:
        """标记任务取消（转换线程在 abort_cb 中感知）。"""
        try:
            if task_id not in self.cancelled:
                self.cancelled.append(task_id)
        except Exception:
            pass

    def clear_cancel(self, task_id: int) -> None:
        """任务结束后清除取消标记（否则同 id 的重试会被立即中止）。"""
        try:
            if task_id in self.cancelled:
                self.cancelled.remove(task_id)
        except Exception:
            pass

    def request_stop(self) -> None:
        """每个工作线程一个哨兵：排在已有任务之后，排空在途任务后退出。"""
        for _ in range(self.nproc * self.nthreads):
            self.task_q.put(None)

    def alive_count(self) -> int:
        return sum(p.is_alive() for p in self.procs)

    def join(self, timeout: Optional[float] = None) -> None:
        """等待进程退出（阻塞调用方，应在线程池中执行）。"""
        for p in self.procs:
            p.join(timeout)

    def terminate(self) -> None:
        """强制结束仍存活的进程。"""
        for p in self.procs:
            if p.is_alive():
                p.terminate()
