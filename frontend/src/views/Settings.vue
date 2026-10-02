<script setup lang="ts">
// 全局设置页：默认输出目录 + 主题 + PyAV 引擎状态 + 各模块并行数 + 超时
import { computed, onMounted, ref } from "vue";
import { useDialog, useMessage } from "naive-ui";
import {
  NAlert, NButton, NCard, NInput, NInputGroup, NInputNumber, NSelect,
  NSpace, NSpin, NDivider, NSwitch,
} from "naive-ui";
import { open } from "@tauri-apps/plugin-dialog";
import { useSettingsStore } from "../stores/settings";
import { useEngineStore } from "../stores/engine";
import AppIcon from "../components/AppIcon.vue";
import type { ModuleName, ParallelMap, ThemeMode } from "../types/backend";

const message = useMessage();
const dialog = useDialog();
const settings = useSettingsStore();
const engine = useEngineStore();

// 本地表单状态（与 settings store 同步）
const theme = ref<ThemeMode>("dark");
const defaultOutputDir = ref("");
const maxParallel = ref<ParallelMap>({ audio: 2, video: 2, image: 2, doc: 2 });
const taskTimeoutMinutes = ref(0);
const superMode = ref(false);
const superProcesses = ref(4);
const superThreads = ref(4);
const saving = ref(false);

const parallelOptions = Array.from({ length: 8 }, (_, i) => ({ label: `${i + 1}`, value: i + 1 }));

// 超级模式进程数：2-8
const superProcessOptions = Array.from({ length: 7 }, (_, i) => ({
  label: `${i + 2}`,
  value: i + 2,
}));
// 每进程同时转换文件数：1-8
const superThreadOptions = Array.from({ length: 8 }, (_, i) => ({
  label: `${i + 1}`,
  value: i + 1,
}));

// 本机逻辑核心数（用于资源风险提示）
const cpuCores = navigator.hardwareConcurrency || 4;
/** 总并发名额 = 转换进程数 × 每进程同时转换文件数 */
const totalConcurrency = computed(() => superProcesses.value * superThreads.value);
/** 总并发达到/超过逻辑核心数时给出高危提示 */
const overCoreRisk = computed(() => totalConcurrency.value >= cpuCores);

/** 切换超级模式：开启前弹确认框，明确资源占用风险 */
function toggleSuper(value: boolean): void {
  if (value) {
    dialog.warning({
      title: "开启超级模式（多进程批量转换）？",
      content:
        "超级模式会启动多个独立的 PyAV 转换进程，每个进程同时转换多个文件，适合大批量转换。开启过多进程/并发会占用大量 CPU 和内存，可能导致系统卡顿、风扇高速运转甚至应用无响应；在机械硬盘上并发过高反而更慢。请根据 CPU 核心数、内存和磁盘类型谨慎设置。",
      positiveText: "我已了解，开启",
      negativeText: "取消",
      onPositiveClick: () => {
        superMode.value = true;
      },
    });
  } else {
    superMode.value = false;
  }
}

// 四个模块各自独立的并行数设置
const parallelModules: { key: ModuleName; label: string; icon: string }[] = [
  { key: "audio", label: "音频", icon: "audio" },
  { key: "video", label: "视频", icon: "video" },
  { key: "image", label: "图片", icon: "image" },
  { key: "doc", label: "文档", icon: "doc" },
];

function loadIntoForm(): void {
  theme.value = settings.theme;
  defaultOutputDir.value = settings.defaultOutputDir;
  maxParallel.value = { ...settings.maxParallel };
  taskTimeoutMinutes.value = settings.taskTimeoutMinutes;
  superMode.value = settings.superMode;
  superProcesses.value = settings.superProcesses;
  superThreads.value = settings.superThreads;
}

async function browseDir(): Promise<void> {
  try {
    const dir = await open({ directory: true, multiple: false });
    if (typeof dir === "string") defaultOutputDir.value = dir;
  } catch {
    message.error("无法打开目录对话框（请通过 Tauri 运行）");
  }
}

function resetDir(): void {
  defaultOutputDir.value = "";
}

async function selectTheme(mode: ThemeMode): Promise<void> {
  theme.value = mode;
  await settings.setTheme(mode); // 即时生效并持久化
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    await settings.apply({
      theme: theme.value,
      default_output_dir: defaultOutputDir.value,
      max_parallel: maxParallel.value,
      task_timeout_minutes: taskTimeoutMinutes.value,
      super_mode: superMode.value,
      super_processes: superProcesses.value,
      super_threads: superThreads.value,
    });
    await settings.save(); // 后端并行数与超级模式热生效
    message.success(
      superMode.value
        ? `设置已保存，超级模式已开启（${superProcesses.value} 进程 × ${superThreads.value} 并发 = ${totalConcurrency.value} 路）`
        : "设置已保存，四个模块并行数已即时生效",
    );
  } catch {
    message.error("保存失败（后端未连接）");
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await settings.load();
  loadIntoForm();
  void engine.refresh();
});
</script>

<template>
  <n-spin :show="saving">
    <n-card class="page-card">
      <template #header>
        <span class="card-title"><AppIcon name="settings" :size="18" /> 全局设置</span>
      </template>
      <!-- 默认输出目录 -->
      <n-card title="默认输出文件夹" size="small" class="section">
        <n-input-group>
          <n-input v-model:value="defaultOutputDir" placeholder="留空 = 与源文件同目录" />
          <n-button type="primary" ghost @click="browseDir">浏览…</n-button>
          <n-button @click="resetDir">重置（同目录）</n-button>
        </n-input-group>
      </n-card>

      <!-- 主题 -->
      <n-card title="界面外观" size="small" class="section">
        <n-space>
          <n-button
            class="theme-card"
            :class="{ active: theme === 'dark' }"
            @click="selectTheme('dark')"
          >
            <AppIcon name="moon" :size="16" /> 暗色主题
          </n-button>
          <n-button
            class="theme-card"
            :class="{ active: theme === 'light' }"
            @click="selectTheme('light')"
          >
            <AppIcon name="sun" :size="16" /> 亮色主题
          </n-button>
        </n-space>
      </n-card>

      <!-- PyAV 引擎状态 -->
      <n-card title="PyAV 引擎" size="small" class="section">
        <div v-if="engine.status" class="engine-info">
          <div class="engine-row">
            <span class="engine-label">状态</span>
            <span class="av-state" :class="{ ok: engine.status.av.available, bad: !engine.status.av.available }">
              <AppIcon :name="engine.status.av.available ? 'check-circle' : 'x-circle'" :size="16" />
              {{ engine.status.av.available ? "已就绪" : "不可用" }}
            </span>
          </div>
          <div class="engine-row">
            <span class="engine-label">版本</span>
            <span>PyAV {{ engine.status.av.version }}（内置 FFmpeg）</span>
          </div>
          <div class="engine-row">
            <span class="engine-label">能力</span>
            <span>{{ engine.status.av.muxers ?? 0 }} 个封装器 / {{ engine.status.av.encoders ?? 0 }} 个编码器</span>
          </div>
          <div class="engine-row">
            <span class="engine-label">硬件加速</span>
            <span>
              {{
                Object.keys(engine.status.av.gpu ?? {}).length
                  ? Object.values(engine.status.av.gpu).join("、")
                  : "未检测到可用 GPU"
              }}
            </span>
          </div>
          <div class="engine-row">
            <span class="engine-label">磁盘剩余</span>
            <span>{{ engine.diskFreeGb }} GB</span>
          </div>
        </div>
        <n-alert v-else type="warning" :show-icon="false">引擎状态加载中（后端未连接）…</n-alert>
      </n-card>

      <n-divider />

      <!-- 转换设置 -->
      <n-card title="转换设置" size="small" class="section">
        <!-- 超级模式（多进程转换） -->
        <div class="super-row">
          <span class="spin-label super-label"><AppIcon name="bolt" :size="16" /> 超级模式（多进程转换）</span>
          <n-switch :value="superMode" @update:value="toggleSuper" />
          <span class="spin-hint">关闭 = 多线程；开启 = 多进程</span>
        </div>
        <n-alert v-if="superMode" type="warning" class="super-alert">
          <div class="super-proc-row">
            <span class="super-field-label">转换进程数</span>
            <n-select
              :value="superProcesses"
              :options="superProcessOptions"
              style="width: 110px"
              @update:value="(v: number) => (superProcesses = v)"
            />
            <span class="super-field-label">每进程同时转换文件数</span>
            <n-select
              :value="superThreads"
              :options="superThreadOptions"
              style="width: 110px"
              @update:value="(v: number) => (superThreads = v)"
            />
          </div>
          <div class="super-total-row">
            总并发 = <b>{{ superProcesses }} × {{ superThreads }} = {{ totalConcurrency }} 路</b>
            <span v-if="overCoreRisk" class="risk-high">
              <AppIcon name="alert" :size="14" /> 已达到/超过本机逻辑核心数（{{ cpuCores }} 核），资源占用风险很高
            </span>
          </div>
          <div>
            开启过多进程会同时拉高 CPU 与内存占用，可能造成系统卡顿甚至无响应；
            机械硬盘上建议总并发适当调低。本机 {{ cpuCores }} 个逻辑核心，
            建议总并发不超过核心数。
          </div>
        </n-alert>

        <div class="spin-row">
          <span class="spin-label">每模块最大并行数（各自独立）</span>
        </div>
        <div class="parallel-grid">
          <div v-for="m in parallelModules" :key="m.key" class="parallel-item">
            <span class="parallel-label">
              <AppIcon :name="m.icon" :size="15" /> {{ m.label }}
            </span>
            <n-select
              :value="maxParallel[m.key]"
              :options="parallelOptions"
              style="width: 120px"
              placeholder="1-8"
              @update:value="(v: number) => (maxParallel[m.key] = v)"
            />
          </div>
        </div>
        <div class="spin-row">
          <span class="spin-label">单文件超时(分钟)</span>
          <n-input-number
            v-model:value="taskTimeoutMinutes"
            :min="0"
            :max="120"
            style="width: 160px"
            :placeholder="taskTimeoutMinutes === 0 ? '不限' : ''"
          />
          <span class="spin-hint">{{ taskTimeoutMinutes === 0 ? "0 = 不限时" : `${taskTimeoutMinutes} 分钟` }}</span>
        </div>
        <n-space class="save-bar">
          <n-button type="primary" :loading="saving" @click="save">
            <template #icon><AppIcon name="save" :size="16" /></template>
            保存设置
          </n-button>
        </n-space>
      </n-card>
    </n-card>
  </n-spin>
</template>

<style scoped>
.card-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.av-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.av-state.ok { color: #34d399; }
.av-state.bad { color: #f87171; }
.super-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.section {
  margin-bottom: 16px;
}
.theme-card {
  min-width: 200px;
  min-height: 72px;
  font-size: 15px;
  border: 2px solid transparent;
}
.theme-card.active {
  border-color: var(--n-primary-color, #e94560);
}
.engine-info {
  font-size: 13px;
}
.engine-row {
  display: flex;
  gap: 12px;
  padding: 4px 0;
}
.engine-label {
  width: 90px;
  color: var(--n-text-color-3, #a0a0a0);
  flex-shrink: 0;
}
.spin-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.parallel-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px 24px;
  margin-bottom: 16px;
  max-width: 520px;
}
.parallel-item {
  display: flex;
  align-items: center;
  gap: 12px;
}
.parallel-label {
  width: 96px;
  flex-shrink: 0;
}
.spin-label {
  width: 160px;
}
.spin-hint {
  font-size: 12px;
  opacity: 0.7;
}
.save-bar {
  margin-top: 8px;
}
.super-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.super-alert {
  margin-bottom: 16px;
}
.super-proc-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.super-field-label {
  font-size: 13px;
}
.super-total-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}
.risk-high {
  color: #e94560;
  font-size: 12px;
}
</style>
