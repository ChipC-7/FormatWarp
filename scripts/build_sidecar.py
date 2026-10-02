#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台打包 Python 后端为 Tauri sidecar（PyInstaller）。

与 build_sidecar.sh 等价，但可在 Windows / macOS / Linux 上运行，
供 GitHub Actions 与本地统一使用。

产物：frontend/src-tauri/binaries/formatwarp-backend-{targetTriple}[.exe]
Tauri externalBin 会按当前编译目标自动追加 triple 查找该文件。

用法：python scripts/build_sidecar.py
"""

import os
import shutil
import subprocess
import sys

OUT_NAME = "formatwarp-backend"


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def target_triple() -> str:
    """获取 Rust 目标三元组（与 Tauri externalBin 后缀一致）。"""
    try:
        out = subprocess.run(
            ["rustc", "-vV"], capture_output=True, text=True, check=False
        ).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    # 兜底映射
    import platform

    system = platform.system()
    machine = platform.machine()
    if system == "Linux":
        return "x86_64-unknown-linux-gnu"
    if system == "Darwin":
        return "arm64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    if system == "Windows":
        return "x86_64-pc-windows-msvc"
    raise RuntimeError(f"无法确定目标三元组：{system}/{machine}")


def ensure_pyinstaller(root: str) -> None:
    try:
        subprocess.run(
            [sys.executable, "-c", "import PyInstaller"],
            check=True, capture_output=True,
        )
    except Exception:
        print("==> 安装 PyInstaller…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], check=True
        )


def ensure_pandoc(root: str) -> str:
    """确保内置 pandoc 存在，返回其文件路径。"""
    exe = ".exe" if sys.platform.startswith("win") else ""
    path = os.path.join(root, "backend", "resources", "pandoc", f"pandoc{exe}")
    if not os.path.isfile(path):
        print("==> 未找到内置 pandoc，执行下载脚本…")
        subprocess.run(
            [sys.executable, os.path.join(root, "scripts", "fetch_pandoc.py")],
            check=True,
        )
    return path


def main() -> None:
    root = project_root()
    triple = target_triple()
    bin_name = f"{OUT_NAME}-{triple}"

    target_dir = os.path.join(root, "frontend", "src-tauri", "binaries")
    os.makedirs(target_dir, exist_ok=True)

    ensure_pyinstaller(root)
    pandoc = ensure_pandoc(root)

    # 清理旧产物
    shutil.rmtree(os.path.join(root, "build"), ignore_errors=True)
    shutil.rmtree(os.path.join(root, "dist"), ignore_errors=True)

    # PyInstaller --add-data 的源:目的（分隔符：win ';'，其他 ':'）
    sep = ";" if os.name == "nt" else ":"
    pandoc_dest = "resources/pandoc"
    add_data = f"{os.path.dirname(pandoc)}{sep}{pandoc_dest}"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", bin_name,
        "--collect-all", "av",
        "--collect-all", "PIL",
        "--collect-submodules", "backend",
        "--add-data", add_data,
        "--paths", root,
        "--noupx",
        os.path.join(root, "backend", "sidecar_entry.py"),
    ]
    print(f"==> 目标三元组: {triple}")
    subprocess.run(cmd, cwd=root, check=True)

    # dist 中产物（Windows 带 .exe）
    produced = None
    dist = os.path.join(root, "dist")
    for name in os.listdir(dist):
        if name.startswith(bin_name):
            produced = os.path.join(dist, name)
            break
    if not produced:
        sys.exit(f"未找到产物 {bin_name}，打包失败")

    final = os.path.join(target_dir, os.path.basename(produced))
    shutil.copyfile(produced, final)
    os.chmod(final, os.stat(final).st_mode | 0o755)
    size_kb = os.path.getsize(final) // 1024
    print(f"==> sidecar 就绪: {final} ({size_kb} KB)")


if __name__ == "__main__":
    main()
