// 后端协议类型定义（与 backend/models.py / ws.py 一一对应）

/** 模块名（固定取值） */
export type ModuleName = "audio" | "video" | "image" | "doc";

/** 任务状态机 */
export type TaskStatus = "pending" | "running" | "paused" | "done" | "failed" | "cancelled";

/** 日志级别 */
export type LogLevel = "info" | "success" | "warning" | "error";

/** 主题 */
export type ThemeMode = "dark" | "light";

/** 各模块独立并行数（1-8） */
export type ParallelMap = Record<ModuleName, number>;

// ---------- 引擎状态 ----------

export interface DocProbe {
  native_flags: Record<string, boolean>;
  native_errors: Record<string, string | null>;
  pandoc: string | null;
  wkhtmltopdf: string | null;
}

export interface EngineStatus {
  av: {
    available: boolean;
    version: string;
    gpu: Record<string, string>;
    muxers?: number;
    encoders?: number;
  };
  pillow: boolean;
  doc: DocProbe;
}

export interface HealthResponse {
  ok: boolean;
  port: number;
  version: string;
  engines: EngineStatus;
  disk_free_gb: number;
  parallel: ParallelMap;
}

// ---------- 格式信息 ----------

export interface FormatPresetItem {
  label: string;
  value: unknown; // string | number | null，视预设而定
}

export interface OutputFormatInfo {
  key: string;
  desc: string;
  ext: string;
  need_quality?: boolean;
  extract_audio?: boolean;
  /** 是否可输出：false 表示 PyAV 缺编码器/封装器，UI 应置灰禁用 */
  supported?: boolean;
  /** 不受支持时的完整原因文案（悬停提示） */
  unsupported_reason?: string;
}

export interface FormatsResponse {
  inputs: string[];
  outputs: OutputFormatInfo[];
  /** 视频模块「提取音频」的输出格式（带 supported 标记，由后端预检返回） */
  extract_audio_outputs?: OutputFormatInfo[];
  presets: Record<string, FormatPresetItem[]>;
}

// ---------- 任务 ----------

export interface FileRef {
  path: string;
}

export interface CreateTaskRequest {
  module: ModuleName;
  files: FileRef[];
  output_dir: string;
  output_format: string;
  params: Record<string, unknown>;
  overwrite: boolean;
}

export interface TaskInfo {
  task_id: number;
  batch_id: string;
  module: ModuleName;
  filename: string;
  input_path: string;
  output_path: string;
  output_format: string;
  status: TaskStatus;
  progress: number;
  success: boolean | null;
  message: string;
  duration_ms: number;
  created_at: number;
  finished_at: number;
}

export interface CreateTasksResponse {
  batch_id: string | null;
  tasks: TaskInfo[];
}

export interface TaskListResponse {
  active: TaskInfo[];
  history: TaskInfo[];
}

export interface ApiResult {
  ok: boolean;
  message: string;
}

// ---------- 设置 ----------

export interface Settings {
  theme: ThemeMode;
  default_output_dir: string;
  max_parallel: ParallelMap;
  task_timeout_minutes: number;
}

// ---------- 日志 ----------

export interface LogEntry {
  ts: string;
  level: LogLevel;
  message: string;
}

// ---------- WebSocket 消息 ----------

export interface WsTaskStart {
  type: "task_start";
  module: ModuleName;
  task_id: number;
  filename: string;
}

export interface WsProgress {
  type: "progress";
  module: ModuleName;
  task_id: number;
  percent: number;
}

export interface WsTaskResult {
  type: "task_result";
  module: ModuleName;
  task_id: number;
  success: boolean;
  message: string;
  duration_ms: number;
}

export interface WsLog {
  type: "log";
  level: LogLevel;
  message: string;
}

export interface WsEngineStatus {
  type: "engine_status";
  engine: EngineStatus;
}

export interface WsPong {
  type: "pong";
  ts: number;
}

/** 服务端 -> 客户端 的所有消息类型（判别联合） */
export type WsServerMessage =
  | WsTaskStart
  | WsProgress
  | WsTaskResult
  | WsLog
  | WsEngineStatus
  | WsPong;

/** 客户端 -> 服务端 消息 */
export type WsClientMessage = { type: "ping" } | { type: "engine_status" };
