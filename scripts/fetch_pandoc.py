#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载并内置 pandoc 官方预编译二进制（用户无需自行安装）。

产物：backend/resources/pandoc/pandoc[.exe]

用法：
  python3 scripts/fetch_pandoc.py            # 当前平台
  python3 scripts/fetch_pandoc.py --force    # 强制重新下载
  python3 scripts/fetch_pandoc.py --version 3.12

仅依赖标准库；下载源为 pandoc 官方 GitHub Release。
"""

import argparse
import io
import os
import platform
import stat
import sys
import tarfile
import urllib.request
import zipfile

# Windows 默认控制台可能是 cp1252，脚本含中文输出，强制 UTF-8 防崩溃
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PANDOC_VERSION = "3.12"
URL_TMPL = (
    "https://github.com/jgm/pandoc/releases/download/"
    "{ver}/pandoc-{ver}-{asset}"
)

# (system, machine) -> release 资源名片段
ASSETS = {
    ("Linux", "x86_64"): "linux-amd64.tar.gz",
    ("Linux", "aarch64"): "linux-arm64.tar.gz",
    ("Darwin", "x86_64"): "x86_64-macOS.zip",
    ("Darwin", "arm64"): "arm64-macOS.zip",
    ("Windows", "AMD64"): "windows-x86_64.zip",
}


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def target_dir() -> str:
    return os.path.join(project_root(), "backend", "resources", "pandoc")


def target_binary() -> str:
    exe = ".exe" if platform.system() == "Windows" else ""
    return os.path.join(target_dir(), f"pandoc{exe}")


def pick_asset() -> str:
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)
    asset = ASSETS.get(key)
    if not asset:
        sys.exit(f"不支持的平台：{system}/{machine}，可手动下载 pandoc")
    return asset


def download(url: str) -> bytes:
    print(f"下载：{url}")
    req = urllib.request.Request(url, headers={"User-Agent": "FormatWarp-fetch"})
    with urllib.request.urlopen(req) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        buf = io.BytesIO()
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {done/1e6:.1f}/{total/1e6:.1f} MB ({pct}%)", end="")
        print()
        return buf.getvalue()


def extract_member(data: bytes, asset: str) -> bytes:
    """从归档中取出 pandoc 二进制内容。"""
    wanted = "pandoc.exe" if asset.endswith(".zip") and "windows" in asset else "pandoc"
    if asset.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf.getmembers():
                base = os.path.basename(m.name)
                if base == wanted and m.isfile():
                    f = tf.extractfile(m)
                    return f.read()
    elif asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if os.path.basename(name) == wanted:
                    return zf.read(name)
    sys.exit("归档中未找到 pandoc 二进制")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=PANDOC_VERSION)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = target_binary()
    if os.path.isfile(out) and not args.force:
        print(f"pandoc 已存在：{out}（--force 可重下）")
        return

    asset = pick_asset()
    url = URL_TMPL.format(ver=args.version, asset=asset)
    data = download(url)
    binary = extract_member(data, asset)

    os.makedirs(target_dir(), exist_ok=True)
    with open(out, "wb") as f:
        f.write(binary)
    # 可执行权限
    os.chmod(out, os.stat(out).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"就绪：{out}（{len(binary)/1e6:.1f} MB，pandoc {args.version}）")


if __name__ == "__main__":
    main()
