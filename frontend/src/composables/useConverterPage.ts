// 转换页共享逻辑：文件列表（含递归目录展开）+ 格式加载 + 批量提交/取消 + 进度聚合。
// 供 Video / Image / Doc 三个转换页复用；AudioConverter 维持其独立实现。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useMessage } from "naive-ui";
import type { DropdownOption } from "naive-ui";
import { open } from "@tauri-apps/plugin-dialog";
import { stat, readDir } from "@tauri-apps/plugin-fs";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { apiGet, apiPost } from "../api/client";
import { connected, onMessage } from "./useBackend";
import { useTasksStore } from "../stores/tasks";
import type {
  ApiResult, FormatsResponse, ModuleName, TaskStatus, WsServerMessage,
} from "../types/backend";

export interface FileItem {
  path: string;
  name: string;
  size: number;
}

export interface BatchTask {
  task_id: number;
  filename: string;
  progress: number;
  status: TaskStatus;
}

const PATH_SEP = "/";

function joinPath(dir: string, name: string): string {
  return dir.endsWith("/") || dir.endsWith("\\") ? dir + name : dir + PATH_SEP + name;
}

function basename(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

function formatSize(n: number): string {
  if (!n) return "未知大小";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** 递归展开目录为文件（按扩展名过滤） */
async function walkDir(dir: string, exts: string[], out: string[]): Promise<void> {
  let entries;
  try {
    entries = await readDir(dir);
  } catch {
    return;
  }
  for (const e of entries) {
    const full = joinPath(dir, e.name);
    if (e.isDirectory) {
      await walkDir(full, exts, out);
    } else if (e.isFile) {
      const ext = (e.name.split(".").pop() ?? "").toLowerCase();
      if (exts.includes(ext)) out.push(full);
    }
  }
}

/** 收集拖入/选择的路径：目录按 recursive 展开，文件按扩展名过滤 */
async function collectPaths(paths: string[], recursive: boolean, exts: string[]): Promise<string[]> {
  const out: string[] = [];
  for (const p of paths) {
    try {
      const info = await stat(p);
      if (info.isDirectory) {
        if (recursive) await walkDir(p, exts, out);
      } else if (info.isFile) {
        const ext = (p.split(".").pop() ?? "").toLowerCase();
        if (exts.includes(ext)) out.push(p);
      }
    } catch {
      /* 跳过无法访问的路径 */
    }
  }
  return out;
}

/**
 * 转换页共享状态。
 * @param module      模块名（audio/video/image/doc）
 * @param recursive   拖入目录时是否递归展开
 */
export function useConverterPage(module: ModuleName, recursive = false) {
  const message = useMessage();
  const tasks = useTasksStore();

  // ---------- 格式信息 ----------
  const formats = ref<FormatsResponse | null>(null);
  const loadingFormats = ref(false);

  async function loadFormats(): Promise<void> {
    loadingFormats.value = true;
    try {
      formats.value = await apiGet<FormatsResponse>(`/api/formats?module=${module}`);
    } catch {
      message.error("加载格式列表失败（后端未连接）");
    } finally {
      loadingFormats.value = false;
    }
  }

  // ---------- 文件列表 ----------
  const files = ref<FileItem[]>([]);
  /** 拖拽悬停高亮 */
  const dragHover = ref(false);

  async function addFiles(paths: string[]): Promise<void> {
    const exts = formats.value?.inputs ?? [];
    const collected = await collectPaths(paths, recursive, exts);
    for (const p of collected) {
      if (files.value.some((f) => f.path === p)) continue;
      let size = 0;
      try {
        size = (await stat(p)).size ?? 0;
      } catch {
        size = 0;
      }
      files.value.push({ path: p, name: basename(p), size });
    }
  }

  /** 点击添加：Tauri 文件对话框 */
  async function addFilesDialog(): Promise<void> {
    try {
      const exts = formats.value?.inputs ?? [];
      const selected = await open({
        multiple: true,
        directory: recursive,
        filters: [{ name: "文件", extensions: exts }],
      });
      if (Array.isArray(selected)) await addFiles(selected);
      else if (typeof selected === "string") await addFiles([selected]);
    } catch {
      message.error("无法打开文件对话框（请通过 Tauri 运行）");
    }
  }

  /** 选择输出目录 */
  async function pickDirectory(): Promise<string> {
    try {
      const dir = await open({ directory: true, multiple: false });
      return typeof dir === "string" ? dir : "";
    } catch {
      message.error("无法打开目录对话框（请通过 Tauri 运行）");
      return "";
    }
  }

  /** 浏览器拖放兜底（仅当 File 带 path 时可用） */
  function onDomDrop(e: DragEvent): void {
    e.preventDefault();
    dragHover.value = false;
    const list = e.dataTransfer?.files;
    if (!list) return;
    const paths: string[] = [];
    for (const f of Array.from(list)) {
      const p = (f as unknown as { path?: string }).path;
      if (p) paths.push(p);
    }
    if (paths.length) void addFiles(paths);
  }

  function onDomDragOver(e: DragEvent): void {
    e.preventDefault();
    dragHover.value = true;
  }

  function onDomDragLeave(e: DragEvent): void {
    e.preventDefault();
    dragHover.value = false;
  }

  function removeFile(path: string): void {
    files.value = files.value.filter((f) => f.path !== path);
  }

  function clearFiles(): void {
    files.value = [];
  }

  // ---------- 右键菜单 ----------
  const menuShow = ref(false);
  const menuX = ref(0);
  const menuY = ref(0);
  const menuFile = ref("");
  const menuOptions: DropdownOption[] = [{ label: "移除", key: "remove" }];

  function onContextMenu(e: MouseEvent, path: string): void {
    e.preventDefault();
    menuFile.value = path;
    menuX.value = e.clientX;
    menuY.value = e.clientY;
    menuShow.value = true;
  }

  function onMenuSelect(key: string | number): void {
    if (key === "remove" && menuFile.value) removeFile(menuFile.value);
    menuShow.value = false;
  }

  // ---------- 批量转换 ----------
  const converting = ref(false);
  const batchId = ref("");
  const batchTasks = ref<BatchTask[]>([]);

  interface StartPayload {
    output_format: string;
    output_dir: string;
    params: Record<string, unknown>;
    overwrite?: boolean;
  }

  async function start(payload: StartPayload): Promise<boolean> {
    if (!files.value.length) {
      message.warning("请先添加要转换的文件");
      return false;
    }
    if (!connected.value) {
      message.error("后端未连接，无法开始转换");
      return false;
    }
    converting.value = true;
    try {
      const resp = await tasks.submit({
        module,
        files: files.value.map((f) => ({ path: f.path })),
        output_dir: payload.output_dir,
        output_format: payload.output_format,
        params: payload.params,
        overwrite: payload.overwrite ?? false,
      });
      batchId.value = resp.batch_id ?? "";
      batchTasks.value = resp.tasks.map((t) => ({
        task_id: t.task_id,
        filename: t.filename,
        progress: 0,
        status: t.status,
      }));
      message.success(`已提交 ${resp.tasks.length} 个任务`);
      return true;
    } catch {
      message.error("提交任务失败（后端未连接）");
      converting.value = false;
      return false;
    }
  }

  /** 停止：对本批次所有任务逐个取消 */
  async function stop(): Promise<void> {
    for (const t of batchTasks.value) {
      if (t.status === "pending" || t.status === "running" || t.status === "paused") {
        try {
          await tasks.cancel(t.task_id);
        } catch {
          /* 忽略单个取消失败 */
        }
      }
    }
  }

  /** 打开目录 */
  async function openOutputDir(dir: string): Promise<void> {
    if (!dir) {
      message.info("未指定输出目录");
      return;
    }
    try {
      const r = await apiPost<ApiResult>("/api/open_path", { path: dir });
      if (!r.ok) message.error(r.message);
    } catch {
      message.error("打开失败（后端未连接）");
    }
  }

  const totalProgress = computed(() => {
    if (!batchTasks.value.length) return 0;
    const sum = batchTasks.value.reduce((s, t) => s + t.progress, 0);
    return Math.round(sum / batchTasks.value.length);
  });

  const doneCount = computed(
    () => batchTasks.value.filter((t) => t.status === "done" || t.status === "failed").length,
  );

  /** WS 消息：更新本批次任务进度/状态，全部结束后复位 converting */
  function onWs(msg: WsServerMessage): void {
    if (!batchTasks.value.length) return;
    if (msg.type !== "progress" && msg.type !== "task_result" && msg.type !== "task_start") return;
    const idx = batchTasks.value.findIndex((t) => t.task_id === msg.task_id);
    if (idx < 0) return;
    if (msg.type === "progress") {
      batchTasks.value[idx].progress = msg.percent;
    } else if (msg.type === "task_result") {
      batchTasks.value[idx].progress = 100;
      batchTasks.value[idx].status = msg.success ? "done" : "failed";
      if (batchTasks.value.every((t) => t.status === "done" || t.status === "failed" || t.status === "cancelled")) {
        converting.value = false;
      }
    }
  }

  // ---------- 生命周期（拖放注册） ----------
  let unlistenWs: (() => void) | undefined;
  let unlistenDrag: (() => void) | undefined;

  onMounted(async () => {
    void loadFormats();
    unlistenWs = onMessage(onWs);
    try {
      unlistenDrag = await getCurrentWebview().onDragDropEvent((event) => {
        const p = event.payload;
        if (p.type === "enter" || p.type === "over") {
          dragHover.value = true;
        } else if (p.type === "leave") {
          dragHover.value = false;
        } else if (p.type === "drop") {
          dragHover.value = false;
          void addFiles(p.paths);
        }
      });
    } catch {
      /* 非 Tauri 环境：走 HTML5 兜底 */
    }
  });

  onUnmounted(() => {
    unlistenWs?.();
    unlistenDrag?.();
  });

  return {
    // 格式
    formats, loadingFormats, loadFormats,
    // 文件
    files, dragHover, addFiles, addFilesDialog, pickDirectory,
    onDomDrop, onDomDragOver, onDomDragLeave, removeFile, clearFiles, formatSize,
    // 右键菜单
    menuShow, menuX, menuY, menuOptions, onContextMenu, onMenuSelect,
    // 转换
    converting, batchId, batchTasks, start, stop, openOutputDir, totalProgress, doneCount,
  };
}
