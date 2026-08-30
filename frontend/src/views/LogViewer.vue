<script setup lang="ts">
// 运行日志页：等宽字体日志流（级别着色）+ 引擎状态卡片
import { computed } from "vue";
import { NButton, NCard, NEmpty, NList, NListItem } from "naive-ui";
import { useTasksStore } from "../stores/tasks";
import { useEngineStore } from "../stores/engine";
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
const LEVEL_ICON: Record<LogLevel, string> = {
  info: "ℹ️", success: "✅", warning: "⚠️", error: "❌",
};

/** 倒序显示（最新在上） */
const reversedLogs = computed(() => [...tasks.logs].reverse());

function clearLogs(): void {
  tasks.logs.splice(0);
}

// ---------- 引擎状态卡片 ----------
const engineLines = computed(() => {
  const av = engine.status?.av;
  const doc = engine.status?.doc;
  const lines: string[] = [];
  if (!av) {
    return ["引擎状态：加载中…"];
  }
  if (av.available) {
    lines.push(`状态:  ✓ 已就绪`);
    lines.push(`版本:  PyAV ${av.version}（内置 FFmpeg）`);
    const gpuNames = Object.values(av.gpu ?? {});
    lines.push(`硬件:  ${gpuNames.length ? gpuNames.join("、") : "未检测到可用 GPU"}`);
  } else {
    lines.push("状态:  ✗ 未检测到 PyAV 引擎");
  }
  lines.push(`Pillow: ${engine.status?.pillow ? "✅ 可用" : "❌ 不可用"}`);
  if (doc) {
    lines.push(`pandoc: ${doc.pandoc ? `✅ ${doc.pandoc}` : "❌ 未检测到"}`);
    lines.push(`wkhtmltopdf: ${doc.wkhtmltopdf ? `✅ ${doc.wkhtmltopdf}` : "—"}`);
  }
  return lines;
});
</script>

<template>
  <n-card title="📋 运行日志" class="page-card">
    <!-- 引擎状态卡片 -->
    <n-card title="引擎状态" size="small" class="engine-card">
      <div v-for="(l, i) in engineLines" :key="i" class="engine-line">{{ l }}</div>
    </n-card>

    <!-- 日志流 -->
    <div class="log-header">
      <span class="log-title">事件日志（最多 500 条）</span>
      <n-button size="small" @click="clearLogs">🗑 清空日志</n-button>
    </div>

    <div class="log-body">
      <n-empty v-if="!reversedLogs.length" description="暂无日志" />
      <n-list v-else>
        <n-list-item v-for="(l, i) in reversedLogs" :key="i" class="log-item">
          <span class="log-text" :style="{ color: LEVEL_COLOR[l.level] }">
            {{ l.ts }} {{ LEVEL_ICON[l.level] }} {{ l.message }}
          </span>
        </n-list-item>
      </n-list>
    </div>
  </n-card>
</template>

<style scoped>
.engine-card {
  margin-bottom: 16px;
}
.engine-line {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 12px;
  line-height: 1.9;
  word-break: break-all;
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
