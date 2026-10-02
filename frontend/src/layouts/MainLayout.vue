<script setup lang="ts">
// 主布局：左侧 240px 导航 + 右侧内容区（含后端断连黄条）
import { h, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NLayout, NLayoutSider, NLayoutContent, NMenu, NAlert } from "naive-ui";
import type { MenuOption } from "naive-ui";
import { connected } from "../composables/useBackend";
import { useEngineStore } from "../stores/engine";
import AppIcon from "../components/AppIcon.vue";
import BrandMark from "../components/BrandMark.vue";

const route = useRoute();
const router = useRouter();
const engine = useEngineStore();

// 导航项：统一线性图标（不再用 emoji）
const navItems: { label: string; key: string; icon: string }[] = [
  { label: "音频转换", key: "/audio", icon: "audio" },
  { label: "视频转换", key: "/video", icon: "video" },
  { label: "图片转换", key: "/image", icon: "image" },
  { label: "文档转换", key: "/doc", icon: "doc" },
  { label: "转换监控", key: "/monitor", icon: "activity" },
  { label: "运行日志", key: "/logs", icon: "logs" },
  { label: "全局设置", key: "/settings", icon: "settings" },
];
const navOptions: MenuOption[] = navItems.map((it) => ({
  label: it.label,
  key: it.key,
  icon: () => h(AppIcon, { name: it.icon, size: 17 }),
}));

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
      <div class="brand-block">
        <BrandMark :size="38" />
        <div class="brand-name">格式跃迁</div>
        <div class="app-version">v{{ engine.version }}</div>
      </div>
      <n-menu
        :options="navOptions"
        :value="route.path"
        class="side-menu"
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
.brand-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 6px 0 4px;
}
.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  margin-top: 2px;
}
.app-version {
  font-size: 11px;
  opacity: 0.55;
  margin-bottom: 14px;
  font-variant-numeric: tabular-nums;
}
.side-menu {
  flex: 1;
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
