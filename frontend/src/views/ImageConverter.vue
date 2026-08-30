<script setup lang="ts">
// 图片转换页：8 种输出格式 + 质量/缩放预设 + 保留 EXIF + 覆盖重名
import { computed, ref } from "vue";
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NForm, NFormItem, NInput,
  NInputGroup, NList, NListItem, NProgress, NSelect, NSpace, NSpin, NDropdown,
} from "naive-ui";
import type { SelectOption } from "naive-ui";
import { useConverterPage } from "../composables/useConverterPage";

const page = useConverterPage("image", true); // 拖入允许递归目录

const formatOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.outputs ?? []).map((o) => ({ label: o.desc, value: o.key })),
);

const qualityOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.presets.quality ?? []).map((p) => ({
    label: p.label,
    value: p.value as number,
  })),
);

// 缩放预设：value 为 null / ["percent",n] / ["max",n]，序列化为哨兵字符串
const scaleOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.presets.scale_mode ?? []).map((p) => ({
    label: p.label,
    value: p.value === null ? "__keep__" : JSON.stringify(p.value),
  })),
);

// 当前选中格式是否需要质量档
const needQuality = computed(() => {
  const fmt = (page.formats.value?.outputs ?? []).find((o) => o.key === outputFormat.value);
  return fmt?.need_quality ?? false;
});

// ---------- 状态 ----------
const outputFormat = ref("png");
const outputDir = ref("");
const quality = ref(92);
const scaleMode = ref<string>("__keep__");
const keepExif = ref(true);
const overwrite = ref(false);

async function browseOutputDir(): Promise<void> {
  const dir = await page.pickDirectory();
  if (dir) outputDir.value = dir;
}

async function startConversion(): Promise<void> {
  let scale: unknown = null;
  if (scaleMode.value !== "__keep__") {
    try {
      const parsed = JSON.parse(scaleMode.value) as [string, number];
      scale = parsed;
    } catch {
      scale = null;
    }
  }
  await page.start({
    output_format: outputFormat.value,
    output_dir: outputDir.value.trim(),
    params: {
      quality: quality.value,
      scale_mode: scale,
      keep_exif: keepExif.value,
    },
    overwrite: overwrite.value,
  });
}
</script>

<template>
  <n-spin :show="page.loadingFormats.value">
    <n-alert type="success" :show-icon="false" class="hint">
      🔒 文件不出本机，全程本地转换（Pillow 引擎）。
    </n-alert>

    <n-card title="🖼️ 图片格式转换" class="page-card">
      <div class="layout">
        <!-- 左：文件列表（支持递归目录） -->
        <n-card title="待转换图片" size="small" class="panel">
          <div
            class="drop-zone"
            :class="{ hover: page.dragHover.value }"
            @dragover.prevent="page.onDomDragOver"
            @dragleave.prevent="page.onDomDragLeave"
            @drop.prevent="page.onDomDrop"
            @click="page.addFilesDialog()"
          >
            <n-empty v-if="!page.files.value.length" description="拖入图片文件或文件夹（递归），或点击添加" />
            <n-list v-else bordered>
              <n-list-item
                v-for="f in page.files.value"
                :key="f.path"
                class="file-item"
                @contextmenu.prevent="page.onContextMenu($event, f.path)"
              >
                <div class="file-row">
                  <span class="file-name">🖼️ {{ f.name }}</span>
                  <span class="file-size">{{ page.formatSize(f.size) }}</span>
                  <n-button size="tiny" text type="error" @click="page.removeFile(f.path)">移除</n-button>
                </div>
              </n-list-item>
            </n-list>
          </div>
          <div class="file-actions">
            <n-button size="small" @click="page.addFilesDialog()">➕ 添加文件/文件夹</n-button>
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
            <n-form-item label="图片质量">
              <n-select v-model:value="quality" :options="qualityOptions" :disabled="!needQuality" />
            </n-form-item>
            <n-form-item label="尺寸缩放">
              <n-select v-model:value="scaleMode" :options="scaleOptions" />
            </n-form-item>
            <n-form-item label="EXIF">
              <n-checkbox v-model:checked="keepExif">保留 EXIF 信息</n-checkbox>
            </n-form-item>
            <n-form-item label="覆盖">
              <n-checkbox v-model:checked="overwrite">覆盖同名文件</n-checkbox>
            </n-form-item>
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
.action-bar { margin-top: 16px; }
.progress-block { min-width: 240px; }
.progress-text { font-size: 12px; opacity: 0.85; }
</style>
