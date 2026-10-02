<script setup lang="ts">
// 品牌标志：直接使用项目现有图标（src-tauri/icons 同源）。
// 用法：<BrandMark :size="44" />
import brandUrl from "../assets/brand.png";

withDefaults(defineProps<{ size?: number }>(), { size: 44 });
</script>

<template>
  <img :src="brandUrl" :width="size" :height="size" alt="格式跃迁" class="brand-img" />
</template>

<style scoped>
.brand-img {
  border-radius: 22%;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
</style>
