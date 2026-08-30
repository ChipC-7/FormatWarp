# FormatWarp 验收清单（ACCEPTANCE）

按平台逐项勾选。每个平台完成「启动 → 转换 → 监控 → 日志 → 设置 → 退出」主链路后，
再核对进程生命周期与异常场景。

前置：`bash backend/build_sidecar.sh && npm run tauri build`（各平台产物见 PACKAGING.md）。

---

## 1. 主功能链路（三平台通用）

### 启动
- [ ] 安装包安装后从桌面/开始菜单启动，出现「格式跃迁」窗口（1200×800）
- [ ] 左侧 7 个导航项：🎵音频 / 🎬视频 / 🖼️图片 / 📄文档 / 📊监控 / 📋日志 / ⚙️设置
- [ ] 无「后端未连接」黄条；状态栏/日志页显示 PyAV 已就绪 + 版本号

### 转换（音频页为例）
- [ ] 点「添加文件」选 2 个 mp3 → 列表显示文件名与大小
- [ ] 输出选 FLAC → 开始转换 → 提示「已提交 2 个任务」，底部聚合进度推进
- [ ] 转换中「开始」禁用、「停止」启用；完成后恢复
- [ ] 输出目录出现 `a.flac`/`b.flac`（无重名冲突）

### 监控
- [ ] 转换中切到监控页：「正在转换 N 个文件…」+ 活跃任务卡进度实时更新
- [ ] 完成后成功栏出现条目（悬停可看完整消息），总进度 100%

### 日志
- [ ] 日志页出现彩色的 info（灰）/ success（青）行；引擎状态卡显示版本与 GPU 列表

### 设置
- [ ] 切 ☀️亮色 → 全局即时变亮并持久化；切回 🌙
- [ ] 并行数改 5 + 超时改 10 → 保存 → message.success「设置已保存并生效」

### 退出
- [ ] 关闭主窗口，应用与后端进程均退出（见 §2）

---

## 2. 进程生命周期

### Linux
```bash
# 启动后
ps aux | grep -E "formatwarp-backend|uvicorn backend"
# 退出应用后（应无输出）
ps aux | grep -E "formatwarp-backend|uvicorn backend" | grep -v grep
```

### Windows
```powershell
# 启动后
tasklist | findstr /i "formatwarp-backend python"
# 退出后（应无输出）
tasklist | findstr /i "formatwarp-backend python"
```

### macOS
```bash
# 启动后
ps aux | grep -E "formatwarp-backend|uvicorn backend"
# 退出后（应无输出）
ps aux | grep -E "formatwarp-backend|uvicorn backend" | grep -v grep
```

- [ ] 退出后 sidecar / uvicorn 进程已消失
- [ ] 再次启动应用，`formatwarp-backend.pid`（系统临时目录）已被重建且无残留进程

---

## 3. 异常场景

### 磁盘空间不足
- [ ] 转换进行中写盘失败 → 任务进入失败栏，消息含明确错误；应用不崩溃
- [ ] 顶部/设置页磁盘剩余显示很小或为 0

### 端口被占
- [ ] 手动先占用 8765（如 `python3 -m http.server 8765`）再启动应用
- [ ] 后端自动 +1 到可用端口，前端通过 `FORMATWARP_PORT` 拿到实际端口，功能正常

### 后端崩溃
- [ ] 转换中手动 kill 后端进程（`kill <pid>` / `taskkill /pid <pid> /f`）
- [ ] 前端顶部出现黄色「后端未连接，3 秒后自动重试…」
- [ ] 恢复后端（重新 `python3 -m uvicorn backend.app:app --port 8765`）后黄条消失，功能恢复

---

## 4. 打包产物核对

- [ ] `.deb` / `.AppImage`（Linux）可安装/可执行，双击运行正常
- [ ] `.msi` / `.exe`（Windows）安装后侧载 sidecar 正常
- [ ] `.dmg`（macOS）可运行（未签名需右键打开）
- [ ] 安装包总体积 < 80MB（超出按 PACKAGING.md §4 瘦身）
