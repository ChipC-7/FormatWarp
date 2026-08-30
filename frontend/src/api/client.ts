// fetch 封装：baseUrl = http://127.0.0.1:<port>
// 端口优先级：Tauri 命令 backend_port（Rust 壳）→ localStorage → 默认 8765

import { invoke } from "@tauri-apps/api/core";

const DEFAULT_PORT = 8765;
let baseUrl: string | null = null;

/** 获取当前后端 baseUrl（惰性解析并缓存） */
export function getBaseUrl(): string {
  if (baseUrl) return baseUrl;
  const port = Number(localStorage.getItem("formatwarp_port")) || DEFAULT_PORT;
  baseUrl = `http://127.0.0.1:${port}`;
  return baseUrl;
}

/** 手动指定端口（后端实际端口通过 FORMATWARP_PORT 上报） */
export function setBackendPort(port: number): void {
  localStorage.setItem("formatwarp_port", String(port));
  baseUrl = `http://127.0.0.1:${port}`;
}

/** 启动时尝试从 Tauri 命令读取后端端口；非 Tauri 环境（浏览器 dev 双开）静默回退。
 *  - Tauri（prod/dev）：invoke("backend_port") 返回 Rust 侧解析的 FORMATWARP_PORT；
 *  - 浏览器 dev：invoke 不可用 → 回退 localStorage / 固定 8765 直连，方便双开调试。 */
export async function initBackendPort(): Promise<void> {
  try {
    // 仅当运行在 Tauri 环境时存在该命令
    const port = await invoke<number>("backend_port");
    if (port && port > 0) {
      setBackendPort(port);
    }
  } catch {
    /* 浏览器开发环境：走 localStorage / 默认端口 */
  }
}

/** GET 请求 */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${path}`);
  }
  return (await res.json()) as T;
}

/** POST 请求（body 可为空对象） */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${path}`);
  }
  return (await res.json()) as T;
}
