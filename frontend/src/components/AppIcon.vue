<script setup lang="ts">
// 统一线性图标（Raycast 风格：24×24、圆角线帽、1.75 描边、currentColor）。
// 用法：<AppIcon name="audio" :size="18" />
import { computed } from "vue";

const props = withDefaults(defineProps<{
  name: string;
  size?: number;
  strokeWidth?: number;
}>(), { size: 18, strokeWidth: 1.75 });

// 各图标的内部 SVG（描边路径，不填色）
const PATHS: Record<string, string> = {
  audio:
    '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  video:
    '<rect x="2.5" y="6" width="12.5" height="12" rx="2"/><path d="M15 10.4l5.5-2.6v8.4L15 13.6"/>',
  image:
    '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 15.5l-5-5L5 20"/>',
  doc:
    '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
  activity:
    '<path d="M3 12h4l2.6 6.2L14 5.8 16.6 12H21"/>',
  logs:
    '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M3.6 6h.01M3.6 12h.01M3.6 18h.01"/>',
  settings:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  "check-circle":
    '<circle cx="12" cy="12" r="9"/><path d="M8.3 12.4l2.5 2.5 4.9-5.2"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  "x-circle":
    '<circle cx="12" cy="12" r="9"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6"/>',
  refresh:
    '<path d="M20.5 11A8.5 8.5 0 1 0 19 15.6"/><path d="M21 4v6h-6"/>',
  trash:
    '<path d="M3.5 6h17"/><path d="M8.5 6V4.5A1.5 1.5 0 0 1 10 3h4a1.5 1.5 0 0 1 1.5 1.5V6"/><path d="M18.5 6l-.8 12.2a2 2 0 0 1-2 1.8H8.3a2 2 0 0 1-2-1.8L5.5 6"/><path d="M10 10.5v5.5M14 10.5v5.5"/>',
  plus:
    '<path d="M12 5v14M5 12h14"/>',
  lock:
    '<rect x="4.5" y="10.5" width="15" height="10" rx="2.2"/><path d="M8 10.5V7.6a4 4 0 0 1 8 0v2.9"/>',
  "folder-open":
    '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.4l1.8 2h6.8A1.5 1.5 0 0 1 19 9.5v.5H5.2l-2.7 8A1.5 1.5 0 0 0 4 20h13.5a1.5 1.5 0 0 0 1.4-1l2.6-7.5H7"/>',
  save:
    '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
  bolt:
    '<path d="M13 2L4.5 13.6H11L10 22l8.5-11.6H12z"/>',
  moon:
    '<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z"/>',
  sun:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"/>',
  info:
    '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.6h.01"/>',
  alert:
    '<path d="M12 3.2L2.8 19.5a1.4 1.4 0 0 0 1.2 2h16a1.4 1.4 0 0 0 1.2-2z"/><path d="M12 9.5v4.5"/><path d="M12 17.4h.01"/>',
  wrench:
    '<path d="M14.7 6.3a4.5 4.5 0 0 0 5.9 5.9c-.3 1.9-2 3.4-4 3.4a4.3 4.3 0 0 1-4-2.8L5.8 20.6a2 2 0 0 1-2.8-2.8l7.8-7.8a4.3 4.3 0 0 1-.3-1.6 4.3 4.3 0 0 1 4.2-4.3 4.5 4.5 0 0 0-.3 2.2z"/>',
  bulb:
    '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5.8 1.1.9 1.8h5.4c.1-.7.3-1.3.9-1.8A6 6 0 0 0 12 3z"/>',
  play:
    '<path d="M7 4.5l12.5 7.5L7 19.5z"/>',
  stop:
    '<rect x="6" y="6" width="12" height="12" rx="2"/>',
};

const inner = computed(() => PATHS[props.name] ?? "");
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="inner"
  />
</template>
