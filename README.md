# FormatWarp 格式跃迁

本地文件格式转换工具，支持 **音频 / 视频 / 图片 / 文档** 四大类格式互转。
全程本地处理，**文件不出本机**——无上传、无云端、无联网依赖。

> License: MIT

---

## 🚀 v3.0.0 — 全面重构

v3.0.0 是 FormatWarp 迄今最大的一次版本更新：**转码内核、界面框架、任务调度**
三个部分全部推倒重来。

### 1️⃣ 转码内核：pydub → PyAV

旧版基于 pydub，本质是 ffmpeg 命令行的浅层封装——每次转码都要拉起独立
子进程，参数控制受限、进度反馈粗糙、报错难以定位。

新版迁移至 **PyAV**（FFmpeg 原生绑定），直接调用 `libavcodec` / `libavformat`：

- 编码参数精细可控（码率、采样率、编码器、容器格式）
- 帧级进度回调，界面实时显示精确转码进度
- **无需单独安装 ffmpeg**，运行依赖全部内置

### 2️⃣ 界面：放弃 Qt，完全重写

旧版使用 PySide6 构建，交互与视觉已显陈旧。v3.0.0 采用 **Tauri 2 + Vue 3**
全新重写：

- 现代化界面，支持深色 / 浅色主题
- 拖拽导入、任务队列可视化、实时进度条
- 得益于 Tauri 使用系统 WebView，安装包更小巧、启动更快

### 3️⃣ 性能：串行处理 → 并行调度

旧版多文件转换只能逐个排队。v3.0.0 引入**并行任务调度**：

- 多文件批量转换充分利用多核 CPU
- 吞吐量随 CPU 核心数扩展，批量场景等待时间大幅缩短

### 架构总览（v3）┌─────────────────────────────┐
│ Tauri 2 壳 (Rust) │
│ ┌───────────────────────┐ │
│ │ Vue 3 界面 │ │
│ └──────────┬────────────┘ │
└─────────────┼───────────────┘
│ HTTP REST + WebSocket（实时进度）
┌─────────────▼───────────────┐
│ Python 后端 (sidecar) │
│ FastAPI + Uvicorn │
│ ├─ PyAV 音频/视频引擎 │
│ ├─ Pillow 图片引擎 │
│ └─ WeasyPrint 等文档引擎 │
└─────────────────────────────┘


双进程隔离：UI 崩溃不影响转换任务，后端崩溃可自动重启。

---

## ⚠️ 破坏性变更

- v3.0.0 与 v2.x **不共享任何组件**，请卸载旧版后全新安装
- 系统要求：**Windows 10 及以上 / Ubuntu 22.04 及以上（x86_64）**

---

## 功能

- 🎵 音频转换（mp3 / flac / wav / m4a / ogg 等）
- 🎬 视频转换（容器与编码转换、音轨处理）
- 🖼️ 图片转换（png / jpg / webp / bmp 等）
- 📄 文档转换
- 📊 转换监控：实时精确进度、任务队列、失败重试
- 📜 运行日志：后端日志可视化查看，便于排查问题

## 环境要求（从源码构建）

| 组件 | 版本要求 |
|---|---|
| Node.js + npm | ≥ 18 |
| Rust 工具链（rustup） | stable |
| Python | ≥ 3.10（推荐 conda 独立环境） |
| PyInstaller | 打包 sidecar 用 |

## 快速开始

### 开发运行

bash

1. 后端依赖
cd backend
pip install -r requirements.txt

2. 启动开发模式
cd …/frontend
npm install
npx tauri dev


### 构建安装包

bash

1. 打包 Python 后端为 sidecar
bash backend/build_sidecar.sh # Linux

Windows：在项目根执行脚本中对应的 PyInstaller 命令
#（入口为 backend/sidecar_entry.py，附带 --collect-all av --collect-all PIL

–collect-submodules backend --paths .）
2. 打包桌面应用
cd frontend
npx tauri build

产物：src-tauri/target/release/bundle/nsis/*-setup.exe（Windows）
或 bundle/deb/*.deb（Linux）

## 项目结构

FormatWarp_v3/
├── backend/ # Python 后端（FastAPI + PyAV/Pillow 引擎）
│ ├── sidecar_entry.py # sidecar 入口（绝对导入）
│ ├── app.py # FastAPI 应用
│ ├── engines/ # 各格式转换引擎
│ └── build_sidecar.sh # sidecar 打包脚本
└── frontend/ # Tauri 桌面应用
├── src/ # Vue 3 界面
└── src-tauri/ # Tauri 配置与 Rust 壳


## 许可证

MIT
