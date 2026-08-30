// 引擎状态 store：/api/health 轮询（30s）+ WS engine_status 推送更新
import { ref } from "vue";
import { defineStore } from "pinia";
import { apiGet } from "../api/client";
import type { EngineStatus, HealthResponse } from "../types/backend";

export const useEngineStore = defineStore("engine", () => {
  const status = ref<EngineStatus | null>(null);
  const diskFreeGb = ref(0);
  const lastCheckAt = ref<number>(0);

  /** 从健康接口刷新引擎状态 */
  async function refresh(): Promise<void> {
    try {
      const h = await apiGet<HealthResponse>("/api/health");
      status.value = h.engines;
      diskFreeGb.value = h.disk_free_gb;
      lastCheckAt.value = Date.now();
    } catch {
      /* 后端未连接时保留上次状态 */
    }
  }

  /** 由 WS engine_status 消息直接更新 */
  function applyEngine(msg: EngineStatus): void {
    status.value = msg;
    lastCheckAt.value = Date.now();
  }

  return { status, diskFreeGb, lastCheckAt, refresh, applyEngine };
});
