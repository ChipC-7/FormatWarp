import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { initBackend, connected } from "./composables/useBackend";
import { initBackendPort } from "./api/client";
import { useSettingsStore } from "./stores/settings";
import { useEngineStore } from "./stores/engine";

async function bootstrap(): Promise<void> {
  const app = createApp(App);
  app.use(createPinia());
  app.use(router);
  app.mount("#app");

  // 先解析后端端口，再建立 WS 连接与数据加载
  await initBackendPort();
  initBackend();

  void useSettingsStore().load();
  void useEngineStore().refresh();
  // 断线期间持续尝试拉取设置/引擎状态
  void watchConnection();
}

// 后端重新连上后刷新数据
function watchConnection(): void {
  setInterval(() => {
    if (connected.value) {
      void useSettingsStore().load();
      void useEngineStore().refresh();
    }
  }, 15000);
}

void bootstrap();
