// WebSocket 单例：自动重连（指数退避）、心跳、消息类型分发到 stores。
// 断线时 connected=false，页面据此显示「后端未连接」黄条；3s 起步重连，封顶 30s。
import { ref } from "vue";
import { getBaseUrl } from "../api/client";
import type { WsClientMessage, WsServerMessage } from "../types/backend";
import { useTasksStore } from "../stores/tasks";
import { useEngineStore } from "../stores/engine";

/** 是否已连接（响应式，供页面/布局显示黄条） */
export const connected = ref(false);

/** 重连次数（用于指数退避：2^n 秒，封顶 30s） */
const reconnectAttempt = ref(0);

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
let heartbeatTimer: ReturnType<typeof setInterval> | undefined;

/** 订阅 WS 消息（返回取消订阅函数） */
const subscribers = new Set<(msg: WsServerMessage) => void>();
export function onMessage(handler: (msg: WsServerMessage) => void): () => void {
  subscribers.add(handler);
  return () => {
    subscribers.delete(handler);
  };
}

/** 分发消息：先更新 stores，再通知订阅者 */
function dispatch(msg: WsServerMessage): void {
  useTasksStore().dispatchWs(msg);
  if (msg.type === "engine_status") {
    useEngineStore().applyEngine(msg.engine);
  }
  for (const fn of subscribers) {
    try {
      fn(msg);
    } catch {
      /* 单个订阅者异常不影响其他订阅者 */
    }
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempt.value));
  reconnectTimer = setTimeout(() => {
    reconnectTimer = undefined;
    connect();
  }, delay);
}

/** 建立（或重建）WebSocket 连接 */
export function connect(): void {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  let socket: WebSocket;
  try {
    const wsUrl = getBaseUrl().replace(/^http/, "ws") + "/ws";
    socket = new WebSocket(wsUrl);
  } catch {
    scheduleReconnect();
    return;
  }
  ws = socket;

  socket.onopen = () => {
    connected.value = true;
    reconnectAttempt.value = 0;
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => send({ type: "ping" }), 15000);
  };

  socket.onmessage = (ev: MessageEvent<string>) => {
    try {
      const msg = JSON.parse(ev.data as string) as WsServerMessage;
      dispatch(msg);
    } catch {
      /* 忽略无法解析的帧 */
    }
  };

  socket.onclose = () => {
    connected.value = false;
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = undefined;
    }
    scheduleReconnect();
  };

  socket.onerror = () => {
    try {
      socket.close();
    } catch {
      /* 已关闭 */
    }
  };
}

/** 发送客户端消息 */
export function send(msg: WsClientMessage): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

/** 应用启动时初始化连接 */
export function initBackend(): void {
  connect();
}
