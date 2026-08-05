#!/bin/bash
set -e

PROJECT_DIR="/home/tech/桌面/格式转换器/py版本/FormatWarp"
CONTAINER_NAME="formatwarp-builder"

echo "╔══════════════════════════════════════════════╗"
echo "║  FormatWarp Docker 编译环境                    ║"
echo "║  宿主机: Ubuntu 26.04 (Python 3.14)            ║"
echo "║  容器:   Ubuntu 20.04 (Python 3.9, glibc 2.31) ║"
echo "║  CPU:    24 核全开                              ║"
echo "╚══════════════════════════════════════════════╝"

# 1. 拉取镜像 & 启动容器
echo "▶ [1/6] 拉取 Ubuntu 20.04 镜像..."
sudo docker pull ubuntu:20.04

echo "▶ [2/6] 启动编译容器..."
sudo docker rm -f $CONTAINER_NAME 2>/dev/null || true
sudo docker run -d --name $CONTAINER_NAME -v "$PROJECT_DIR:/app" -w /app ubuntu:20.04 sleep 86400

# 2. 安装系统依赖 + Python 3.9
echo "▶ [3/6] 安装系统依赖和 Python 3.9..."
sudo docker exec $CONTAINER_NAME bash -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq software-properties-common curl wget gnupg
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  apt-get install -y -qq \
    python3.9 python3.9-dev python3.9-distutils python3.9-venv \
    build-essential patchelf ccache \
    zlib1g-dev libffi-dev libssl-dev \
    libglib2.0-0 libgl1 libegl1 libxkbcommon0 \
    libdbus-1-3 libfontconfig1 libfreetype6 \
    libxi6 libxtst6 libxrandr2 libxss1 libxcursor1 \
    libxcomposite1 libxshmfence1 libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 libgbm1 \
    libpango-1.0-0 libcairo2 libstdc++6
  apt-get install -y -qq ruby ruby-dev
  gem install fpm --no-document
  update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
  update-alternatives --set python3 /usr/bin/python3.9
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3.9
'

# 3. 安装 Python 依赖
echo "▶ [4/6] 安装 Python 依赖..."
sudo docker exec $CONTAINER_NAME bash -c '
  python3 -m pip install --upgrade pip
  python3 -m pip install nuitka ordered-set zstandard PySide6
  python3 -m pip install Pillow pillow-heif pillow-avif-plugin
  python3 -m pip install python-docx openpyxl pypdf markdown striprtf
  if [ -f /app/requirements.txt ]; then
    python3 -m pip install -r /app/requirements.txt
  fi
  echo "--- 版本信息 ---"
  python3 --version
  python3 -c "import PySide6; print(f\"PySide6 {PySide6.__version__}\")"
'

# 4. Nuitka 编译 (24核全开)
echo "▶ [5/6] Nuitka 编译开始 (24核全开)..."
sudo docker exec $CONTAINER_NAME bash -c '
  cd /app
  rm -rf build deb_build/FormatWarp_1.0.0_amd64 deb_build/*.deb
  python3 -m nuitka \
    --standalone \
    --enable-plugin=pyside6 \
    --disable-console \
    --output-dir=build \
    --output-filename=FormatWarp \
    --static-libpython=no \
    --nofollow-import-to=pandas,numpy,scipy,PySide6.QtWebEngineWidgets,PySide6.QtWebEngineCore,PySide6.QtQml,PySide6.QtQuick,PySide6.Qt3D,PySide6.QtCharts \
    --follow-imports \
    --jobs=24 \
    --lto=no \
    main.py
  echo "✅ Nuitka 编译完成! 大小: $(du -sh build/FormatWarp.dist | cut -f1)"
'

# 5. 打包 .deb
echo "▶ [6/6] 打包 .deb 文件..."
sudo docker exec $CONTAINER_NAME bash -c '
  cd /app
  DEB_ROOT="deb_build/FormatWarp_1.0.0_amd64"
  APP_DIR="$DEB_ROOT/opt/FormatWarp"
  mkdir -p "$APP_DIR" "$DEB_ROOT/DEBIAN"
  mkdir -p "$DEB_ROOT/usr/share/applications"
  mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps"
  mkdir -p "$DEB_ROOT/usr/local/bin"

  cp -r build/FormatWarp.dist/* "$APP_DIR/"
  cp -r ffmpeg "$APP_DIR/"
  chmod +x "$APP_DIR/ffmpeg/linux-x64/ffmpeg" 2>/dev/null || true
  chmod +x "$APP_DIR/ffmpeg/linux-x64/ffprobe" 2>/dev/null || true
  chmod +x "$APP_DIR/FormatWarp"

  cat > "$DEB_ROOT/DEBIAN/control" << CTRL
Package: formatwarp
Version: 1.0.0
Architecture: amd64
Maintainer: FormatWarp <tech@example.com>
Depends: libglib2.0-0, libgl1, libegl1, libxkbcommon0, libdbus-1-3, libfontconfig1, libfreetype6, libxi6, libxtst6, libxrandr2, libxss1, libxcursor1, libxcomposite1, libxshmfence1, libnss3, libnspr4, libatk1.0-0, libatk-bridge2.0-0, libgtk-3-0, libgbm1, libpango-1.0-0, libcairo2, libstdc++6
Section: utils
Priority: optional
Description: FormatWarp - Universal Format Converter
 A PySide6-based tool for converting audio, video, image, and document formats.
CTRL

  cat > "$DEB_ROOT/usr/share/applications/formatwarp.desktop" << DESK
[Desktop Entry]
Name=FormatWarp
Comment=Universal Format Converter
Exec=/opt/FormatWarp/FormatWarp
Icon=formatwarp
Terminal=false
Type=Application
Categories=AudioVideo;Video;Utility;
DESK

  cat > "$DEB_ROOT/usr/local/bin/formatwarp" << WARP
#!/bin/bash
cd /opt/FormatWarp
exec ./FormatWarp "$@"
WARP
  chmod +x "$DEB_ROOT/usr/local/bin/formatwarp"

  if [ -f images/screenshot1.png ]; then
    cp images/screenshot1.png "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps/formatwarp.png"
  fi

  chmod -R 755 "$DEB_ROOT"
  cd deb_build
  dpkg-deb --build --root-owner-gid FormatWarp_1.0.0_amd64
  echo "✅ .deb 打包完成! 大小: $(du -sh FormatWarp_1.0.0_amd64.deb | cut -f1)"
'

# 6. 清理容器
sudo docker rm -f $CONTAINER_NAME
echo "🎉 全部完成! .deb 位于: deb_build/FormatWarp_1.0.0_amd64.deb"

