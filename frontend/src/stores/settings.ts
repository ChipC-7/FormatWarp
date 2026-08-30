// 全局设置 store：主题 / 默认输出目录 / 并行数（按模块）/ 超时
// 启动时 GET /api/settings 加载；修改后 POST /api/settings 持久化
import { ref } from "vue";
import { defineStore } from "pinia";
import { apiGet, apiPost } from "../api/client";
import type { ParallelMap, Settings, ThemeMode } from "../types/backend";

/** 四模块默认并行数 */
const DEFAULT_PARALLEL: ParallelMap = { audio: 2, video: 2, image: 2, doc: 2 };

export const useSettingsStore = defineStore("settings", () => {
  const theme = ref<ThemeMode>("dark");
  const defaultOutputDir = ref("");
  const maxParallel = ref<ParallelMap>({ ...DEFAULT_PARALLEL });
  const taskTimeoutMinutes = ref(0);

  /** 从后端加载设置并写入 store */
  async function load(): Promise<void> {
    try {
      const s = await apiGet<Settings>("/api/settings");
      apply(s);
    } catch {
      /* 后端未连接时保留默认值 */
    }
  }

  /** 将后端设置应用到本地状态 */
  function apply(s: Settings): void {
    theme.value = s.theme === "light" ? "light" : "dark";
    defaultOutputDir.value = s.default_output_dir ?? "";
    maxParallel.value = { ...DEFAULT_PARALLEL, ...(s.max_parallel ?? {}) };
    taskTimeoutMinutes.value = s.task_timeout_minutes;
  }

  /** 持久化到后端 */
  async function save(): Promise<void> {
    await apiPost<{ ok: boolean; settings: Settings }>("/api/settings", {
      theme: theme.value,
      default_output_dir: defaultOutputDir.value,
      max_parallel: maxParallel.value,
      task_timeout_minutes: taskTimeoutMinutes.value,
    });
  }

  /** 切换主题（即时生效并持久化） */
  async function setTheme(mode: ThemeMode): Promise<void> {
    theme.value = mode;
    await save();
  }

  return {
    theme,
    defaultOutputDir,
    maxParallel,
    taskTimeoutMinutes,
    load,
    apply,
    save,
    setTheme,
  };
});
