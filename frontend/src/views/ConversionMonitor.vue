<script setup lang="ts">
// 转换监控页：活跃任务 + 总进度 + 成功/失败结果两栏（数据来自 stores/tasks.ts）
import { computed, ref, watch } from "vue";
import {
  NAlert, NButton, NCard, NEmpty, NList, NListItem, NProgress, NSpace,
  NTooltip,
} from "naive-ui";
import { useTasksStore } from "../stores/tasks";

const tasks = useTasksStore();

const MODULE_EMOJI: Record<string, string> = {
  audio: "🎵", video: "🎬", image: "🖼️", doc: "📄",
};
const MODULE_NAME: Record<string, string> = {
  audio: "音频", video: "视频", image: "图片", doc: "文档",
};

// 进行中任务（module + filename + 进度 + 取消）
const activeCards = computed(() => tasks.active);

const statusText = computed(() => {
  const n = activeCards.value.length;
  return n ? `正在转换 ${n} 个文件…` : "当前没有正在进行的转换任务";
});

// ---------- 总进度（算法照搬旧版：已完成*100 + 活跃进度和 / 总启动数） ----------
const totalStarted = computed(() => tasks.active.length + tasks.history.length);
const totalProgress = computed(() => {
  if (!totalStarted.value) return 0;
  const completed = tasks.history.length;
  const activeSum = tasks.active.reduce((s, t) => s + (t.progress || 0), 0);
  const numerator = completed * 100 + activeSum;
  return Math.max(0, Math.min(100, Math.round(numerator / totalStarted.value)));
});
const totalInfo = computed(() => {
  const done = tasks.history.length;
  const running = tasks.active.length;
  const success = tasks.history.filter((t) => t.success).length;
  const fail = tasks.history.filter((t) => !t.success).length;
  const pending = Math.max(0, totalStarted.value - done - running);
  return `总计 ${totalStarted.value} 个任务 | 已完成 ${done} | 进行中 ${running} | 待处理 ${pending} | 成功 ${success} | 失败 ${fail}`;
});

// ---------- 成功/失败结果两栏（本地副本，可清空） ----------
interface ResultEntry {
  task_id: number;
  module: string;
  filename: string;
  message: string;
}
const successList = ref<ResultEntry[]>([]);
const failureList = ref<ResultEntry[]>([]);

/** 消息首行截断 140 字 */
function firstLine(msg: string): string {
  const line = (msg || "").split("\n")[0] || "转换完成";
  return line.length > 140 ? line.slice(0, 137) + "..." : line;
}

/** 同步 store 历史到结果列表（按 task_id 去重追加） */
function syncResults(): void {
  const seen = new Set<number>([
    ...successList.value.map((r) => r.task_id),
    ...failureList.value.map((r) => r.task_id),
  ]);
  for (const t of tasks.history) {
    if (seen.has(t.task_id)) continue;
    seen.add(t.task_id);
    const entry: ResultEntry = {
      task_id: t.task_id,
      module: t.module,
      filename: t.filename,
      message: t.message || (t.success ? "转换成功" : "转换失败"),
    };
    (t.success ? successList : failureList).value.unshift(entry);
  }
}
watch(() => tasks.history.length, syncResults);

function clearResults(): void {
  successList.value = [];
  failureList.value = [];
}

async function cancelTask(taskId: number): Promise<void> {
  await tasks.cancel(taskId);
  void tasks.refresh();
}

async function refresh(): Promise<void> {
  await tasks.refresh();
  syncResults();
}

// 初始拉取一次
void refresh();
</script>

<template>
  <n-card title="📊 转换监控" class="page-card">
    <n-alert :type="activeCards.length ? 'success' : 'info'" :show-icon="false" class="status-line">
      {{ statusText }}
    </n-alert>

    <!-- 总进度 -->
    <div class="total-group">
      <div class="total-info">{{ totalInfo }}</div>
      <n-progress type="line" :percentage="totalProgress" :height="16" processing />
    </div>

    <!-- 活跃任务 -->
    <n-card title="进行中任务" size="small" class="sub-card">
      <n-empty v-if="!activeCards.length" description="当前没有正在进行的转换任务" />
      <n-list v-else bordered>
        <n-list-item v-for="t in activeCards" :key="t.task_id" class="task-item">
          <div class="task-row">
            <span class="task-name">{{ MODULE_EMOJI[t.module] }} {{ MODULE_NAME[t.module] }} — {{ t.filename }}</span>
            <n-progress
              type="line"
              :percentage="t.progress"
              :height="10"
              class="task-progress"
            />
            <n-button size="tiny" type="error" @click="cancelTask(t.task_id)">取消</n-button>
          </div>
        </n-list-item>
      </n-list>
    </n-card>

    <!-- 结果两栏 -->
    <div class="result-row">
      <n-card title="✅ 成功文件" size="small" class="result-col">
        <n-empty v-if="!successList.length" description="暂无成功记录" size="small" />
        <n-list v-else bordered size="small">
          <n-list-item v-for="r in successList" :key="r.task_id">
            <n-tooltip>
              <template #trigger>
                <span class="result-line">{{ MODULE_EMOJI[r.module] }} {{ r.filename }} — {{ firstLine(r.message) }}</span>
              </template>
              {{ r.message }}
            </n-tooltip>
          </n-list-item>
        </n-list>
      </n-card>
      <n-card title="❌ 失败文件" size="small" class="result-col">
        <n-empty v-if="!failureList.length" description="暂无失败记录" size="small" />
        <n-list v-else bordered size="small">
          <n-list-item v-for="r in failureList" :key="r.task_id">
            <n-tooltip>
              <template #trigger>
                <span class="result-line">{{ MODULE_EMOJI[r.module] }} {{ r.filename }} — {{ firstLine(r.message) }}</span>
              </template>
              {{ r.message }}
            </n-tooltip>
          </n-list-item>
        </n-list>
      </n-card>
    </div>

    <n-space class="result-actions">
      <n-button size="small" @click="refresh">🔄 刷新</n-button>
      <n-button size="small" @click="clearResults">🗑 清空结果</n-button>
    </n-space>
  </n-card>
</template>

<style scoped>
.status-line { margin-bottom: 12px; }
.total-group { margin: 12px 0; }
.total-info { font-size: 13px; opacity: 0.85; margin-bottom: 6px; }
.sub-card { margin-bottom: 12px; }
.task-row { display: flex; align-items: center; gap: 12px; }
.task-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.task-progress { flex: 2; }
.result-row { display: flex; gap: 12px; }
.result-col { flex: 1; min-width: 0; }
.result-line { font-size: 12px; cursor: default; word-break: break-all; }
.result-actions { margin-top: 12px; display: flex; gap: 8px; }
</style>
