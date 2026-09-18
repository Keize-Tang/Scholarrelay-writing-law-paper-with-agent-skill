#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py —— 正文引用编号 ↔ 文末参考文献列表 一致性校验（只读）

不做任何修改，只输出诊断报告。专治以下"低级但致命"错误：
    * 缺失：正文引用了 [5]，但文末列表里没有 [5]
    * 多余：文末有 [44]，但正文从未引用
    * 跳号：编号不连续（缺号）
    * 重号：同一编号在文末列表里出现多次（同一文献重复占号）
    * 顺序不符：首次出现顺序与编号顺序不一致
    * 僵尸：文末存在内容完全相同的重复条目（不同编号但同一文献）

用法：
    python validate.py 论文正文_XX_v5.md
    python validate.py 论文正文_XX_v5.md --refs-heading "## 参考文献"

    # 校验页下脚注体例（[^1] 引用 vs [^1]: 定义）
    python validate.py 论文正文_XX.md --mode footnote

退出码：0 = 通过；1 = 有问题；2 = 文件/格式错误
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

# 多编码文本读取（Windows 上常见 GBK/GB18030/BOM，硬用 utf-8 会崩）
# 注：本块自带 import，不依赖调用方是否已 import os / sys
try:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _textio import read_text as _read_text_any
except ImportError:          # 单独复制本脚本（无 _textio.py）时降级
    def _read_text_any(p):
        with open(p, encoding="utf-8") as f:
            return f.read()

DEFAULT_REFS_HEADING = "## 参考文献"

# 正文引用：[1]  [1-3]  [1,3]  [1，3]  [1-3,5]
CITE_RE = re.compile(r"\[(\d+(?:\s*[-–—]\s*\d+)?(?:\s*[,，]\s*\d+(?:\s*[-–—]\s*\d+)?)*)\]")
FN_REF_RE = re.compile(r"\[\^(\d+)\]")
FN_DEF_RE = re.compile(r"^\[\^(\d+)\]:\s*(.*)$", re.M)


def expand_citation(raw: str) -> list[int]:
    """把 [1-3,5] 展开为 [1,2,3,5]。"""
    out: list[int] = []
    for part in re.split(r"[,，]", raw):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b - a < 200:          # 防呆：异常范围不展开
                out.extend(range(a, b + 1))
            else:
                out.append(a)
        elif part.isdigit():
            out.append(int(part))
    return out


def split_document(text: str, heading: str) -> tuple[str, str]:
    idx = text.find(heading)
    if idx < 0:
        raise ValueError(
            f"未找到参考文献分隔标记「{heading}」。\n"
            f"请在正文与参考文献之间保留一行 `{heading}`，"
            f"或用 --refs-heading 指定实际使用的标题。")
    return text[:idx], text[idx:]


def parse_ref_entries(refs_section: str) -> dict[int, list[str]]:
    """解析文末列表，返回 {编号: [条目文本, ...]}（同编号多次出现会被记录）。"""
    entries: dict[int, list[str]] = {}
    for m in re.finditer(r"^\[(\d+)\]\s*(.+?)(?=\n\[\d+\]|\Z)",
                         refs_section, re.M | re.S):
        num = int(m.group(1))
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        entries.setdefault(num, []).append(body)
    return entries


def norm_entry(text: str) -> str:
    """条目归一化，用于识别"同一文献重复占号"。"""
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"[\"'“”‘’]", "", t)
    return t.lower()


def check_journal(body: str, refs_section: str) -> tuple[bool, list[str]]:
    entries = parse_ref_entries(refs_section)
    ref_nums = sorted(entries.keys())

    # 正文引用（按出现顺序，保留重复）
    hits: list[int] = []
    for m in CITE_RE.finditer(body):
        hits.extend(expand_citation(m.group(1)))
    cited = sorted(set(hits))

    # 首次出现顺序
    first_order: list[int] = []
    for n in hits:
        if n not in first_order:
            first_order.append(n)

    problems: list[str] = []

    missing = sorted(set(cited) - set(ref_nums))
    extra = sorted(set(ref_nums) - set(cited))

    if missing:
        problems.append(f"❌ 缺失（正文引用但文末无此条目）：{missing}")
    if extra:
        problems.append(f"❌ 多余（文末有条目但正文未引用）：{extra}")

    # 跳号
    if ref_nums:
        expected = set(range(1, max(ref_nums) + 1))
        gaps = sorted(expected - set(ref_nums))
        if gaps:
            problems.append(f"❌ 跳号（编号不连续，缺）：{gaps}")

    # 重号（同一编号在列表里出现多次）
    dups = {n: len(v) for n, v in entries.items() if len(v) > 1}
    if dups:
        detail = "；".join(f"[{n}]×{c}" for n, c in sorted(dups.items()))
        problems.append(f"❌ 重号（同一编号在文末列表出现多次）：{detail}")

    # 僵尸重复：不同编号但条目内容完全相同
    seen: dict[str, int] = {}
    zombies = []
    for n in ref_nums:
        key = norm_entry(entries[n][0])
        if key in seen:
            zombies.append((seen[key], n))
        else:
            seen[key] = n
    if zombies:
        detail = "；".join(f"[{a}] 与 [{b}] 内容相同" for a, b in zombies)
        problems.append(f"❌ 重复条目（不同编号指向同一文献）：{detail}")

    # 顺序不符
    mismatch = [n for i, n in enumerate(first_order) if n != i + 1]
    if mismatch:
        head = mismatch[:8]
        problems.append(
            f"⚠️  顺序不符（首次出现顺序与编号顺序不一致）：{head}"
            f"{' …' if len(mismatch) > 8 else ''}")

    # 打印报告
    print("=" * 64)
    print("参考文献编号校验报告")
    print("=" * 64)
    print(f"正文引用总次数   ：{len(hits)}")
    print(f"正文唯一引用数   ：{len(cited)}")
    print(f"文末条目总数     ：{len(ref_nums)}")
    if ref_nums:
        print(f"文末编号范围     ：{min(ref_nums)} — {max(ref_nums)}")
    print(f"正文引用编号     ：{_fmt(cited)}")
    print(f"文末条目编号     ：{_fmt(ref_nums)}")
    print("-" * 64)
    if problems:
        for p in problems:
            print(p)
        print("\n【结论】校验未通过。")
        print("建议：补齐缺失条目后执行  python renumber.py <文件>  重排，再复校本文件。")
    else:
        print("✅ 全部通过：无缺失、无多余、无跳号、无重号、无重复条目，顺序一致。")
        print("\n【结论】校验通过。")
    return (not problems), problems


def _fmt(nums: list[int], limit: int = 40) -> str:
    if not nums:
        return "（空）"
    shown = " ".join(f"[{n}]" for n in nums[:limit])
    return shown + (f" … 共 {len(nums)} 个" if len(nums) > limit else "")


def check_footnote(body: str, refs_section: str) -> tuple[bool, list[str]]:
    full = body + refs_section
    refs = sorted({int(x) for x in FN_REF_RE.findall(body)})
    defs = sorted({int(m.group(1)) for m in FN_DEF_RE.finditer(full)})
    # 定义段可能被 split 掉，这里在原文中重新找
    problems: list[str] = []
    print("=" * 64)
    print("脚注校验报告（[^n] 引用 vs [^n]: 定义）")
    print("=" * 64)
    print(f"脚注引用编号：{_fmt(refs)}")
    print(f"脚注定义编号：{_fmt(defs)}")
    print("-" * 64)
    miss = sorted(set(refs) - set(defs))
    extra = sorted(set(defs) - set(refs))
    if miss:
        problems.append(f"❌ 缺失定义：{miss}")
    if extra:
        problems.append(f"⚠️  定义了但未引用：{extra}")
    if defs:
        expected = set(range(1, max(defs) + 1))
        gaps = sorted(expected - set(defs))
        if gaps:
            problems.append(f"❌ 编号不连续，缺：{gaps}")
    if problems:
        for p in problems:
            print(p)
        print("\n【结论】校验未通过。")
    else:
        print("✅ 脚注引用与定义一一对应，编号连续。")
        print("\n【结论】校验通过。")
    return (not problems), problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="正文引用编号与文末参考文献一致性校验（只读）")
    ap.add_argument("file", help="论文 Markdown 文件")
    ap.add_argument("--refs-heading", default=DEFAULT_REFS_HEADING,
                    help=f"参考文献标题行（默认 {DEFAULT_REFS_HEADING!r}）")
    ap.add_argument("--mode", choices=["auto", "journal", "footnote"],
                    default="auto",
                    help="auto=自动识别（默认）；journal=文末参考文献体例；"
                         "footnote=页下脚注体例")
    ap.add_argument("--quiet", action="store_true", help="只在失败时输出摘要")
    args = ap.parse_args(argv)

    try:
        text = _read_text_any(args.file)
    except OSError as exc:
        print(f"无法读取文件：{exc}", file=sys.stderr)
        return 2

    has_fn_defs = bool(FN_DEF_RE.search(text))
    has_refs_head = args.refs_heading in text
    body_guess = text.split(args.refs_heading)[0] if has_refs_head else text
    has_bracket_cites = bool(CITE_RE.search(body_guess))

    mode = args.mode
    if mode == "auto":
        if has_fn_defs and not has_bracket_cites:
            mode = "footnote"
        elif has_refs_head and has_bracket_cites:
            mode = "journal"
        elif has_fn_defs:
            mode = "footnote"
        elif has_refs_head:
            mode = "journal"
        else:
            print(f"❌ 既未找到参考文献标题「{args.refs_heading}」，"
                  f"也未找到脚注定义（[^n]:）。\n"
                  f"   请确认文件格式，或用 --refs-heading / --mode 指定。",
                  file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"[自动识别体例：{'页下脚注' if mode == 'footnote' else '文末参考文献'}]\n")

    try:
        if mode == "footnote":
            ok, _ = check_footnote(text, "")
        else:
            body, refs_section = split_document(text, args.refs_heading)
            ok, _ = check_journal(body, refs_section)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
