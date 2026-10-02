<script setup lang="ts">
// 文档转换页：14 种输出格式 + PDF DPI + 引擎状态面板
import { computed, ref } from "vue";
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NForm, NFormItem, NInput,
  NInputGroup, NInputNumber, NList, NListItem, NProgress, NSelect, NSpace,
  NSpin, NDropdown,
} from "naive-ui";
import type { SelectOption } from "naive-ui";
import { useConverterPage } from "../composables/useConverterPage";
import { useEngineStore } from "../stores/engine";
import AppIcon from "../components/AppIcon.vue";

const page = useConverterPage("doc", true); // 拖入允许递归目录
const engine = useEngineStore();

const formatOptions = computed<SelectOption[]>(() =>
  (page.formats.value?.outputs ?? []).map((o) => ({ label: o.desc, value: o.key })),
);

// ---------- 状态 ----------
const outputFormat = ref("pdf");
const outputDir = ref("");
const pdfDpi = ref(200);
const overwrite = ref(false);

async function browseOutputDir(): Promise<void> {
  const dir = await page.pickDirectory();
  if (dir) outputDir.value = dir;
}

async function startConversion(): Promise<void> {
  await page.start({
    output_format: outputFormat.value,
    output_dir: outputDir.value.trim(),
    params: { pdf_dpi: pdfDpi.value },
    overwrite: overwrite.value,
  });
}

// ---------- 引擎状态面板 ----------
interface EngineLine {
  icon: string;
  tone: "ok" | "warn" | "info";
  text: string;
}
const engineLines = computed<EngineLine[]>(() => {
  const d = engine.status?.doc;
  if (!d) return [{ icon: "info", tone: "info", text: "引擎状态：加载中…" }];
  const lines: EngineLine[] = [];
  const nativeHits = Object.entries(d.native_flags).filter(([, v]) => v).map(([k]) => k);
  lines.push(
    nativeHits.length
      ? { icon: "check-circle", tone: "ok", text: `Python 原生库：${nativeHits.join(",")}` }
      : { icon: "x-circle", tone: "warn", text: "无可用 Python 原生文档库（缺少依赖）" },
  );
  // 已安装但导入失败
  const broken = Object.entries(d.native_errors)
    .filter(([, msg]) => msg && !String(msg).startsWith("未安装"))
    .map(([k]) => k);
  if (broken.length) {
    lines.push({ icon: "alert", tone: "warn", text: `已安装但导入失败：${broken.join(", ")}` });
  }
  lines.push(
    d.pandoc
      ? { icon: "check-circle", tone: "ok", text: `pandoc（主力）：${d.pandoc}` }
      : { icon: "alert", tone: "warn", text: "未检测到 pandoc（通用文档互转主力）" },
  );
  if (d.wkhtmltopdf) {
    lines.push({ icon: "check-circle", tone: "ok", text: `wkhtmltopdf：${d.wkhtmltopdf}` });
  } else if (!d.native_flags.weasyprint) {
    lines.push({ icon: "info", tone: "info", text: "未检测到 HTML→PDF 引擎（推荐 weasyprint 或 wkhtmltopdf）" });
  }
  return lines;
});
</script>

<template>
  <n-spin :show="page.loadingFormats.value">
    <n-alert type="success" class="hint">
      <template #icon><AppIcon name="lock" :size="16" /></template>
      文件不出本机，全程本地转换（五级文档引擎链）。
    </n-alert>

    <n-card class="page-card">
      <template #header>
        <span class="card-title"><AppIcon name="doc" :size="18" /> 文档格式转换</span>
      </template>
      <div class="layout">
        <!-- 左：文件列表（支持递归目录） -->
        <n-card title="待转换文档" size="small" class="panel">
          <div
            class="drop-zone"
            :class="{ hover: page.dragHover.value }"
            @dragover.prevent="page.onDomDragOver"
            @dragleave.prevent="page.onDomDragLeave"
            @drop.prevent="page.onDomDrop"
            @click="page.addFilesDialog()"
          >
            <n-empty v-if="!page.files.value.length" description="拖入文档或文件夹（递归），或点击添加" />
            <n-list v-else bordered>
              <n-list-item
                v-for="f in page.files.value"
                :key="f.path"
                class="file-item"
                @contextmenu.prevent="page.onContextMenu($event, f.path)"
              >
                <div class="file-row">
                  <span class="file-name"><AppIcon name="doc" :size="14" class="file-ico" /> {{ f.name }}</span>
                  <span class="file-size">{{ page.formatSize(f.size) }}</span>
                  <n-button size="tiny" text type="error" @click="page.removeFile(f.path)">移除</n-button>
                </div>
              </n-list-item>
            </n-list>
          </div>
          <div class="file-actions">
            <n-button size="small" @click="page.addFilesDialog()">
              <template #icon><AppIcon name="plus" :size="15" /></template>
              添加文件/文件夹
            </n-button>
            <n-button size="small" @click="page.clearFiles()">
              <template #icon><AppIcon name="trash" :size="15" /></template>
              清空全部
            </n-button>
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
            <n-form-item label="PDF DPI">
              <n-input-number v-model:value="pdfDpi" :min="72" :max="600" :step="10" style="width: 160px" />
            </n-form-item>
            <n-form-item label="覆盖">
              <n-checkbox v-model:checked="overwrite">覆盖同名文件</n-checkbox>
            </n-form-item>
          </n-form>

          <!-- 引擎状态卡片（对齐旧版"引擎状态"面板） -->
          <div class="engine-card">
            <div class="engine-title"><AppIcon name="wrench" :size="14" class="title-ico" /> 引擎状态</div>
            <div v-for="(l, i) in engineLines" :key="i" class="engine-line" :class="l.tone">
              <AppIcon :name="l.icon" :size="13" class="line-ico" />
              <span>{{ l.text }}</span>
            </div>
          </div>
        </n-card>
      </div>

      <!-- 底部操作 + 进度 -->
      <n-space class="action-bar" justify="space-between" align="center">
        <n-space>
          <n-button type="primary" :loading="page.converting.value" @click="startConversion">
            <template #icon><AppIcon name="play" :size="15" /></template>
            开始转换
          </n-button>
          <n-button :disabled="!page.converting.value" @click="page.stop()">
            <template #icon><AppIcon name="stop" :size="14" /></template>
            停止
          </n-button>
          <n-button @click="page.openOutputDir(outputDir.trim())">
            <template #icon><AppIcon name="folder-open" :size="15" /></template>
            打开输出目录
          </n-button>
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
.card-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.file-ico {
  vertical-align: -2px;
}
.title-ico {
  vertical-align: -2px;
}
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

.engine-card {
  margin-top: 16px;
  border: 1px solid var(--n-border-color, #0f3460);
  border-radius: 8px;
  padding: 10px 12px;
  background-color: var(--n-card-color, #16213e);
}
.engine-title {
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.engine-line {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 12px;
  line-height: 1.8;
  word-break: break-all;
  display: flex;
  align-items: center;
  gap: 6px;
}
.engine-line.ok { color: #34d399; }
.engine-line.warn { color: #fbbf24; }
.engine-line.info { color: #94a3b8; }
.line-ico {
  flex-shrink: 0;
}
</style>
