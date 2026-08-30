// 任务 store：维护进行中任务、历史与日志。
// WS 消息由 useBackend 分发到本 store；页面也可调用 submit/cancel/retry 与后端交互。
import { ref } from "vue";
import { defineStore } from "pinia";
import { apiGet, apiPost } from "../api/client";
import type {
  CreateTaskRequest,
  CreateTasksResponse,
  LogEntry,
  LogLevel,
  TaskInfo,
  TaskListResponse,
  WsServerMessage,
} from "../types/backend";

const MAX_LOGS = 500;

export const useTasksStore = defineStore("tasks", () => {
  const active = ref<TaskInfo[]>([]);
  const history = ref<TaskInfo[]>([]);
  const logs = ref<LogEntry[]>([]);

  /** 从后端拉取进行中与历史任务 */
  async function refresh(): Promise<void> {
    try {
      const data = await apiGet<TaskListResponse>("/api/tasks");
      active.value = data.active;
      history.value = data.history;
    } catch {
      /* 后端未连接 */
    }
  }

  /** 提交一批任务（页面拿到 batch_id 与任务列表自行跟踪） */
  async function submit(req: CreateTaskRequest): Promise<CreateTasksResponse> {
    const resp = await apiPost<CreateTasksResponse>("/api/tasks", req);
    return resp;
  }

  /** 取消单个任务 */
  async function cancel(taskId: number): Promise<void> {
    await apiPost(`/api/tasks/${taskId}/cancel`);
  }

  /** 重试单个任务 */
  async function retry(taskId: number): Promise<void> {
    await apiPost(`/api/tasks/${taskId}/retry`);
  }

  /** 追加日志（本地环形缓冲） */
  function pushLog(level: LogLevel, message: string): void {
    logs.value.push({ ts: new Date().toLocaleTimeString("zh-CN"), level, message });
    if (logs.value.length > MAX_LOGS) {
      logs.value = logs.value.slice(-MAX_LOGS);
    }
  }

  /** 根据 WS 消息更新本 store 状态（由 useBackend 分发） */
  function dispatchWs(msg: WsServerMessage): void {
    switch (msg.type) {
      case "task_start": {
        // 若已存在同 id 记录则仅刷新文件名，否则插入
        const exist = active.value.find((t) => t.task_id === msg.task_id);
        if (!exist) {
          active.value.unshift({
            task_id: msg.task_id,
            batch_id: "",
            module: msg.module,
            filename: msg.filename,
            input_path: "",
            output_path: "",
            output_format: "",
            status: "running",
            progress: 0,
            success: null,
            message: "",
            duration_ms: 0,
            created_at: Date.now() / 1000,
            finished_at: 0,
          });
        }
        break;
      }
      case "progress": {
        const t = active.value.find((x) => x.task_id === msg.task_id);
        if (t) t.progress = msg.percent;
        break;
      }
      case "task_result": {
        const idx = active.value.findIndex((t) => t.task_id === msg.task_id);
        if (idx >= 0) {
          const done: TaskInfo = { ...active.value[idx], status: msg.success ? "done" : "failed", success: msg.success, message: msg.message, duration_ms: msg.duration_ms, progress: 100, finished_at: Date.now() / 1000 };
          active.value.splice(idx, 1);
          history.value.unshift(done);
          if (history.value.length > 50) history.value = history.value.slice(0, 50);
        }
        break;
      }
      case "log":
        pushLog(msg.level, msg.message);
        break;
      default:
        break;
    }
  }

  return { active, history, logs, refresh, submit, cancel, retry, pushLog, dispatchWs };
});
