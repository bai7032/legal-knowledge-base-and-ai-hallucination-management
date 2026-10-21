#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按关键词映射把散落资料批量归类到知识库结构中。

用法：
    # 1. 先预演，看看会移动什么（不改动任何文件）
    python kb_migrate.py <资料根目录> --dry-run

    # 2. 确认无误后实际执行
    python kb_migrate.py <资料根目录>

    # 只处理特定扩展名
    python kb_migrate.py <资料根目录> --exts .pdf,.txt

映射规则写在 RULES 里，按顺序匹配，第一个命中的生效。
匹配不到的文件进 00_待更新_临时。

安全约束：
  - 默认不删除任何东西；--prune-empty 只删除**已搬空**的旧目录
  - --prune-empty 必须配合 --yes 使用，且执行前打印将被删除的目录清单
  - 同一份资料的多格式文件（同名不同扩展名）一起移动，保持一致

仅使用标准库，不访问网络。
"""

import argparse
import os
import shutil
import sys
from collections import OrderedDict

# ---------------------------------------------------------------------------
# 映射规则：关键词 -> 目标子目录（相对资料根目录）
# 顺序即优先级，第一个命中的关键词生效
# ---------------------------------------------------------------------------
RULES = [
    # 【第 0 条】已废止 / 待核实的版本，绝不能放进 _现行有效。
    # 放在最前面判断：效力状态优先于内容类型。
    (["已废止", "已失效", "历史版本"], "01_法律规范/_已废止"),
    (["待核实", "版本待确认"], "01_法律规范/_待核实"),

    # 【规范层优先】法律法规文件要先于实务层判断。
    # 否则「中华人民共和国行政复议法」会被「复议」二字截胡，误归到实务层——
    # 这是法条文件最常见的错归，必须用「中华人民共和国」「施行」等强特征先拦住。
    (["法释", "司法解释"], "01_法律规范/_现行有效/司法解释"),
    # 正式法名（中华人民共和国 + 法名），或文件名带施行日期 → 一定是法条文件
    (["中华人民共和国", "法律", "法典", "法_", "法-"], "01_法律规范/_现行有效/法律"),
    (["条例", "规定", "办法", "实施条例"], "01_法律规范/_现行有效/行政法规"),

    # 跨程序的文件先判：文件名同时含「复议」和「诉讼」时，按主导程序归类。
    # 例：「征收补偿与行政复议诉讼衔接_类案检索报告」→ 诉讼（衔接以诉讼为落点）
    (["复议与行政诉讼", "复议诉讼衔接", "复议与诉讼衔接", "复议和诉讼"],
     "03_行政诉讼实务/审理阶段"),

    # 行政复议
    (["行政复议流程", "复议流程", "复议受理", "法律依据汇编"],
     "02_行政复议实务/流程指南"),
    (["复议申请书", "复议答辩", "复议决定", "文书模板"],
     "02_行政复议实务/文书模板"),
    (["前置情形", "决定类型", "复议要点"],
     "02_行政复议实务/常见要点"),
    (["复议"], "02_行政复议实务"),

    # 行政诉讼
    (["行政起诉状", "起诉状", "立案", "管辖"],
     "03_行政诉讼实务/起诉阶段"),
    (["审理", "庭审", "举证", "质证", "类案检索"],
     "03_行政诉讼实务/审理阶段"),
    (["执行", "监督申请"],
     "03_行政诉讼实务/执行阶段"),

    # 案例分区
    (["会议纪要", "典型案例", "指导案例"], "04_案例库/最高法典型案例"),
    (["判例", "案例", "裁判"], "04_案例库/分类案例"),

    # 理论分区
    (["讲义", "教材", "教程", "理论", "论文", "笔记"],
     "05_理论研究/学术论文_笔记"),
]

# 未命中任何规则时的去处
DEFAULT_TARGET = "00_待更新_临时"

# 规则里出现过的顶层目录，用于跳过「已在目标结构内」的文件
KNOWN_TOP_DIRS = sorted({t.split("/")[0] for _kws, t in RULES} | {DEFAULT_TARGET})

# 默认不参与迁移的扩展名
SKIP_EXTS = {".db", ".lnk", ".ini", ".tmp", ".bak", ".exe", ".dll"}

SEP = " | "


def pick_target(filename):
    """按 RULES 返回目标子目录；未命中返回 DEFAULT_TARGET。"""
    low = filename.lower()
    for keywords, target in RULES:
        for kw in keywords:
            if kw.lower() in low:
                return target, kw
    return DEFAULT_TARGET, None


def collect_files(root, exts=None):
    """列出待处理文件（不含知识库自身的结构目录）。"""
    root = os.path.abspath(root)
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 已经在目标结构里的文件不再搬
        dirnames[:] = [d for d in sorted(dirnames) if d not in KNOWN_TOP_DIRS]
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXTS:
                continue
            if exts and ext.lstrip(".") not in exts:
                continue
            abs_path = os.path.join(dirpath, fn)
            result.append(abs_path)
    return result


def group_by_target(files, root):
    """把文件按目标目录分组；同时把同名不同扩展名的文件归到同一组。

    返回 OrderedDict[(target_dir, filename_stem)] -> [src, ...]
    """
    groups = OrderedDict()
    for src in files:
        fn = os.path.basename(src)
        target, _kw = pick_target(fn)
        stem = os.path.splitext(fn)[0]
        groups.setdefault((target, stem), []).append(src)
    return groups


def find_empty_dirs(root):
    """列出 root 下所有空目录（相对路径），从深到浅。"""
    root = os.path.abspath(root)
    empties = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        if not dirnames and not filenames:
            empties.append(os.path.relpath(dirpath, root).replace(os.sep, "/"))
    return empties


def cmd_dryrun(groups, root, out):
    """预演：打印每个文件的归类，不做任何改动。"""
    out.write("=== 预演模式，不会移动任何文件 ===\n")
    out.write("资料根目录：%s\n" % os.path.abspath(root).replace(os.sep, "/"))
    out.write("待处理文件：%d 个\n" % sum(len(v) for v in groups.values()))
    out.write("\n")
    for (target, _stem), srcs in groups.items():
        out.write("→ %s\n" % target)
        for src in srcs:
            rel = os.path.relpath(src, root).replace(os.sep, "/")
            out.write("    %s\n" % rel)
        out.write("\n")

    empties = find_empty_dirs(root)
    if empties:
        out.write("搬完后以下空目录可清理（需 --prune-empty --yes）：\n")
        for e in empties:
            out.write("    %s\n" % e)
    return 0


def cmd_apply(groups, root, prune_empty, out):
    """实际移动。"""
    moved = 0
    for (target, _stem), srcs in groups.items():
        dest_dir = os.path.join(root, target.replace("/", os.sep))
        os.makedirs(dest_dir, exist_ok=True)
        for src in srcs:
            dest = os.path.join(dest_dir, os.path.basename(src))
            if os.path.abspath(dest) == os.path.abspath(src):
                continue
            if os.path.exists(dest):
                out.write("跳过（目标已存在）：%s\n"
                          % os.path.relpath(src, root).replace(os.sep, "/"))
                continue
            shutil.move(src, dest)
            moved += 1
    out.write("已移动 %d 个文件\n" % moved)

    if prune_empty:
        empties = find_empty_dirs(root)
        if not empties:
            out.write("没有可清理的空目录。\n")
        else:
            out.write("清理以下 %d 个空目录：\n" % len(empties))
            for e in empties:
                full = os.path.join(root, e.replace("/", os.sep))
                try:
                    os.rmdir(full)   # 只删空目录，非空会抛 OSError
                    out.write("    已删除 %s\n" % e)
                except OSError as exc:
                    out.write("    跳过 %s（%s）\n" % (e, exc.strerror))
    return 0


def cmd_selfcheck(_args):
    """映射规则与分组逻辑的断言。"""
    checks = []

    # 规则命中与优先级
    checks.append(("命中复议流程",
                   pick_target("行政复议流程图.png")[0] == "02_行政复议实务/流程指南"))
    checks.append(("命中复议申请书模板",
                   pick_target("复议申请书.docx")[0] == "02_行政复议实务/文书模板"))
    checks.append(("命中起诉状",
                   pick_target("行政起诉状.docx")[0] == "03_行政诉讼实务/起诉阶段"))
    checks.append(("命中法释",
                   pick_target("法释〔2021〕某号.pdf")[0] == "01_法律规范/_现行有效/司法解释"))

    # 【第 0 条】效力状态优先于内容类型
    checks.append(("已废止进 _已废止，不进 _现行有效",
                   pick_target("中华人民共和国行政处罚法_2017修正_已废止.pdf")[0]
                   == "01_法律规范/_已废止"))
    checks.append(("已废止优先于法律类关键词",
                   pick_target("中华人民共和国行政处罚法_已废止.pdf")[0]
                   == "01_法律规范/_已废止"))
    checks.append(("待核实进 _待核实",
                   pick_target("某法_版本待确认.pdf")[0]
                   == "01_法律规范/_待核实"))
    checks.append(("现行有效仍进 _现行有效",
                   pick_target("中华人民共和国行政处罚法_2021修订_现行有效.pdf")[0]
                   == "01_法律规范/_现行有效/法律"))

    # 法条文件优先于实务关键词——「行政复议法」含「复议」，不能被截胡到实务层
    checks.append(("《行政复议法》归规范层，不被「复议」截胡",
                   pick_target("中华人民共和国行政复议法_2023修订_2024-01-01施行_现行有效.pdf")[0]
                   == "01_法律规范/_现行有效/法律"))
    checks.append(("单字『法』不作为关键词（否则书名被截胡）",
                   pick_target("行政法判例百选.pdf")[0] == "04_案例库/分类案例"))
    checks.append(("复议文书仍归实务层",
                   pick_target("行政复议申请书.docx")[0] == "02_行政复议实务/文书模板"))
    checks.append(("条例优先于法（顺序敏感）",
                   pick_target("土地管理法实施条例.pdf")[0] == "01_法律规范/_现行有效/行政法规"))
    checks.append(("中华人民共和国兜底到法律层",
                   pick_target("中华人民共和国行政处罚法.pdf")[0] == "01_法律规范/_现行有效/法律"))
    checks.append(("判例进案例库",
                   pick_target("行政法判例百选.pdf")[0] == "04_案例库/分类案例"))
    checks.append(("讲义进理论层",
                   pick_target("姜明安讲义.pdf")[0] == "05_理论研究/学术论文_笔记"))
    checks.append(("未命中进待更新区",
                   pick_target("随手记.txt")[0] == DEFAULT_TARGET))
    checks.append(("命中时返回最先命中的关键词",
                   pick_target("行政复议流程.png")[1] == "行政复议流程"))
    checks.append(("返回的关键词确实在文件名里",
                   pick_target("行政复议流程.png")[1] in "行政复议流程.png"))
    checks.append(("法名简写带下划线归法律层",
                   pick_target("行政处罚法_2021修订.pdf")[0] == "01_法律规范/_现行有效/法律"))
    checks.append(("复议诉讼衔接类归诉讼审理层",
                   pick_target("征收补偿与行政复议诉讼衔接_类案检索报告.md")[0]
                   == "03_行政诉讼实务/审理阶段"))

    # 分组：同名不同扩展名归到同一目标
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for fn in ("法律_行政处罚法.pdf", "法律_行政处罚法.txt"):
            with open(os.path.join(td, fn), "w", encoding="utf-8") as fh:
                fh.write("x")
        with open(os.path.join(td, "convert.py"), "w", encoding="utf-8") as fh:
            fh.write("print(1)")
        files = collect_files(td)
        groups = group_by_target(files, td)

        stems = [s for (_t, s) in groups]
        checks.append(("同名多格式合并为一组",
                       stems.count("法律_行政处罚法") == 1))
        same_group = next(v for (t, s), v in groups.items()
                          if s == "法律_行政处罚法")
        checks.append(("该组含两个文件", len(same_group) == 2))
        checks.append((".py 不在 SKIP_EXTS 时仍会被收集（由 exts 控制）",
                       len(files) == 3))
        checks.append(("目标目录去重",
                       len({t for (t, _s) in groups}) ==
                       len({pick_target(os.path.basename(p))[0] for p in files})))

        # 空目录识别
        os.makedirs(os.path.join(td, "01_法律规范", "法律"))
        os.makedirs(os.path.join(td, "空的旧文件夹"))
        empties = find_empty_dirs(td)
        checks.append(("识别空目录", "空的旧文件夹" in empties))
        checks.append(("空目录结果用 / 分隔",
                       all("\\" not in e for e in empties)))

        # 已在目标结构内的文件不再收集
        n_before = len(files)
        os.makedirs(os.path.join(td, "02_行政复议实务", "流程指南"))
        with open(os.path.join(td, "02_行政复议实务", "流程指南", "x.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        files2 = collect_files(td)
        checks.append(("跳过已在目标结构内的文件",
                       len(files2) == n_before))

        # 扩展名过滤
        only_txt = collect_files(td, exts={"txt"})
        checks.append(("按扩展名过滤生效",
                       only_txt and all(f.endswith(".txt") for f in only_txt)))

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
        description="按关键词映射批量归类知识库资料（默认预演）")
    ap.add_argument("root", nargs="?", help="资料根目录")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印归类结果，不移动文件（推荐先跑这个）")
    ap.add_argument("--exts", help="只处理这些扩展名，如 .pdf,.txt")
    ap.add_argument("--prune-empty", action="store_true",
                    help="搬完后清理已空掉的旧目录（需配合 --yes）")
    ap.add_argument("--yes", action="store_true",
                    help="确认执行会改动文件的操作")
    ap.add_argument("--selftest", "--selfcheck", dest="selftest",
                    action="store_true", help="运行自检并退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return cmd_selfcheck(args)

    if not args.root:
        ap.print_help()
        return 2
    if not os.path.isdir(args.root):
        sys.stderr.write("错误：目录不存在：%s\n" % args.root)
        return 2

    exts = None
    if args.exts:
        exts = {p.strip().lower().lstrip(".")
                for p in args.exts.split(",") if p.strip()}

    files = collect_files(args.root, exts)
    if not files:
        sys.stderr.write("没有找到待处理的文件。\n")
        return 0

    groups = group_by_target(files, args.root)

    if args.dry_run or not args.yes:
        return cmd_dryrun(groups, args.root, sys.stdout)

    if args.prune_empty:
        sys.stderr.write("注意：--prune-empty 会删除已空掉的旧目录。\n"
                         "建议先跑 --dry-run 查看清单。\n")

    return cmd_apply(groups, args.root, args.prune_empty, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
