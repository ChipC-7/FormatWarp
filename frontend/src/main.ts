import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { bootBackend, connected } from "./composables/useBackend";
import { useSettingsStore } from "./stores/settings";
import { useEngineStore } from "./stores/engine";

async function bootstrap(): Promise<void> {
  const app = createApp(App);
  app.use(createPinia());
  app.use(router);
  app.mount("#app");

  // 先等后端端口 + 健康检查 + WebSocket 就绪，再显示主界面并加载数据
  await bootBackend();

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
