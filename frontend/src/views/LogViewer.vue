<script setup lang="ts">
// 运行日志页：等宽字体日志流（级别着色）+ 引擎状态卡片
import { computed } from "vue";
import { NButton, NCard, NEmpty, NList, NListItem } from "naive-ui";
import { useTasksStore } from "../stores/tasks";
import { useEngineStore } from "../stores/engine";
import AppIcon from "../components/AppIcon.vue";
import type { LogLevel } from "../types/backend";

const tasks = useTasksStore();
const engine = useEngineStore();

// 级别 → 颜色（info灰 / success青 / warning橙 / error红）
const LEVEL_COLOR: Record<LogLevel, string> = {
  info: "#a0a0a0",
  success: "#00d9ff",
  warning: "#f9a826",
  error: "#e94560",
};
// 级别 → 线性图标
const LEVEL_ICON: Record<LogLevel, string> = {
  info: "info", success: "check-circle", warning: "alert", error: "x-circle",
};

/** 倒序显示（最新在上） */
const reversedLogs = computed(() => [...tasks.logs].reverse());

function clearLogs(): void {
  tasks.logs.splice(0);
}

// ---------- 引擎状态卡片 ----------
interface EngineLine { icon: string; text: string; ok?: boolean }
const engineLines = computed<EngineLine[]>(() => {
  const av = engine.status?.av;
  const doc = engine.status?.doc;
  const lines: EngineLine[] = [];
  if (!av) {
    return [{ icon: "info", text: "引擎状态：加载中…" }];
  }
  if (av.available) {
    lines.push({ icon: "check-circle", text: "状态：已就绪", ok: true });
    lines.push({ icon: "info", text: `版本：PyAV ${av.version}（内置 FFmpeg）` });
    const gpuNames = Object.values(av.gpu ?? {});
    lines.push({ icon: "info", text: `硬件：${gpuNames.length ? gpuNames.join("、") : "未检测到可用 GPU"}` });
  } else {
    lines.push({ icon: "x-circle", text: "状态：未检测到 PyAV 引擎" });
  }
  lines.push({
    icon: engine.status?.pillow ? "check-circle" : "x-circle",
    text: `Pillow：${engine.status?.pillow ? "可用" : "不可用"}`,
  });
  if (doc) {
    lines.push({
      icon: doc.pandoc ? "check-circle" : "x-circle",
      text: `pandoc：${doc.pandoc ?? "未检测到"}`,
    });
    lines.push({
      icon: doc.wkhtmltopdf ? "check-circle" : "info",
      text: `wkhtmltopdf：${doc.wkhtmltopdf ?? "—"}`,
    });
  }
  return lines;
});
</script>

<template>
  <n-card class="page-card">
    <template #header>
      <span class="card-title"><AppIcon name="logs" :size="18" /> 运行日志</span>
    </template>
    <!-- 引擎状态卡片 -->
    <n-card title="引擎状态" size="small" class="engine-card">
      <div v-for="(l, i) in engineLines" :key="i" class="engine-line">
        <AppIcon :name="l.icon" :size="14" :class="l.ok ? 'ok-icon' : ''" />
        <span>{{ l.text }}</span>
      </div>
    </n-card>

    <!-- 日志流 -->
    <div class="log-header">
      <span class="log-title">事件日志（最多 500 条）</span>
      <n-button size="small" @click="clearLogs">
        <template #icon><AppIcon name="trash" :size="14" /></template>
        清空日志
      </n-button>
    </div>

    <div class="log-body">
      <n-empty v-if="!reversedLogs.length" description="暂无日志" />
      <n-list v-else>
        <n-list-item v-for="(l, i) in reversedLogs" :key="i" class="log-item">
          <span class="log-text" :style="{ color: LEVEL_COLOR[l.level] }">
            {{ l.ts }}
            <AppIcon :name="LEVEL_ICON[l.level]" :size="13" class="log-level-icon" />
            {{ l.message }}
          </span>
        </n-list-item>
      </n-list>
    </div>
  </n-card>
</template>

<style scoped>
.card-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.engine-card {
  margin-bottom: 16px;
}
.engine-line {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 12px;
  line-height: 1.9;
  word-break: break-all;
  display: flex;
  align-items: center;
  gap: 7px;
}
.ok-icon { color: #34d399; }
.log-level-icon {
  vertical-align: -2px;
  margin: 0 2px;
}
.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.log-title {
  font-size: 14px;
  font-weight: 600;
}
.log-body {
  border: 1px solid var(--n-border-color, #0f3460);
  border-radius: 8px;
  overflow: auto;
  max-height: 520px;
}
.log-item {
  padding: 2px 0;
}
.log-text {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 12px;
  word-break: break-all;
}
</style>
