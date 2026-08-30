// 路由：7 个页面，全部挂载在 MainLayout 内容区
import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "../layouts/MainLayout.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        { path: "", redirect: "/audio" },
        { path: "audio", name: "audio", component: () => import("../views/AudioConverter.vue") },
        { path: "video", name: "video", component: () => import("../views/VideoConverter.vue") },
        { path: "image", name: "image", component: () => import("../views/ImageConverter.vue") },
        { path: "doc", name: "doc", component: () => import("../views/DocConverter.vue") },
        { path: "monitor", name: "monitor", component: () => import("../views/ConversionMonitor.vue") },
        { path: "logs", name: "logs", component: () => import("../views/LogViewer.vue") },
        { path: "settings", name: "settings", component: () => import("../views/Settings.vue") },
      ],
    },
  ],
});

export default router;
