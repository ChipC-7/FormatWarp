# 🔄 FormatShift - 全能格式转换工具箱

> 一款基于 Python 开发的跨平台、多功能文件格式转换工具。支持音视频、图片、文档的批量高效转换，界面简洁，开箱即用。

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## ✨ 核心特性

- 🎬 **视频转换**：支持 MP4, AVI, MKV, MOV 等主流视频格式互转，支持提取视频音频。
- 🎵 **音频转换**：支持 MP3, WAV, FLAC, AAC 等格式转换，支持自定义采样率与比特率。
- 🖼️ **图片处理**：支持 JPG, PNG, WEBP, BMP 等图片格式批量转换与基础压缩。
- 📄 **文档转换**：支持常见办公文档、PDF 等格式的相互转换（持续完善中）。
- ⚙️ **自定义设置**：提供可视化设置面板，满足高级用户的定制化转换需求。
- 🚀 **批量处理**：支持多线程/多任务队列，大幅提升转换效率。

## 📸 软件截图

*(待补充：建议在此处插入 1-2 张软件运行时的精美截图)*
<!-- 示例：![主界面](docs/screenshot_main.png) -->

## 🚀 快速开始

### 方式一：下载安装包（推荐普通用户）

请前往 [**Releases 发布页**](https://github.com/ChipC-7/FormatShift/releases) 下载对应操作系统的最新安装包：
- **Linux (Debian/Ubuntu)**: 下载 `.deb` 文件，双击或使用 `sudo dpkg -i FormatShift_x.x.x_amd64.deb` 安装。
- **Windows**: 下载 `.exe` 安装程序。
- **macOS**: 下载 `.dmg` 或 `.pkg` 镜像。

### 方式二：从源码运行（推荐开发者）

如果您想自己修改代码或从源码运行，请按照以下步骤操作：

**1. 克隆本仓库**
```bash
git clone https://github.com/ChipC-7/FormatShift.git
cd FormatShift
2. 创建并激活虚拟环境（推荐）
bash

编辑



python -m venv venv
source venv/bin/activate  # Windows 用户运行: venv\Scripts\activate
3. 安装 Python 依赖
bash

编辑



pip install -r requirements.txt
4. 启动程序
bash

编辑



python main.py
⚠️ 重要前置依赖：FFmpeg
本软件的音视频转换功能深度依赖 FFmpeg。由于 FFmpeg 二进制文件体积较大（>100MB），未包含在源码中。请在运行源码前确保系统已安装 FFmpeg：
Ubuntu / Debian:
bash

编辑



sudo apt update && sudo apt install ffmpeg
macOS (使用 Homebrew):
bash

编辑



brew install ffmpeg
Windows:
请前往 FFmpeg 官网 下载构建包，并将 ffmpeg.exe 所在目录添加到系统的环境变量 PATH 中。
📦 自行打包指南
本项目使用 PyInstaller 进行打包。如需自行构建可执行文件：
bash

编辑



# 确保已安装 pyinstaller
pip install pyinstaller

# 使用项目自带的 spec 文件进行打包
pyinstaller FormatShift.spec
打包完成后，可执行文件将生成在 dist/ 目录下。
🤝 贡献与反馈
如果您在使用过程中遇到 Bug，或者有好的功能建议，欢迎：
提交 Issue
提交 Pull Request
📜 开源协议
本项目基于 MIT License 开源。您可以自由使用、修改和分发本软件。
