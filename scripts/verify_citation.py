#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在法条汇编/法规文本中定位「第 X 条」，用于核对条号是否正确。

这是防幻觉的辅助工具：AI 引用条号后，用它确认「这一条确实是这个内容」。

用法：
    # 在单个文件中查第 20 条
    python verify_citation.py <文件路径> --article 20

    # 查多条
    python verify_citation.py <文件路径> --article 20 --article 62

    # 只看文件里有哪些条（不指定 --article）
    python verify_citation.py <文件路径> --list

    # 关键词定位：先找含关键词的条，再报条号
    python verify_citation.py <文件路径> --find "六十日"

支持 .txt / .md / .html(去除标签后取文本) / .docx(提取正文，纯标准库 zipfile+XML)。
仅读取，不修改文件；不访问网络。

重要提示：
  本工具只能确认「文件里第 20 条写了什么」，不能确认「现行法的第 20 条是这一条」。
  法条编号会因修订而变动——务必确认文件本身是现行有效版本。

自检：
    python verify_citation.py --selfcheck
"""

import argparse
import os
import re
import sys
import zipfile
import html as _html

# 中文数字 → 阿拉伯数字（覆盖法条编号常见范围）
CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

# 「第X条」：X 可为阿拉伯数字或中文数字
ARTICLE_RE = re.compile(r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*条")

# 中文数字解析上限（够用即可，不追求覆盖任意大数）
CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(s):
    """把中文数字串转成 int。无法解析时返回 None。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)

    total = 0        # 已确定的部分（十位及以上）
    section = 0      # 当前单位内的累积
    last_digit = 0
    matched = False

    for ch in s:
        if ch in CN_DIGITS:
            section = CN_DIGITS[ch]
            last_digit = section
            matched = True
        elif ch in CN_UNITS:
            unit = CN_UNITS[ch]
            # "十五" 开头省略了前面的 "一"
            if section == 0:
                section = last_digit if last_digit else 1
            total += section * unit
            section = 0
            last_digit = 0
            matched = True
        elif ch == "两":
            section = 2
            last_digit = 2
            matched = True
        else:
            return None

    if not matched:
        return None
    return total + section


def strip_html(raw):
    """粗略提取 HTML 正文：去 script/style，去标签，还原实体。"""
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = _html.unescape(raw)
    return re.sub(r"[ \t　]+", " ", raw)


def read_docx_text(path):
    """从 .docx 提取正文文本，纯标准库实现。"""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "ignore")
    # 段落结束符转成换行，避免所有文字黏成一行
    xml = xml.replace("</w:p>", "\n")
    parts = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", xml, re.S)
    text = "".join(_html.unescape(p) for p in parts)
    text = text.replace(ns, "")
    return text


def load_text(path):
    """按扩展名选择读取方式，返回 str。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx_text(path)
    # doc / docx 之外的统一按文本读；GBK 常见，做一次回退
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as fh:
                raw = fh.read()
            if ext in (".html", ".htm", ".xhtml"):
                raw = strip_html(raw)
            return raw
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    return strip_html(raw) if ext in (".html", ".htm", ".xhtml") else raw


def extract_articles(text):
    """把文本切成 [(条号int, 原文str), ...]，按出现顺序。

    一条的范围：从「第X条」到下一个「第Y条」或文末。
    """
    hits = []
    for m in ARTICLE_RE.finditer(text):
        num = cn_to_int(m.group(1))
        if num is not None:
            hits.append((num, m.start(), m.end()))
    if not hits:
        return []

    out = []
    for i, (num, _s, e) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(text)
        body = re.sub(r"\s+", "", text[e:end])
        out.append((num, body))
    return out


def cmd_selfcheck(_args):
    """中文数字解析与条文切分的断言。"""
    checks = []

    # 中文数字
    cases = {
        "一": 1, "二": 2, "九": 9, "十": 10,
        "十一": 11, "十五": 15, "二十": 20, "二十条": None,  # 「条」不是数字
        "三十": 30, "六十二": 62, "一百": 100, "一百零一": 101,
        "1": 1, "20": 20, "62": 62,
    }
    for src, want in cases.items():
        got = cn_to_int(src)
        checks.append(("cn_to_int(%r) == %r" % (src, want), got == want))

    checks.append(("空串返回 None", cn_to_int("") is None))
    checks.append(("无关字符返回 None", cn_to_int("abc") is None))

    # 条文切分
    sample = (
        "第一条 为了防止和纠正违法的或者不当的行政行为，制定本法。"
        "第二条 本法所称行政行为，包括法律、法规、规章授权的组织的行为。"
        "第二十条 公民、法人或者其他组织认为行政行为侵犯其合法权益的，"
        "可以自知道或者应当知道该行政行为之日起六十日内提出行政复议申请。"
        "第六十二条 适用普通程序审理的行政复议案件，"
        "行政复议机关应当自受理申请之日起六十日内作出行政复议决定。"
    )
    arts = extract_articles(sample)
    nums = [n for n, _ in arts]
    checks.append(("切出 4 条", len(arts) == 4))
    checks.append(("条号正确", nums == [1, 2, 20, 62]))
    checks.append(("条号升序来自原文顺序", nums[0] < nums[-1]))

    d20 = dict(arts)[20]
    checks.append(("第二十条内容含「六十日」", "六十日" in d20))
    checks.append(("第二十条不含第六十二条内容",
                   "普通程序" not in d20))
    d62 = dict(arts)[62]
    checks.append(("第六十二条内容含「普通程序」", "普通程序" in d62))

    # 首条不吞掉章节标题
    checks.append(("第一条内容以立法目的开头",
                   dict(arts)[1].startswith("为了防止和纠正")))
    checks.append(("条内空白被清除", all(" " not in b for (_n, b) in arts)))

    # 边界
    checks.append(("无条文时返回空", extract_articles("随便一段文字") == []))
    checks.append(("空文本返回空", extract_articles("") == []))
    checks.append(("单条文本能切出 1 条",
                   len(extract_articles("第十五条 同一行政复议案件。")) == 1))
    checks.append(("最后一条延伸到文末",
                   "六十日" in extract_articles("第六十二条 六十日内作出决定。")[0][1]))

    # HTML 清洗
    h = "<html><head><style>a{}</style><script>x()</script></head>" \
        "<body><p>第一条 测试内容</p></body></html>"
    cleaned = strip_html(h)
    checks.append(("strip_html 去 script", "x()" not in cleaned))
    checks.append(("strip_html 去 style", "a{}" not in cleaned))
    checks.append(("strip_html 保留正文", "第一条" in cleaned))
    checks.append(("strip_html 去标签", "<p>" not in cleaned))
    checks.append(("HTML 中能切出条文",
                   [n for n, _ in extract_articles(cleaned)] == [1]))

    # HTML 实体还原
    checks.append(("strip_html 还原实体",
                   "&" in strip_html("<p>&amp;</p>")))

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
        description="在法条文本中定位第 X 条，辅助核对条号（只读）")
    ap.add_argument("path", nargs="?", help="法条文件路径（.txt/.md/.docx/.html）")
    ap.add_argument("--article", action="append", type=int,
                    help="要查的条号，可重复，如 --article 20 --article 62")
    ap.add_argument("--list", action="store_true", help="列出文件中的全部条号")
    ap.add_argument("--find", help="按关键词定位条号")
    ap.add_argument("--max-chars", type=int, default=600,
                    help="每条最多显示多少字符，默认 600")
    ap.add_argument("--selftest", "--selfcheck", dest="selftest",
                    action="store_true", help="运行自检并退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return cmd_selfcheck(args)

    if not args.path:
        ap.print_help()
        return 2
    if not os.path.isfile(args.path):
        sys.stderr.write("错误：文件不存在：%s\n" % args.path)
        return 2

    try:
        text = load_text(args.path)
    except (OSError, zipfile.BadZipFile) as exc:
        sys.stderr.write("错误：读取失败：%s\n" % exc)
        return 2

    arts = extract_articles(text)
    if not arts:
        sys.stderr.write(
            "未在文件中识别到「第X条」格式。\n"
            "请确认文件是法条汇编正文；扫描版 PDF 需先 OCR。\n")
        return 1

    by_num = {}
    for num, body in arts:
        by_num.setdefault(num, body)

    print("文件：%s" % os.path.abspath(args.path).replace(os.sep, "/"))
    print("识别到 %d 条（去重后 %d 条）\n" % (len(arts), len(by_num)))

    if args.list:
        print("条号清单：" + "、".join(str(n) for n in sorted(by_num)))
        return 0

    if args.find:
        kw = args.find
        matched = [(n, b) for n, b in arts if kw in b]
        if not matched:
            print("未找到含「%s」的条文。" % kw)
            return 1
        print("含「%s」的条文共 %d 条：\n" % (kw, len(matched)))
        for n, b in matched:
            show = b[:args.max_chars] + ("…" if len(b) > args.max_chars else "")
            print("第%s条：%s\n" % (n, show))
        return 0

    if not args.article:
        print("未指定 --article 或 --find。用 --list 查看全部条号。")
        return 2

    missing = []
    for n in args.article:
        if n not in by_num:
            missing.append(n)
            print("⚠ 文件中没有找到第 %d 条。\n" % n)
            continue
        body = by_num[n]
        show = body[:args.max_chars] + ("…" if len(body) > args.max_chars else "")
        print("第%d条：%s\n" % (n, show))

    if missing:
        print("提示：缺失条号 %s。可能原因——" % "、".join(map(str, missing)))
        print("  1) 该条在文件里确实不存在；")
        print("  2) 编号方式不同（如『第三十条之一』未被本工具识别）；")
        print("  3) 文件不是现行有效版本，法条编号已因修订变动。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
