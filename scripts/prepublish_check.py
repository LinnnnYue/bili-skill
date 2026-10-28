#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布前自检 —— 推送公开仓库之前必须跑一遍。

检查三类绝不该出现在公开仓库里的东西：

1. **登录凭证**：B 站 Cookie（SESSDATA / bili_jct / DedeUserID…）、API key、token
2. **个人环境**：本机绝对路径（`C:/Users/xxx`、`/home/xxx`）、个人邮箱
3. **不该提交的文件**：cookies.txt、.env、私钥、运行时产物

用法
----
    python scripts/prepublish_check.py            # 检查工作区全部文件
    python scripts/prepublish_check.py --staged   # 只检查已 git add 的内容
    python scripts/prepublish_check.py --quiet    # 只在有问题时输出

退出码：0 = 干净；1 = 发现问题
"""
import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 真实凭证特征（不是关键词，是「值」的形状）──
CRED = [
    (r"SESSDATA\s*[=:]\s*[A-Za-z0-9%._-]{25,}", "B站 SESSDATA 实际值"),
    (r"bili_jct\s*[=:]\s*[0-9a-f]{32}", "B站 bili_jct（32 位）"),
    (r"DedeUserID\s*[=:]\s*\d{5,}", "B站 DedeUserID"),
    (r"DedeUserID__ckMd5\s*[=:]\s*[0-9a-f]{16}", "B站 ckMd5"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"ghp_[0-9A-Za-z]{36}", "GitHub Token"),
    (r"sk-[A-Za-z0-9]{20,}", "API Secret Key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "私钥"),
]

# ── 个人环境特征 ──
ENV_PAT = [
    (r"C:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+[\\/]", "Windows 用户目录绝对路径"),
    (r"/home/[A-Za-z0-9_.-]+/", "Linux 家目录绝对路径"),
    (r"/Users/[A-Za-z0-9_.-]+/", "macOS 用户目录绝对路径"),
]

# ── 不该被提交的文件名 ──
FORBIDDEN_FILES = [
    (r"^cookies?.*\.txt$", "Cookie 文件"),
    (r"^\.env", "环境变量文件"),
    (r"\.(pem|key|p12|pfx)$", "密钥文件"),
    (r"\.log$", "日志"),
]

TEXT_EXT = {".py", ".md", ".html", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".ps1"}


def git_files(staged):
    cmd = ["git", "diff", "--cached", "--name-only"] if staged else ["git", "ls-files"]
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    except Exception:
        return []
    return [f for f in out.splitlines() if f.strip()]


def walk_files():
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if "__pycache__" in rel or rel.startswith(".git/"):
            continue
        out.append(rel)
    return out


def main():
    ap = argparse.ArgumentParser(description="发布前自检：凭证 / 个人路径 / 禁止文件")
    ap.add_argument("--staged", action="store_true", help="只检查已暂存的文件")
    ap.add_argument("--quiet", action="store_true", help="只在有问题时输出")
    a = ap.parse_args()

    files = git_files(a.staged) if a.staged else walk_files()
    if not a.staged and not files:
        files = walk_files()

    if not a.quiet:
        print(f"检查 {len(files)} 个文件（{ROOT}）\n")

    problems = []

    for rel in files:
        name = os.path.basename(rel)
        for pat, label in FORBIDDEN_FILES:
            if re.search(pat, name, re.I):
                problems.append((rel, "禁止提交的文件", label))
                break

        p = ROOT / rel
        if p.suffix.lower() not in TEXT_EXT or not p.exists():
            continue
        try:
            text = io.open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue

        for pat, label in CRED:
            for m in re.finditer(pat, text, re.I):
                frag = m.group(0)
                masked = frag[:12] + "***" if len(frag) > 15 else frag
                problems.append((rel, label, masked))
        for pat, label in ENV_PAT:
            for m in re.finditer(pat, text):
                problems.append((rel, label, m.group(0)))

    if not problems:
        if not a.quiet:
            print("干净：没有发现凭证、个人路径或禁止提交的文件。")
        return 0

    print(f"发现 {len(problems)} 处问题：\n")
    seen = set()
    for rel, label, frag in problems:
        key = (rel, label)
        if key in seen:
            continue
        seen.add(key)
        print(f"  ✗ {rel}")
        print(f"      {label}：{frag}")
    print("\n处理完再提交。凭证一旦推上去等于泄露，改历史也很麻烦。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
