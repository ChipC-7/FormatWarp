# 从源码到安装包 · 一页纸手册

> 目标：Ubuntu 22.04 上一条命令链产出 `.deb` / `.AppImage`；Windows / macOS 命令见底部。

## 1. 装环境（一次性）

```bash
# Node + Rust + Tauri Linux 依赖
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt install -y nodejs
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
sudo apt install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
# 前端 + 后端依赖
cd frontend && npm install
pip install -r backend/requirements.txt pyinstaller
```

## 2. 出包（核心三步）

```bash
# ① 前端（vue-tsc + vite → dist/）
cd frontend && npm run build
# ② 后端 sidecar（PyInstaller → src-tauri/binaries/formatwarp-backend-<triple>）
bash ../backend/build_sidecar.sh
# ③ 桌面安装包（Tauri 自动带上 sidecar）
npm run tauri build                    # Linux: deb+AppImage 一次出
npm run tauri build -- --bundles deb   # 只要 deb
npm run tauri build -- --bundles appimage
```

> `npm run tauri build` 的 beforeBuildCommand 会自动执行 ① 和 ②，
> 日常直接跑 ③ 即可；② 也可单独跑以调试 sidecar。

## 3. 产物位置

| 平台 | 产物 |
|---|---|
| Linux | `src-tauri/target/release/bundle/deb/*.deb`、`.../appimage/*.AppImage` |
| Windows | `npm run tauri build -- --bundles nsis` → `...\nsis\*.exe`；`--bundles msi` → `...\msi\*.msi` |
| macOS  | `npm run tauri build -- --bundles dmg` → `.../dmg/*.dmg`（未签名需右键打开） |

## 4. 常见问题速查

- **体积超 80MB** → 见 `docs/PACKAGING.md` §4（UPX 压缩 / 裁剪 PyAV codecs）
- **`externalBin` 找不到 sidecar** → 未跑 `backend/build_sidecar.sh`，先执行
- **dev 想用系统 python3 热重载** → `npm run tauri dev`（Rust 自动拉起 uvicorn）
- **退出后后端进程残留** → 见 `docs/ACCEPTANCE.md` §2（pid 文件兜底，下轮启动自动清理）

> 完整细节：`docs/PACKAGING.md`（打包）· `docs/ACCEPTANCE.md`（验收）
