<script setup lang="ts">
// 主布局：左侧 240px 导航 + 右侧内容区（含后端断连黄条）
import { onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NLayout, NLayoutSider, NLayoutContent, NMenu, NAlert } from "naive-ui";
import type { MenuOption } from "naive-ui";
import { connected } from "../composables/useBackend";
import { useEngineStore } from "../stores/engine";

const route = useRoute();
const router = useRouter();
const engine = useEngineStore();

// 导航项：emoji 图标对齐旧版导航文案
const navOptions: MenuOption[] = [
  { label: "🎵 音频转换", key: "/audio" },
  { label: "🎬 视频转换", key: "/video" },
  { label: "🖼️ 图片转换", key: "/image" },
  { label: "📄 文档转换", key: "/doc" },
  { label: "📊 转换监控", key: "/monitor" },
  { label: "📋 运行日志", key: "/logs" },
  { label: "⚙️ 全局设置", key: "/settings" },
];

function onSelect(key: string): void {
  void router.push(key);
}

// 引擎健康轮询：30s
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  void engine.refresh();
  timer = setInterval(() => void engine.refresh(), 30000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      :width="240"
      :native-scrollbar="false"
      content-style="display:flex;flex-direction:column;height:100%;padding-top:16px"
    >
      <div class="app-logo">🛠️ 格式跃迁</div>
      <div class="app-version">v0.1.0</div>
      <n-menu
        :options="navOptions"
        :value="route.path"
        @update:value="onSelect"
      />
    </n-layout-sider>

    <n-layout-content :native-scrollbar="false" content-style="display:flex;flex-direction:column;height:100%">
      <!-- 后端断连提示 -->
      <n-alert v-if="!connected" type="warning" :show-icon="false" class="backend-offline">
        后端未连接，3 秒后自动重试…
      </n-alert>
      <div class="page-content">
        <router-view />
      </div>
    </n-layout-content>
  </n-layout>
</template>

<style scoped>
.app-logo {
  font-size: 18px;
  font-weight: 700;
  text-align: center;
  padding: 8px 0 2px;
}
.app-version {
  font-size: 12px;
  text-align: center;
  opacity: 0.6;
  margin-bottom: 18px;
}
.backend-offline {
  margin: 8px 16px 0;
}
.page-content {
  flex: 1;
  overflow: auto;
  padding: 16px 20px;
}
</style>
