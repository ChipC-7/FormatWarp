# FormatWarp 打包手册（PACKAGING）

前端 Tauri 2 + Vue3 + NaiveUI；后端 Python FastAPI + PyAV，以 **sidecar** 方式随应用分发。
应用退出时由 Rust 壳 kill 后端子进程，并用 pid 文件兜底清理孤儿进程。

---

## 0. 目录角色速览

| 路径 | 角色 |
|---|---|
| `backend/app.py` | FastAPI 入口（端口自动重试，stdout 输出 `FORMATWARP_PORT=xxxx`） |
| `backend/sidecar_entry.py` | **打包入口**：绝对导入 `backend.app.main`，绕开 app.py 相对导入在冻结环境失效的问题 |
| `backend/build_sidecar.sh` | 把后端打成 Tauri sidecar，产物 → `src-tauri/binaries/` |
| `frontend/src-tauri/` | Rust 壳（setup 钩子 spawn sidecar / dev uvicorn） |
| `frontend/` | Vue 前端（`npm run build` 产出 `dist/`） |

---

## 1. 一次性环境准备

```bash
# Node LTS + Rust
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt install -y nodejs
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Linux 系统依赖（Tauri 2）
sudo apt install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev

# 前端依赖
cd frontend && npm install

# Python 后端依赖（打包机）
pip install -r backend/requirements.txt
pip install pyinstaller        # 或 pip install nuitka
```

---

## 2. 打包 sidecar

```bash
bash backend/build_sidecar.sh            # 默认 PyInstaller
BUILD_TOOL=nuitka bash backend/build_sidecar.sh   # 可选 Nuitka
```

产物：`src-tauri/binaries/formatwarp-backend-<targetTriple>`，如
`x86_64-unknown-linux-gnu` / `aarch64-apple-darwin` / `x86_64-pc-windows-msvc.exe`。

**工具选择理由**
- 默认 **PyInstaller**：对 PyAV/Pillow 这类 C 扩展有成熟 hook，`--collect-all av/PIL`
  能可靠收集二进制库与数据；三平台行为一致，出错率低。
- 备选 **Nuitka**：单文件体积更小、启动更快（编译为 C），但 C 扩展需要逐个
  `--include-package` 排查、编译期长；作为体积优化手段。
- 切换方式：`BUILD_TOOL=nuitka` 环境变量（脚本已内置两套命令）。

---

## 3. 构建桌面安装包

`tauri.conf.json` 已配置：
- `beforeBuildCommand = "npm run build && bash ../backend/build_sidecar.sh"`（先出前端 + sidecar）
- `bundle.externalBin = ["binaries/formatwarp-backend"]`（Tauri 自动追加 target triple 找文件）

### Linux（Ubuntu 22.04 验证）
```bash
cd frontend
# .deb
npm run tauri build -- --bundles deb
# AppImage
npm run tauri build -- --bundles appimage
# 一次全出
npm run tauri build
```
产物：`src-tauri/target/release/bundle/deb/*.deb`、`.../appimage/*.AppImage`

### Windows（nsis / msi）
```powershell
cd frontend
npm run tauri build -- --bundles nsis      # .exe 安装器
npm run tauri build -- --bundles msi       # .msi
```
产物：`src-tauri\target\release\bundle\nsis\*.exe`、`...\msi\*.msi`

### macOS（.dmg）
```bash
cd frontend
npm run tauri build -- --bundles dmg
```
产物：`src-tauri/target/release/bundle/dmg/*.dmg`
> ⚠️ 未签名/未公证的 dmg 首次打开会被 Gatekeeper 拦截，需右键“打开”或
> `xattr -dr com.apple.quarantine 格式跃迁.app`；正式发布请配置签名。

---

## 4. 体积预期与瘦身（目标 < 80MB）

预期构成（安装包口径）：
- 前端静态资源（Vue/NaiveUI 打包后）≈ 2–4 MB
- Rust 壳 + WebView 壳 ≈ 15–25 MB
- **后端 sidecar（PyAV 内置完整 FFmpeg）≈ 30–60 MB** ← 主要体积来源

**瘦身手段（按需叠加）**
1. **UPX 压缩 sidecar 二进制**（PyInstaller 支持 `--upx-dir`，脚本默认 `--noupx`
   便于调试；发布时去掉 `--noupx` 并安装 upx 可压 ~40–50%）。
2. **裁剪 PyAV 内置 codecs**：PyAV wheel 内置完整 FFmpeg。若只需音视频常见格式，
   可改用自编译的瘦身 FFmpeg 构建，把不需要的编解码器（如少见 muxer/encoder）剔除。
3. **压缩图标/资源**：`.AppImage` 用 `APPIMAGE_COMPRESS=xz` 压缩。
4. **排除无用的文档引擎可选依赖**：backend/requirements.txt 中 doc 模块的可选库
   （pdf2docx 等）不安装即不进 sidecar。

---

## 5. Dev 模式两种方案（取舍说明）

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **Rust dev 自动拉起（本项目采用）** | `npm run tauri dev`，Rust setup 钩子自动 `python3 -m uvicorn backend.app:app --port 8765`（从项目根） | 一条命令；后端代码热重载（uvicorn --reload 可加） | 依赖本机 python3/uvicorn 环境 |
| dev:full 一键双开（Linux/macOS bash） | `npm run dev:full`（后台 uvicorn + `tauri dev` 并行；Windows 请手动开两终端） | 一条命令起两个进程 | bash 语法，Windows 需手动两终端 |

> 浏览器纯前端调试（不含 Tauri）：开两个终端，一个起 uvicorn，一个 `npm run dev`
> （Vite 1420 端口），前端 `invoke` 失败自动回退 `127.0.0.1:8765` 直连。
> 首次 `npm run tauri dev` 前需执行一次 `bash backend/build_sidecar.sh`
> （dev 下实际运行系统 python3，sidecar 文件仅用于满足 Tauri 对 externalBin 的构建校验）。

---

## 6. sidecar 生命周期

- **启动**：Rust `setup` 钩子 spawn sidecar，后台线程排空 stdout 并解析
  `FORMATWARP_PORT=xxxx` 写入 `BackendState.port`；前端 `invoke("get_backend_port")` 读取。
- **端口重试**：后端 8765 被占则自动 +1（最多 5 次），实际端口经 stdout 上报，前端无感。
- **退出**：`RunEvent::Exit` 中 `child.kill()` + 删除 pid 文件。
- **孤儿兜底**：pid 文件存于系统临时目录 `formatwarp-backend.pid`，下次启动先清理残留。
