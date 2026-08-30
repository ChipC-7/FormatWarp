<script setup lang="ts">
// 视频转换页：16 种视频格式 + 提取音频 + GPU 硬件加速
import { computed, h, ref, watch } from "vue";
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NForm, NFormItem, NInput,
  NInputGroup, NList, NListItem, NProgress, NSelect, NSpace, NSpin, NDropdown,
} from "naive-ui";
import type { SelectOption } from "naive-ui";
import { useConverterPage } from "../composables/useConverterPage";
import { useEngineStore } from "../stores/engine";

const page = useConverterPage("video", false);
const engine = useEngineStore();

// 视频 / 提取音频 两组输出格式（提取音频列表由后端 /api/formats 预检返回）
const videoFormats = computed(() => page.formats.value?.outputs ?? []);
const audioFormats = computed(() => page.formats.value?.extract_audio_outputs ?? []);

// 当前生效的格式下拉（提取音频时换成音频格式）
const extractAudio = ref(false);
const activeList = computed(() => (extractAudio.value ? audioFormats.value : videoFormats.value));

// 输出格式下拉：不支持的格式置灰禁用，label 加"（不支持）"后缀，
// hover 时用原生 title 展示 unsupported_reason 完整文案
const formatOptions = computed<SelectOption[]>(() =>
  activeList.value.map((o) => {
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

// 回退：当前选中格式在生效列表中不存在或不支持（如切换"提取音频"、旧配置
// 存了不支持的格式）时，自动切到当前列表第一个可用格式
watch(activeList, () => {
  const cur = activeList.value.find((o) => o.key === outputFormat.value);
  if (!cur || cur.supported === false) {
    const first = activeList.value.find((o) => o.supported !== false);
    if (first) outputFormat.value = first.key;
  }
});

const videoBitrateOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.presets.video_bitrate ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__auto__" : (p.value as string | number),
  })),
);
const audioBitrateOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.presets.audio_bitrate ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__auto__" : (p.value as string | number),
  })),
);

// ---------- 状态 ----------
const outputFormat = ref("mp4");
const outputDir = ref("");
const videoBitrate = ref<string | number>("__auto__");
const audioBitrate = ref<string | number>("__auto__");

// GPU 硬件加速
const hwEnabled = ref(true);
const hwValue = ref<string>("__auto__");
const gpuOptions = computed<SelectOption[]>(() => {
  const opts: SelectOption[] = [
    { label: "自动选择 (推荐)", value: "__auto__" },
    { label: "CPU 软件编码", value: "__cpu__" },
  ];
  const gpu = engine.status?.av.gpu ?? {};
  for (const [key, display] of Object.entries(gpu)) {
    opts.push({ label: `${display} (已就绪)`, value: key });
  }
  return opts;
});
const gpuHint = computed(() => {
  if (extractAudio.value) return "提取音频时无需视频编码，硬件加速已自动禁用";
  if (!hwEnabled.value) return "硬件加速已关闭，将使用 CPU 软件编码";
  if (hwValue.value === "__auto__") {
    const gpu = engine.status?.av.gpu ?? {};
    const names = Object.values(gpu);
    return names.length
      ? `💡 检测到 ${names.join("、")} 硬件，已自动开启加速；转换失败将自动降级为 CPU 编码`
      : "💡 未检测到可用硬件编码器，将使用 CPU 软件编码";
  }
  if (hwValue.value === "__cpu__") return "使用 CPU 软件编码，兼容性最好但速度较慢";
  return "💡 硬件加速模式下转换速度可提升 5-20 倍；如转换失败将自动降级为 CPU 编码";
});

function restoreNull(v: string | number): unknown {
  if (v === "__auto__" || v === "__cpu__") return v === "__auto__" ? null : "cpu";
  return v;
}

async function browseOutputDir(): Promise<void> {
  const dir = await page.pickDirectory();
  if (dir) outputDir.value = dir;
}

async function startConversion(): Promise<void> {
  await page.start({
    output_format: outputFormat.value,
    output_dir: outputDir.value.trim(),
    params: {
      video_bitrate: restoreNull(videoBitrate.value),
      audio_bitrate: extractAudio.value ? restoreNull(audioBitrate.value) : null,
      extract_audio: extractAudio.value,
      hardware_accel: extractAudio.value ? null : (hwEnabled.value ? restoreNull(hwValue.value) : null),
    },
  });
}
</script>

<template>
  <n-spin :show="page.loadingFormats.value">
    <n-alert type="success" :show-icon="false" class="hint">
      🔒 文件不出本机，全程本地转换（PyAV 进程内引擎）。
    </n-alert>

    <n-card title="🎬 视频格式转换" class="page-card">
      <div class="layout">
        <!-- 左：文件列表 -->
        <n-card title="待转换文件" size="small" class="panel">
          <div
            class="drop-zone"
            :class="{ hover: page.dragHover.value }"
            @dragover.prevent="page.onDomDragOver"
            @dragleave.prevent="page.onDomDragLeave"
            @drop.prevent="page.onDomDrop"
            @click="page.addFilesDialog()"
          >
            <n-empty v-if="!page.files.value.length" description="拖入视频文件，或点击此处添加" />
            <n-list v-else bordered>
              <n-list-item
                v-for="f in page.files.value"
                :key="f.path"
                class="file-item"
                @contextmenu.prevent="page.onContextMenu($event, f.path)"
              >
                <div class="file-row">
                  <span class="file-name">🎬 {{ f.name }}</span>
                  <span class="file-size">{{ page.formatSize(f.size) }}</span>
                  <n-button size="tiny" text type="error" @click="page.removeFile(f.path)">移除</n-button>
                </div>
              </n-list-item>
            </n-list>
          </div>
          <div class="file-actions">
            <n-button size="small" @click="page.addFilesDialog()">➕ 添加文件</n-button>
            <n-button size="small" @click="page.clearFiles()">🗑 清空全部</n-button>
          </div>
        </n-card>

        <!-- 右：转换设置 -->
        <n-card title="转换设置" size="small" class="panel">
          <n-form label-placement="left" label-width="96" size="medium">
            <n-form-item label="输出格式">
              <n-select v-model:value="outputFormat" :options="formatOptions" />
            </n-form-item>
            <n-form-item label="输出目录">
              <n-input-group>
                <n-input v-model:value="outputDir" placeholder="留空 = 与源文件同目录" />
                <n-button type="primary" ghost @click="browseOutputDir">浏览</n-button>
              </n-input-group>
            </n-form-item>
            <n-form-item label="视频码率">
              <n-select v-model:value="videoBitrate" :options="videoBitrateOptions" :disabled="extractAudio" />
            </n-form-item>
            <n-form-item label="提取音频">
              <n-checkbox v-model:checked="extractAudio">提取音频（忽略视频流）</n-checkbox>
            </n-form-item>
            <n-form-item v-if="extractAudio" label="音频码率">
              <n-select v-model:value="audioBitrate" :options="audioBitrateOptions" />
            </n-form-item>
            <template v-if="!extractAudio">
              <n-form-item label="硬件加速">
                <n-checkbox v-model:checked="hwEnabled">启用硬件加速 (GPU)</n-checkbox>
              </n-form-item>
              <n-form-item label="加速引擎">
                <n-select v-model:value="hwValue" :options="gpuOptions" :disabled="!hwEnabled" />
              </n-form-item>
            </template>
            <div class="hint-text">{{ gpuHint }}</div>
          </n-form>
        </n-card>
      </div>

      <!-- 底部操作 + 进度 -->
      <n-space class="action-bar" justify="space-between" align="center">
        <n-space>
          <n-button type="primary" :loading="page.converting.value" @click="startConversion">
            ▶ 开始转换
          </n-button>
          <n-button :disabled="!page.converting.value" @click="page.stop()">⏹ 停止</n-button>
          <n-button @click="page.openOutputDir(outputDir.trim())">📂 打开输出目录</n-button>
        </n-space>
        <n-space v-if="page.batchTasks.value.length" vertical size="small" class="progress-block">
          <span class="progress-text">
            {{ page.doneCount.value }}/{{ page.batchTasks.value.length }} 完成 · 总进度 {{ page.totalProgress.value }}%
          </span>
          <n-progress type="line" :percentage="page.totalProgress.value" :height="10" processing />
        </n-space>
      </n-space>
    </n-card>

    <n-dropdown
      :show="page.menuShow.value"
      :x="page.menuX.value"
      :y="page.menuY.value"
      :options="page.menuOptions"
      @select="page.onMenuSelect"
      @clickoutside="page.menuShow.value = false"
    />
  </n-spin>
</template>

<style scoped>
.hint { margin-bottom: 12px; }
.layout { display: flex; gap: 16px; align-items: stretch; }
.panel { flex: 1; min-width: 0; }
.drop-zone {
  min-height: 220px;
  border: 1px dashed var(--n-border-color, #0f3460);
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s;
}
.drop-zone.hover {
  border-color: var(--n-primary-color, #e94560);
  background-color: var(--n-color-hover, #1e2a4a);
}
.file-row { display: flex; align-items: center; gap: 8px; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { color: var(--n-text-color-3, #a0a0a0); font-size: 12px; }
.file-actions { margin-top: 8px; display: flex; gap: 8px; }
.hint-text { font-size: 12px; opacity: 0.75; padding: 0 2px; }
.action-bar { margin-top: 16px; }
.progress-block { min-width: 240px; }
.progress-text { font-size: 12px; opacity: 0.85; }
</style>
