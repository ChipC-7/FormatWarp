#!/usr/bin/env bash
# ============================================================
# build_sidecar.sh —— 打包 FormatWarp Python 后端为 Tauri sidecar
#
# 产物：formatwarp-backend-{targetTriple}（Tauri sidecar 命名规范，
#       externalBin 会自动追加 target triple 查找对应文件）
# 输出：复制到 src-tauri/binaries/
#
# 工具选择（默认 PyInstaller，可用 BUILD_TOOL=nuitka 切换）：
#   PyInstaller：对 PyAV/Pillow 等 C 扩展有成熟 hook，三平台行为稳定，
#                 依赖收集可靠，是当前推荐方案；
#   Nuitka：编译为 C，单文件体积更小、启动更快，但对 C 扩展需要逐个
#           排查 include，打包期更长，作为体积优化备选。
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${PROJECT_ROOT}/frontend/src-tauri/binaries"
BUILD_TOOL="${BUILD_TOOL:-pyinstaller}"   # pyinstaller | nuitka
OUT_NAME="formatwarp-backend"

# 目标三元组（Tauri sidecar 命名规范）
TARGET_TRIPLE="$(rustc -vV 2>/dev/null | sed -n 's/^host: //p' || true)"
if [ -z "${TARGET_TRIPLE}" ]; then
  # 兜底：按平台猜测
  case "$(uname -s)" in
    Linux*)  TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
    Darwin*) TARGET_TRIPLE="$(uname -m)-apple-darwin" ;;
    MINGW*|MSYS*|CYGWIN*) TARGET_TRIPLE="x86_64-pc-windows-msvc" ;;
    *) TARGET_TRIPLE="unknown" ;;
  esac
fi
BIN_NAME="${OUT_NAME}-${TARGET_TRIPLE}"

cd "${PROJECT_ROOT}"

echo "==> 目标三元组: ${TARGET_TRIPLE}"
echo "==> 打包工具: ${BUILD_TOOL}"

# 校验依赖
command -v rustc >/dev/null 2>&1 || echo "!! 未检测到 rustc（Tauri 依赖），仅能猜测三元组"
python3 -c "import PySide6" 2>/dev/null || true   # 忽略：不参与打包

case "${BUILD_TOOL}" in
  pyinstaller)
    python3 -c "import PyInstaller" >/dev/null 2>&1 || {
      echo "!! 未安装 pyinstaller，尝试安装…"; pip install --break-system-packages pyinstaller; }
    # 清理旧产物
    rm -rf build dist "${TARGET_DIR}/${BIN_NAME}"
    # --collect-all av / PIL：把 PyAV 与 Pillow 的二进制库与数据一并收集
    # --collect-submodules backend：收集 backend 包（含 engines）
    # 入口用 sidecar_entry.py（绝对导入，绕开 app.py 相对导入在冻结环境的限制）
    python3 -m PyInstaller \
      --onefile \
      --name "${BIN_NAME}" \
      --collect-all av \
      --collect-all PIL \
      --collect-submodules backend \
      --paths "${PROJECT_ROOT}" \
      --noupx \
      backend/sidecar_entry.py
    ;;

  nuitka)
    python3 -c "import nuitka" >/dev/null 2>&1 || {
      echo "!! 未安装 nuitka，尝试安装…"; pip install --break-system-packages nuitka; }
    rm -rf "${TARGET_DIR}/${BIN_NAME}"
    # 入口用 sidecar_entry.py；backend 无静态数据文件，无需 include-data-dir
    python3 -m nuitka \
      --onefile \
      --output-filename="${BIN_NAME}" \
      --include-package=av \
      --include-package=backend \
      --include-package=backend.engines \
      --nofollow-import-to=PySide6 \
      --noinclude-default-mode=nofollow \
      backend/sidecar_entry.py
    # nuitka 产物默认在当前目录，移动到 dist 语义一致
    mkdir -p dist && mv -f "${BIN_NAME}" dist/ 2>/dev/null || true
    ;;

  *)
    echo "!! 未知打包工具：${BUILD_TOOL}（可选 pyinstaller / nuitka）" >&2
    exit 1
    ;;
esac

# 复制到 Tauri binaries/
mkdir -p "${TARGET_DIR}"
if [ -f "dist/${BIN_NAME}" ]; then
  cp -f "dist/${BIN_NAME}" "${TARGET_DIR}/${BIN_NAME}"
  chmod +x "${TARGET_DIR}/${BIN_NAME}"
  SIZE_KB=$(( $(stat -c%s "${TARGET_DIR}/${BIN_NAME}" 2>/dev/null || stat -f%z "${TARGET_DIR}/${BIN_NAME}") / 1024 ))
  echo "==> 产物已就绪: ${TARGET_DIR}/${BIN_NAME} (${SIZE_KB} KB)"
else
  echo "!! 未找到 dist/${BIN_NAME}，打包失败" >&2
  exit 1
fi

echo "==> 完成。后续运行 npm run tauri build 即可把 sidecar 打进安装包。"
