#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描知识库目录，生成含效力状态的全量清单 Markdown。

列：分类 | 文件名 | 相对路径 | 效力状态 | 版本/生效日期 | 来源 | 备注

用法：
    python kb_inventory.py <知识库根目录> [-o 输出文件] [--no-ignore] [--exts .pdf,.txt]

法律知识库的清单必须带效力状态和版本，否则无法判断某条引用是否现行有效。
「效力状态」「版本/生效日期」优先从目录名和文件名解析；解析不到时留空并提示人工补，
不要猜——猜错比空着更危险。

只读，不修改知识库内容。仅使用标准库，不访问网络。

自检：
    python kb_inventory.py --selfcheck
"""

import argparse
import os
import re
import sys

# 默认忽略的目录名（小写比较）
DEFAULT_IGNORE_DIRS = {
    "__pycache__", "node_modules", ".git", ".svn", ".idea", ".vscode",
    "dist", "build", ".obsolete",
}

# 默认忽略的文件名
DEFAULT_IGNORE_FILES = {
    "desktop.ini", "thumbs.db", ".ds_store",
}

# 目录名 -> 效力状态（法律库专用）
DIR_STATUS = {
    "_现行有效": "现行有效",
    "_已废止": "已废止",
    "_新旧对照": "对照资料",
    "_待核实": "待核实",
}

# 文件名里的效力标记
STATUS_PATTERNS = [
    ("现行有效", "现行有效"),
    ("已废止", "已废止"),
    ("已失效", "已废止"),
    ("历史版本", "已废止"),
    ("待核实", "待核实"),
]

# 版本：2023修订 / 2017修正 / 1999通过
VERSION_RE = re.compile(r"((?:19|20)\d{2})\s*(修订|修正|通过|版)")

# 生效日期：2024-01-01施行 / 2024年1月1日起施行
# 年份必须整体捕获：(19|20)\d{2} 会把年份截成「20」，年份部分用 (?:19|20)\d{2} 非捕获
EFFECTIVE_RE = re.compile(
    r"((?:19|20)\d{2})[-年/](\d{1,2})[-月/](\d{1,2})\s*日?\s*(?:起)?\s*(施行|生效|执行)"
)

# 表头（顺序即列序）
COLUMNS = ["分类", "文件名", "相对路径", "效力状态", "版本/生效日期", "来源", "备注"]


def normalize_exts(raw):
    """把 '.pdf,.TXT' 解析成 {'pdf','txt'}；None 表示不限制。"""
    if not raw:
        return None
    out = set()
    for part in raw.split(","):
        part = part.strip().lower().lstrip(".")
        if part:
            out.add(part)
    return out or None


def should_skip_dir(name, ignore_dirs):
    low = name.lower()
    if low in ignore_dirs:
        return True
    return low.startswith(".") and low not in (".", "..")


def parse_status(path_rel):
    """从相对路径和文件名推断效力状态。找不到返回空串。

    顺序：目录名（_现行有效 等）优先于文件名标记——
    因为目录是人工归置的，比文件名里的关键词更可信。
    """
    for part in path_rel.split("/"):
        if part in DIR_STATUS:
            return DIR_STATUS[part]

    name = path_rel.rsplit("/", 1)[-1]
    for kw, val in STATUS_PATTERNS:
        if kw in name:
            return val
    return ""


def parse_version_effective(path_rel):
    """从文件名解析版本与生效日期，拼成 '2023修订；2024-01-01施行'。

    解析不到返回空串。绝不猜测。
    """
    name = path_rel.rsplit("/", 1)[-1]
    parts = []

    m = VERSION_RE.search(name)
    if m:
        parts.append(m.group(0))

    m2 = EFFECTIVE_RE.search(name)
    if m2:
        y, mo, d, tail = m2.group(1), m2.group(2), m2.group(3), m2.group(4)
        parts.append("%s-%02d-%02d%s" % (y, int(mo), int(d), tail))

    return "；".join(parts)


def collect(root, ignore_dirs, ignore_files, exts):
    """遍历 root，返回按相对路径排序的记录列表。"""
    root = os.path.abspath(root)
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not should_skip_dir(d, ignore_dirs)
        )
        for fn in filenames:
            if fn.lower() in ignore_files:
                continue
            ext = os.path.splitext(fn)[1].lower().lstrip(".")
            if exts and ext not in exts:
                continue
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            parts = rel.split("/")
            category = parts[0] if len(parts) > 1 else "(根目录)"
            rows.append({
                "分类": category,
                "文件名": fn,
                "相对路径": rel,
                "效力状态": parse_status(rel),
                "版本/生效日期": parse_version_effective(rel),
                "来源": "",
                "备注": "",
            })
    rows.sort(key=lambda r: (r["分类"], r["相对路径"]))
    return rows


def render(root, rows):
    """渲染成 Markdown 表格。"""
    root_display = os.path.abspath(root).replace(os.sep, "/")
    lines = []
    lines.append("# 知识库全量清单")
    lines.append("")
    lines.append("- 根目录：`%s`" % root_display)
    lines.append("- 文件总数：%d" % len(rows))

    blanks = sum(1 for r in rows if not r["效力状态"])
    if blanks:
        lines.append("- ⚠ 效力状态待补充：%d 个" % blanks)
    lines.append("")
    lines.append("| " + " | ".join(COLUMNS) + " |")
    lines.append("|---|" * len(COLUMNS))
    for r in rows:
        cells = []
        for col in COLUMNS:
            v = (r.get(col) or "").replace("|", "\\|")
            cells.append(v if v else "　")   # 全角空格占位，比空单元格醒目
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("> 「效力状态」「来源」两列请人工补齐，不要留空——"
                 "留空等于没有，猜错比空着更危险。")
    lines.append("")
    return "\n".join(lines)


def cmd_selfcheck(_args):
    """解析逻辑与渲染的断言。"""
    checks = []

    # 效力状态：目录优先
    checks.append(("_现行有效 目录 -> 现行有效",
                   parse_status("01_法律规范/_现行有效/法律/a.pdf") == "现行有效"))
    checks.append(("_已废止 目录 -> 已废止",
                   parse_status("01_法律规范/_已废止/法律/a.pdf") == "已废止"))
    checks.append(("_新旧对照 目录 -> 对照资料",
                   parse_status("01_法律规范/_新旧对照/a.md") == "对照资料"))
    checks.append(("目录优先于文件名标记",
                   parse_status("01_法律规范/_已废止/法律/a_现行有效.pdf") == "已废止"))
    # 文件名标记（无特殊目录）
    checks.append(("文件名含现行有效",
                   parse_status("法律/行政处罚法_现行有效.pdf") == "现行有效"))
    checks.append(("文件名含已废止",
                   parse_status("法律/行政处罚法_已废止.pdf") == "已废止"))
    checks.append(("文件名含历史版本",
                   parse_status("法律/x_历史版本.pdf") == "已废止"))
    checks.append(("无标记返回空串",
                   parse_status("法律/行政处罚法.pdf") == ""))
    checks.append(("待核实可识别",
                   parse_status("法律/x_待核实.pdf") == "待核实"))

    # 版本与生效日期
    checks.append(("解析 2023修订",
                   "2023修订" in parse_version_effective("法_2023修订.pdf")))
    checks.append(("解析施行日期",
                   "2024-01-01施行" in parse_version_effective(
                       "法_2023修订_2024-01-01施行_现行有效.pdf")))
    checks.append(("版本与生效日期合并",
                   parse_version_effective("法_2023修订_2024-01-01施行.pdf")
                   == "2023修订；2024-01-01施行"))
    checks.append(("中文日期也能解析",
                   "2024-01-01施行" in parse_version_effective("法_2024年1月1日施行.pdf")))
    checks.append(("无版本信息返回空串",
                   parse_version_effective("法.pdf") == ""))
    checks.append(("解析 1999通过",
                   "1999通过" in parse_version_effective("法_1999通过.pdf")))

    # 端到端
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "01_法律规范", "_现行有效", "法律"))
        os.makedirs(os.path.join(td, "01_法律规范", "_已废止"))
        f1 = os.path.join(td, "01_法律规范", "_现行有效", "法律",
                          "中华人民共和国行政复议法_2023修订_2024-01-01施行_现行有效.pdf")
        f2 = os.path.join(td, "01_法律规范", "_已废止",
                          "中华人民共和国行政复议法_1999通过_2017修正_已废止.pdf")
        for p in (f1, f2):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x")

        rows = collect(td, DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_FILES, None)
        checks.append(("收集到 2 个文件", len(rows) == 2))
        by_rel = {r["相对路径"]: r for r in rows}

        r1 = by_rel["01_法律规范/_现行有效/法律/"
                    "中华人民共和国行政复议法_2023修订_2024-01-01施行_现行有效.pdf"]
        checks.append(("现行版状态正确", r1["效力状态"] == "现行有效"))
        checks.append(("现行版版本正确", "2024-01-01施行" in r1["版本/生效日期"]))
        checks.append(("分类取第一层目录", r1["分类"] == "01_法律规范"))

        r2 = by_rel["01_法律规范/_已废止/"
                    "中华人民共和国行政复议法_1999通过_2017修正_已废止.pdf"]
        checks.append(("废止版状态正确", r2["效力状态"] == "已废止"))
        checks.append(("废止版解析出 1999通过",
                       "1999通过" in r2["版本/生效日期"]))

        checks.append(("七列齐全", len(COLUMNS) == 7))
        checks.append(("每条记录七字段", all(len(r) == 7 for r in rows)))
        checks.append(("来源默认为空", all(r["来源"] == "" for r in rows)))

        md = render(td, rows)
        checks.append(("表头为七列",
                       "| " + " | ".join(COLUMNS) + " |" in md))
        checks.append(("分隔行七段", "|---|" * 7 in md))
        checks.append(("空值用占位符而非真空", "　" in md))
        checks.append(("提示人工补齐", "请人工补齐" in md))
        checks.append(("以竖线开头的行数 = 文件数 + 1（表头）",
                       len([ln for ln in md.splitlines()
                            if ln.startswith("| ") and not ln.startswith("|---")])
                       == len(rows) + 1))

        # 竖线转义不破坏列数
        tricky = [{
            "分类": "案例|库", "文件名": "a.txt", "相对路径": "案例|库/a.txt",
            "效力状态": "", "版本/生效日期": "", "来源": "", "备注": "",
        }]
        md_t = render(td, tricky)
        bad = []
        for ln in md_t.splitlines():
            if not ln.startswith("| ") or ln.startswith("|---"):
                continue
            if ln.replace("\\|", "").count("|") != 8:   # 7列 -> 8 个未转义竖线
                bad.append(ln)
        checks.append(("竖线转义后列数仍为 7", not bad))

    passed = sum(1 for _n, ok in checks if ok)
    total = len(checks)
    for name, ok in checks:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    if passed == total:
        print("[SELFTEST PASS] 共 %d 项断言全部通过" % total)
        return 0
    print("[SELFTEST FAIL] %d/%d 通过，%d 项失败" % (passed, total, total - passed))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="扫描法律知识库并生成含效力状态的全量清单（只读）")
    ap.add_argument("root", nargs="?", help="知识库根目录")
    ap.add_argument("-o", "--output", help="输出文件路径，默认打印到屏幕")
    ap.add_argument("--no-ignore", action="store_true", help="不忽略任何目录")
    ap.add_argument("--exts", help="只统计这些扩展名，如 .pdf,.txt")
    ap.add_argument("--selftest", "--selfcheck", dest="selftest",
                    action="store_true", help="运行自检并退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return cmd_selfcheck(args)

    if not args.root:
        ap.print_help()
        return 2

    if not os.path.isdir(args.root):
        sys.stderr.write("错误：目录不存在或不是目录：%s\n" % args.root)
        return 2

    ignore_dirs = set() if args.no_ignore else DEFAULT_IGNORE_DIRS
    rows = collect(args.root, ignore_dirs, DEFAULT_IGNORE_FILES,
                   normalize_exts(args.exts))
    if not rows:
        sys.stderr.write("提示：没有找到符合条件的文件。\n")

    md = render(args.root, rows)

    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        sys.stderr.write("清单已生成：%s（%d 个文件）\n" % (args.output, len(rows)))
    else:
        sys.stdout.write(md + "\n")

    blanks = sum(1 for r in rows if not r["效力状态"])
    if blanks:
        sys.stderr.write(
            "提醒：%d 个文件的「效力状态」为空，请人工补齐。"
            "空着等于没有，猜错比空着更危险。\n" % blanks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
