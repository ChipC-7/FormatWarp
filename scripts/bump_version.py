#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键同步 FormatWarp 全部版本号（杜绝漏改）。

版本号分散在 7 个文件，手动改极易遗漏，本脚本一次全部更新：

  1. backend/app.py                         APP_VERSION
  2. frontend/src-tauri/tauri.conf.json     "version"
  3. frontend/package.json                  "version"
  4. frontend/package-lock.json             顶层 + packages[""]
  5. frontend/src-tauri/Cargo.toml          [package] version
  6. frontend/src-tauri/Cargo.lock          name="frontend" 的 version
  7. frontend/src/stores/engine.ts          兜底默认版本

用法：
  python scripts/bump_version.py 3.2.0      # 直接指定版本
  python scripts/bump_version.py --patch    # 3.1.1 -> 3.1.2
  python scripts/bump_version.py --minor    # 3.1.1 -> 3.2.0
  python scripts/bump_version.py --major    # 3.1.1 -> 4.0.0
  python scripts/bump_version.py 3.2.0 --dry-run   # 只看不改

只改版本字段，不动其他内容。
"""

import argparse
import os
import re
import sys

# Windows 控制台兼容
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# (相对路径, 匹配正则, 替换模板用 {v})
# 每条规则独立替换；package-lock 两处由同一正则 multiline 一次覆盖。
RULES = [
    (
        "backend/app.py",
        re.compile(r'(APP_VERSION\s*=\s*")[0-9.]+(")'),
    ),
    (
        "frontend/src-tauri/tauri.conf.json",
        re.compile(r'("version"\s*:\s*")[0-9.]+(")'),
    ),
    (
        "frontend/package.json",
        re.compile(r'("version"\s*:\s*")[0-9.]+(")'),
    ),
    # 只改两处：根级 version（恰好 2 空格）和 packages[""] 空包名块的
    # version（以 `    "": {` 精确定位）。不能按缩进匹配——lockfile v3 中
    # 每个依赖包的 version 也都是 6 空格缩进，按缩进会误改全部依赖。
    (
        "frontend/package-lock.json",
        re.compile(
            r'(?m)^(  "version"\s*:\s*"'
            r'|    "":\s*\{\n(?:[^\n]*\n)*?      "version"\s*:\s*")[0-9.]+(")'
        ),
    ),
    # Cargo.toml [package] 节：行首无缩进的 version
    (
        "frontend/src-tauri/Cargo.toml",
        re.compile(r'(?m)^(version\s*=\s*")[0-9.]+(")'),
    ),
    # Cargo.lock：仅本应用 "frontend" 包块内的 version（下一行）
    (
        "frontend/src-tauri/Cargo.lock",
        re.compile(r'(name\s*=\s*"frontend"\nversion\s*=\s*")[0-9.]+(")'),
    ),
    (
        "frontend/src/stores/engine.ts",
        re.compile(r'(const\s+version\s*=\s*ref\(")[0-9.]+(")'),
    ),
]


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def current_version(root: str) -> str:
    """以 backend/app.py 的 APP_VERSION 作为当前版本权威来源。"""
    path = os.path.join(root, "backend", "app.py")
    text = open(path, encoding="utf-8").read()
    m = re.search(r'APP_VERSION\s*=\s*"([0-9.]+)"', text)
    if not m:
        sys.exit("无法从 backend/app.py 读取当前版本")
    return m.group(1)


def bump(ver: str, part: str) -> str:
    m = SEMVER_RE.match(ver)
    if not m:
        sys.exit(f"当前版本不符合 semver：{ver}")
    major, minor, patch = (int(x) for x in m.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    ap = argparse.ArgumentParser(description="同步 FormatWarp 全部版本号")
    ap.add_argument("version", nargs="?", help="目标版本，如 3.2.0")
    ap.add_argument("--major", action="store_true", help="主版本号 +1")
    ap.add_argument("--minor", action="store_true", help="次版本号 +1")
    ap.add_argument("--patch", action="store_true", help="修订号 +1（默认）")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做的修改")
    args = ap.parse_args()

    root = project_root()
    old = current_version(root)

    # 确定目标版本
    selected = [b for b in ("major", "minor", "patch") if getattr(args, b)]
    if len(selected) > 1:
        sys.exit("--major/--minor/--patch 只能选一个")
    if args.version:
        new = args.version
    elif selected:
        new = bump(old, selected[0])
    else:
        new = bump(old, "patch")  # 默认递增修订号

    if not SEMVER_RE.match(new):
        sys.exit(f"版本号格式错误：{new}（应为 主.次.修订，如 3.2.0）")

    print(f"版本：{old}  ->  {new}")
    if old == new:
        print("（目标版本与当前一致，文件内容无需变化）")

    changed_files = 0
    for rel, pattern in RULES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            print(f"  × 跳过（文件不存在）：{rel}")
            continue
        text = open(path, encoding="utf-8").read()
        new_text, count = pattern.subn(rf"\g<1>{new}\g<2>", text)
        if count == 0:
            print(f"  × 未匹配到版本字段：{rel}（请检查规则）")
            continue
        wrote = False
        if not args.dry_run and new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            wrote = True
        if args.dry_run:
            mark = "dry"
        elif wrote:
            mark = "✓"
        else:
            mark = "="  # 内容未变（版本相同）
        print(f"  {mark} {rel}（{count} 处）")
        changed_files += 1

    print(f"\n共处理 {changed_files} 个文件" + ("（dry-run，未写入）" if args.dry_run else ""))
    if not args.dry_run and changed_files and old != new:
        print("下一步：提交改动，然后打标签并推送：")
        print(f"  git add . && git commit -m 'chore: 版本升级至 {new}'")
        print(f"  git tag v{new} && git push origin main --tags")


if __name__ == "__main__":
    main()
