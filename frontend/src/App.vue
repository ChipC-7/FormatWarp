<script setup lang="ts">
// 根组件：Naive UI 主题提供者 + 消息/对话框提供者 + 路由出口
import { computed } from "vue";
import {
  NConfigProvider, NMessageProvider, NDialogProvider, NGlobalStyle, NSpin,
  zhCN, dateZhCN,
} from "naive-ui";
import { useSettingsStore } from "./stores/settings";
import { themeFor, overridesFor } from "./styles/theme";
import { backendBooting, backendBootError } from "./composables/useBackend";
import BrandMark from "./components/BrandMark.vue";

const settings = useSettingsStore();
const theme = computed(() => themeFor(settings.theme));
const overrides = computed(() => overridesFor(settings.theme));
</script>

<template>
  <n-config-provider
    :theme="theme"
    :theme-overrides="overrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-global-style />
    <n-message-provider>
      <n-dialog-provider>
        <!-- 启动遮罩：等后端健康检查与 WebSocket 就绪后再显示主界面，
             避免前端先加载、后端后启动时闪出“后端未连接”黄条 -->
        <div v-if="backendBooting" class="boot-screen">
          <BrandMark :size="64" />
          <div class="boot-title">格式跃迁</div>
          <n-spin size="small" />
          <div class="boot-hint">{{ backendBootError || "正在启动本地转换引擎…" }}</div>
        </div>
        <router-view v-else />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  padding: 0;
}
* {
  box-sizing: border-box;
}

.boot-screen {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
}

.boot-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 4px;
}

.boot-hint {
  font-size: 12px;
  opacity: 0.6;
}
</style>
