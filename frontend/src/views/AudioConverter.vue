<script setup lang="ts">
// 音频转换页：文件选择/拖入 + 转换设置 + 开始/停止 + 内联进度
// 功能对齐旧 PySide6 版音频模块，后端协议走第一轮 FastAPI。
import { computed, h, onMounted, onUnmounted, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NInput, NList, NListItem,
  NProgress, NSelect, NForm, NFormItem, NDropdown, NSpace, NSpin,
} from "naive-ui";
import type { DropdownOption, SelectOption } from "naive-ui";
import { open } from "@tauri-apps/plugin-dialog";
import { stat } from "@tauri-apps/plugin-fs";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { apiGet, apiPost } from "../api/client";
import { connected, onMessage } from "../composables/useBackend";
import { useTasksStore } from "../stores/tasks";
import { useSettingsStore } from "../stores/settings";
import type {
  ApiResult, CreateTaskRequest, FormatsResponse, ModuleName,
  TaskStatus, WsServerMessage,
} from "../types/backend";

const message = useMessage();
const tasks = useTasksStore();
const settings = useSettingsStore();

// ---------- 格式信息 ----------
const formats = ref<FormatsResponse | null>(null);
const loadingFormats = ref(false);

async function loadFormats(): Promise<void> {
  loadingFormats.value = true;
  try {
    formats.value = await apiGet<FormatsResponse>("/api/formats?module=audio");
  } catch {
    message.error("加载格式列表失败（后端未连接）");
  } finally {
    loadingFormats.value = false;
  }
}

// ---------- 文件列表 ----------
interface AudioFileItem {
  path: string;
  name: string;
  size: number;
}

const files = ref<AudioFileItem[]>([]);

function basename(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

/** 加入文件：过滤音频扩展名 + 去重 + 读取大小 */
async function addFiles(paths: string[]): Promise<void> {
  const inputs = formats.value?.inputs ?? [];
  for (const p of paths) {
    const ext = (p.split(".").pop() ?? "").toLowerCase();
    if (!inputs.includes(ext)) continue;
    if (files.value.some((f) => f.path === p)) continue;
    let size = 0;
    try {
      const info = await stat(p);
      size = info.size ?? 0;
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
      directory: false,
      filters: [{ name: "音频文件", extensions: exts }],
    });
    if (Array.isArray(selected)) await addFiles(selected);
    else if (typeof selected === "string") await addFiles([selected]);
  } catch {
    message.error("无法打开文件对话框（请通过 Tauri 运行）");
  }
}

/** 浏览器拖放兜底（仅当 File 带 path 时可用） */
function onDomDrop(e: DragEvent): void {
  e.preventDefault();
  const list = e.dataTransfer?.files;
  if (!list) return;
  const paths: string[] = [];
  for (const f of Array.from(list)) {
    const p = (f as unknown as { path?: string }).path;
    if (p) paths.push(p);
  }
  if (paths.length) void addFiles(paths);
}

function removeFile(path: string): void {
  files.value = files.value.filter((f) => f.path !== path);
}

function clearFiles(): void {
  files.value = [];
}

function formatSize(n: number): string {
  if (!n) return "未知大小";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// 右键菜单
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

// ---------- 转换设置 ----------
const outputFormat = ref("mp3");
const outputDir = ref("");
const bitrate = ref<string | number>("__auto__");
const sampleRate = ref<string | number>("__keep__");
const channels = ref<string | number>("__keep__");
const normalize = ref(true); // 对齐 AudioConversionTask.normalize 默认 True

// 输出格式下拉：不支持的格式置灰禁用，label 加"（不支持）"后缀，
// hover 时用原生 title 展示 unsupported_reason 完整文案
const formatOptions = computed<SelectOption[]>(() =>
  (formats.value?.outputs ?? []).map((o) => {
    const opt: SelectOption = { value: o.key, disabled: o.supported === false };
    if (o.supported === false) {
      opt.label = `${o.desc}（不支持）`;
      opt.render = () =>
        h("span", { title: o.unsupported_reason ?? "该格式不受支持" }, `${o.desc}（不支持）`);
    } else {
      opt.label = o.desc;
    }
    return opt;
  }),
);

// 回退：若当前选中格式不存在或不支持（如旧配置存了 dts），自动切到第一个可用格式
watch(formats, () => {
  const list = formats.value?.outputs ?? [];
  const cur = list.find((o) => o.key === outputFormat.value);
  if (!cur || cur.supported === false) {
    const first = list.find((o) => o.supported !== false);
    if (first) outputFormat.value = first.key;
  }
});
const bitrateOptions = computed<SelectOption[]>(() =>
  (formats.value?.presets.bitrate ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__auto__" : (p.value as string | number),
  })),
);
const sampleRateOptions = computed<SelectOption[]>(() =>
  (formats.value?.presets.sample_rate ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__keep__" : (p.value as string | number),
  })),
);
const channelOptions = computed<SelectOption[]>(() =>
  (formats.value?.presets.channels ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__keep__" : (p.value as string | number),
  })),
);

/** 选择框的哨兵值还原为后端 null */
function restoreNull(v: string | number): unknown {
  return v === "__auto__" || v === "__keep__" ? null : v;
}

/** 浏览输出目录（Tauri 目录对话框） */
async function browseOutputDir(): Promise<void> {
  try {
    const dir = await open({ directory: true, multiple: false });
    if (typeof dir === "string") outputDir.value = dir;
  } catch {
    message.error("无法打开目录对话框（请通过 Tauri 运行）");
  }
}

// ---------- 转换执行 ----------
const converting = ref(false);
const batchId = ref("");
interface BatchTask {
  task_id: number;
  filename: string;
  progress: number;
  status: TaskStatus;
}
const batchTasks = ref<BatchTask[]>([]);

async function startConversion(): Promise<void> {
  if (!files.value.length) {
    message.warning("请先添加要转换的音频文件");
    return;
  }
  if (!connected.value) {
    message.error("后端未连接，无法开始转换");
    return;
  }
  const req: CreateTaskRequest = {
    module: "audio" as ModuleName,
    files: files.value.map((f) => ({ path: f.path })),
    output_dir: outputDir.value.trim(),
    output_format: outputFormat.value,
    params: {
      bitrate: restoreNull(bitrate.value),
      sample_rate: restoreNull(sampleRate.value),
      channels: restoreNull(channels.value),
      normalize: normalize.value,
    },
    overwrite: false,
  };
  converting.value = true;
  try {
    const resp = await tasks.submit(req);
    batchId.value = resp.batch_id ?? "";
    batchTasks.value = resp.tasks.map((t) => ({
      task_id: t.task_id,
      filename: t.filename,
      progress: 0,
      status: t.status,
    }));
  } catch {
    message.error("提交任务失败（后端未连接）");
    converting.value = false;
  }
}

/** 停止：对本批次所有任务逐个取消 */
async function stopConversion(): Promise<void> {
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

/** 打开输出目录 */
async function openOutputDir(): Promise<void> {
  const dir = outputDir.value.trim();
  if (!dir) {
    message.info("未指定输出目录，请在转换设置中填写");
    return;
  }
  try {
    const r = await apiPost<ApiResult>("/api/open_path", { path: dir });
    if (!r.ok) message.error(r.message);
  } catch {
    message.error("打开失败（后端未连接）");
  }
}

// ---------- 进度聚合 ----------
const totalProgress = computed(() => {
  if (!batchTasks.value.length) return 0;
  const sum = batchTasks.value.reduce((s, t) => s + t.progress, 0);
  return Math.round(sum / batchTasks.value.length);
});
const doneCount = computed(
  () => batchTasks.value.filter((t) => t.status === "done" || t.status === "failed").length,
);

/** WS 消息：更新本批次任务的进度/状态 */
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

// ---------- 生命周期 ----------
let unlistenWs: (() => void) | undefined;
let unlistenDrag: (() => void) | undefined;

onMounted(async () => {
  void loadFormats();
  if (settings.defaultOutputDir) outputDir.value = settings.defaultOutputDir;
  unlistenWs = onMessage(onWs);
  // Tauri 拖放（提供完整文件路径）
  try {
    unlistenDrag = await getCurrentWebview().onDragDropEvent((event) => {
      if (event.payload.type === "drop") {
        void addFiles(event.payload.paths);
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
</script>

<template>
  <n-spin :show="loadingFormats">
    <n-alert type="success" :show-icon="false" class="local-hint">
      🔒 文件不出本机，全程本地转换（PyAV 进程内引擎）。
    </n-alert>

    <n-card title="🎵 音频格式转换" class="page-card">
      <div class="layout">
        <!-- 左：文件列表 -->
        <n-card title="待转换文件" size="small" class="panel">
          <div
            class="drop-zone"
            @dragover.prevent
            @drop.prevent="onDomDrop"
            @click="addFilesDialog"
          >
            <n-empty v-if="!files.length" description="拖入音频文件，或点击此处添加" />
            <n-list v-else bordered>
              <n-list-item
                v-for="f in files"
                :key="f.path"
                class="file-item"
                @contextmenu.prevent="onContextMenu($event, f.path)"
              >
                <div class="file-row">
                  <span class="file-name">🎵 {{ f.name }}</span>
                  <span class="file-size">{{ formatSize(f.size) }}</span>
                  <n-button size="tiny" text type="error" @click="removeFile(f.path)">移除</n-button>
                </div>
              </n-list-item>
            </n-list>
          </div>
          <div class="file-actions">
            <n-button size="small" @click="addFilesDialog">➕ 添加文件</n-button>
            <n-button size="small" @click="clearFiles">🗑 清空全部</n-button>
          </div>
        </n-card>

        <!-- 右：转换设置 -->
        <n-card title="转换设置" size="small" class="panel">
          <n-form label-placement="left" label-width="86" size="medium">
            <n-form-item label="输出格式">
              <n-select v-model:value="outputFormat" :options="formatOptions" />
            </n-form-item>
            <n-form-item label="输出目录">
              <n-input-group>
                <n-input v-model:value="outputDir" placeholder="留空 = 与源文件同目录" />
                <n-button type="primary" ghost @click="browseOutputDir">浏览</n-button>
              </n-input-group>
            </n-form-item>
            <n-form-item label="比特率">
              <n-select v-model:value="bitrate" :options="bitrateOptions" />
            </n-form-item>
            <n-form-item label="采样率">
              <n-select v-model:value="sampleRate" :options="sampleRateOptions" />
            </n-form-item>
            <n-form-item label="声道">
              <n-select v-model:value="channels" :options="channelOptions" />
            </n-form-item>
            <n-form-item label="归一化">
              <n-checkbox v-model:checked="normalize">音量归一化 (Normalize)</n-checkbox>
            </n-form-item>
          </n-form>
        </n-card>
      </div>

      <!-- 底部操作 + 进度 -->
      <n-space class="action-bar" justify="space-between" align="center">
        <n-space>
          <n-button type="primary" :loading="converting" @click="startConversion">
            ▶ 开始转换
          </n-button>
          <n-button :disabled="!batchTasks.length" @click="stopConversion">⏹ 停止</n-button>
          <n-button @click="openOutputDir">📂 打开输出目录</n-button>
        </n-space>
        <n-space v-if="batchTasks.length" vertical size="small" class="progress-block">
          <span class="progress-text">
            {{ doneCount }}/{{ batchTasks.length }} 完成 · 总进度 {{ totalProgress }}%
          </span>
          <n-progress type="line" :percentage="totalProgress" :height="10" processing />
        </n-space>
      </n-space>
    </n-card>

    <!-- 右键菜单 -->
    <n-dropdown
      :show="menuShow"
      :x="menuX"
      :y="menuY"
      :options="menuOptions"
      @select="onMenuSelect"
      @clickoutside="menuShow = false"
    />
  </n-spin>
</template>

<style scoped>
.local-hint {
  margin-bottom: 12px;
}
.layout {
  display: flex;
  gap: 16px;
  align-items: stretch;
}
.panel {
  flex: 1;
  min-width: 0;
}
.drop-zone {
  min-height: 220px;
  border: 1px dashed var(--n-border-color, #0f3460);
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
}
.file-item {
  cursor: default;
}
.file-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-size {
  color: var(--n-text-color-3, #a0a0a0);
  font-size: 12px;
}
.file-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.action-bar {
  margin-top: 16px;
}
.progress-block {
  min-width: 240px;
}
.progress-text {
  font-size: 12px;
  opacity: 0.85;
}
</style>
