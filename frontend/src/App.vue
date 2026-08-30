<script setup lang="ts">
// 根组件：Naive UI 主题提供者 + 消息/对话框提供者 + 路由出口
import { computed } from "vue";
import { NConfigProvider, NMessageProvider, NDialogProvider, NGlobalStyle, zhCN, dateZhCN } from "naive-ui";
import { useSettingsStore } from "./stores/settings";
import { themeFor, overridesFor } from "./styles/theme";

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
        <router-view />
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
</style>
