<script setup lang="ts">
// 全局设置页：默认输出目录 + 主题 + PyAV 引擎状态 + 各模块并行数 + 超时
import { onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import {
  NAlert, NButton, NCard, NInput, NInputGroup, NInputNumber, NSelect,
  NSpace, NSpin, NDivider,
} from "naive-ui";
import { open } from "@tauri-apps/plugin-dialog";
import { useSettingsStore } from "../stores/settings";
import { useEngineStore } from "../stores/engine";
import type { ModuleName, ParallelMap, ThemeMode } from "../types/backend";

const message = useMessage();
const settings = useSettingsStore();
const engine = useEngineStore();

// 本地表单状态（与 settings store 同步）
const theme = ref<ThemeMode>("dark");
const defaultOutputDir = ref("");
const maxParallel = ref<ParallelMap>({ audio: 2, video: 2, image: 2, doc: 2 });
const taskTimeoutMinutes = ref(0);
const saving = ref(false);

const parallelOptions = Array.from({ length: 8 }, (_, i) => ({ label: `${i + 1}`, value: i + 1 }));

// 四个模块各自独立的并行数设置
const parallelModules: { key: ModuleName; label: string }[] = [
  { key: "audio", label: "🎵 音频" },
  { key: "video", label: "🎬 视频" },
  { key: "image", label: "🖼️ 图片" },
  { key: "doc", label: "📄 文档" },
];

function loadIntoForm(): void {
  theme.value = settings.theme;
  defaultOutputDir.value = settings.defaultOutputDir;
  maxParallel.value = { ...settings.maxParallel };
  taskTimeoutMinutes.value = settings.taskTimeoutMinutes;
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
    });
    await settings.save(); // 后端按模块热更新并行数即时生效
    message.success("设置已保存，四个模块并行数已即时生效");
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
    <n-card title="⚙️ 全局设置" class="page-card">
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
            🌙 暗色主题
          </n-button>
          <n-button
            class="theme-card"
            :class="{ active: theme === 'light' }"
            @click="selectTheme('light')"
          >
            ☀️ 亮色主题
          </n-button>
        </n-space>
      </n-card>

      <!-- PyAV 引擎状态 -->
      <n-card title="PyAV 引擎" size="small" class="section">
        <div v-if="engine.status" class="engine-info">
          <div class="engine-row">
            <span class="engine-label">状态</span>
            <span :style="{ color: engine.status.av.available ? '#00d9ff' : '#e94560' }">
              {{ engine.status.av.available ? "✓ 已就绪" : "✗ 不可用" }}
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
        <div class="spin-row">
          <span class="spin-label">每模块最大并行数（各自独立）</span>
        </div>
        <div class="parallel-grid">
          <div v-for="m in parallelModules" :key="m.key" class="parallel-item">
            <span class="parallel-label">{{ m.label }}</span>
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
          <n-button type="primary" :loading="saving" @click="save">💾 保存设置</n-button>
        </n-space>
      </n-card>
    </n-card>
  </n-spin>
</template>

<style scoped>
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
</style>
