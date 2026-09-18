#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
renumber.py —— 按正文首次出现顺序重排参考文献编号（会改写文件，自动备份）

这是本工作流最重要的一步。手工维护编号必然出错（真实教训：增删文献后
正文编号整体错位 12 处、同一文献重复占号 3 次）。正确姿势是：

    1. 在正文里随便插入引用编号（哪怕重复、跳号都没关系）
    2. 把新文献条目追加到文末列表（条目文本必须正确）
    3. 跑本脚本 —— 编号全部自动归位
    4. 跑 validate.py 复校

用法：
    # 先看会怎么改，不写文件
    python renumber.py 论文正文_XX_v5.md --dry-run

    # 执行（原文件备份为 论文正文_XX_v5.md.bak）
    python renumber.py 论文正文_XX_v5.md

    # 同时压缩连续编号（[1][2][3] -> [1-3]）
    python renumber.py 论文正文_XX_v5.md --compress

    # 丢弃未被正文引用的条目
    python renumber.py 论文正文_XX_v5.md --drop-uncited
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys

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

CITE_RE = re.compile(r"\[(\d+(?:\s*[-–—]\s*\d+)?(?:\s*[,，]\s*\d+(?:\s*[-–—]\s*\d+)?)*)\]")
REF_ENTRY_RE = re.compile(r"^\[(\d+)\]\s*(.+?)(?=\n\[\d+\]|\Z)", re.M | re.S)


def expand_citation(raw: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"[,，]", raw):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b - a < 200:
                out.extend(range(a, b + 1))
            else:
                out.append(a)
        elif part.isdigit():
            out.append(int(part))
    return out


def compress(nums: list[int]) -> list[str]:
    """[1,2,3,5] -> ['1-3', '5']"""
    if not nums:
        return []
    nums = sorted(set(nums))
    groups, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        groups.append((start, prev))
        start = prev = n
    groups.append((start, prev))
    out = []
    for a, b in groups:
        if b - a >= 2:
            out.append(f"{a}-{b}")
        elif b == a:
            out.append(str(a))
        else:
            out.extend([str(a), str(b)])
    return out


def norm_entry(text: str) -> str:
    """条目归一化，用于识别"同一文献重复占号"。"""
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"[\"'“”‘’]", "", t)
    return t.lower()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按正文首次出现顺序重排参考文献编号")
    ap.add_argument("file", help="论文 Markdown 文件")
    ap.add_argument("--refs-heading", default=DEFAULT_REFS_HEADING)
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    ap.add_argument("--no-backup", action="store_true", help="不生成 .bak 备份")
    ap.add_argument("--compress", action="store_true",
                    help="把连续编号压缩为区间（如 [1][2][3] -> [1-3]）")
    ap.add_argument("--drop-uncited", action="store_true",
                    help="删除正文未引用的条目（默认保留并排在末尾）")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="不做内容去重（默认会合并内容完全相同的条目）")
    ap.add_argument("--allow-missing", action="store_true",
                    help="正文引用了文末没有的编号时，插入占位条目而不是中止")
    args = ap.parse_args(argv)

    try:
        text = _read_text_any(args.file)
    except OSError as exc:
        print(f"无法读取文件：{exc}", file=sys.stderr)
        return 2

    idx = text.find(args.refs_heading)
    if idx < 0:
        print(f"❌ 未找到参考文献标题「{args.refs_heading}」", file=sys.stderr)
        return 2
    body = text[:idx]
    refs_section = text[idx:]

    # ---- 解析文末条目
    raw_entries: dict[int, str] = {}
    dup_in_list: list[int] = []
    for m in REF_ENTRY_RE.finditer(refs_section):
        num = int(m.group(1))
        entry_text = re.sub(r"\s+", " ", m.group(2)).strip()
        if num in raw_entries:
            dup_in_list.append(num)
        else:
            raw_entries[num] = entry_text
    if dup_in_list:
        print(f"⚠️  文末列表存在重复编号（已取首次出现者）：{sorted(set(dup_in_list))}")

    # ---- 内容去重：不同编号但条目完全相同的，合并为最早的那个编号
    alias: dict[int, int] = {n: n for n in raw_entries}
    entries: dict[int, str] = {}
    merged: list[tuple[int, int]] = []
    if args.keep_duplicates:
        entries = dict(raw_entries)
    else:
        seen: dict[str, int] = {}
        for old in sorted(raw_entries):
            key = norm_entry(raw_entries[old])
            if key in seen:
                alias[old] = seen[key]
                merged.append((old, seen[key]))
            else:
                seen[key] = old
                entries[old] = raw_entries[old]
        if merged:
            detail = "；".join(f"[{b}] 并入 [{a}]" for b, a in merged)
            print(f"🔧 内容去重：{detail}")

    def canon(n: int) -> int:
        return alias.get(n, n)

    # ---- 扫描正文引用
    matches = list(CITE_RE.finditer(body))
    if not matches:
        print("❌ 正文中没有找到任何 [n] 形式的引用。", file=sys.stderr)
        return 2

    used_order: list[int] = []
    for m in matches:
        for n in expand_citation(m.group(1)):
            c = canon(n)
            if c not in used_order:
                used_order.append(c)

    missing = [n for n in used_order if n not in entries]
    if missing:
        msg = f"正文引用了文末没有的编号：{missing}"
        if not args.allow_missing:
            print(f"❌ {msg}", file=sys.stderr)
            print("   请先把这些文献的条目补进文末列表，"
                  "或加 --allow-missing 生成占位条目。", file=sys.stderr)
            return 1
        print(f"⚠️  {msg} —— 已生成占位条目，请务必补齐。")

    # ---- 分配新编号
    new_num: dict[int, int] = {old: i + 1 for i, old in enumerate(used_order)}
    uncited = [o for o in sorted(entries) if o not in new_num]
    if uncited and not args.drop_uncited:
        counter = len(used_order)
        for old in uncited:
            counter += 1
            new_num[old] = counter
        print(f"⚠️  {len(uncited)} 条未被正文引用，已排到末尾：{uncited}"
              f"（加 --drop-uncited 可删除）")
    elif uncited:
        print(f"🔧 已丢弃 {len(uncited)} 条正文未引用的条目：{uncited}")

    # ---- 重写正文引用
    def render(nums: list[int]) -> str:
        mapped = sorted({new_num[canon(n)] for n in nums if canon(n) in new_num})
        if not mapped:
            return ""
        if args.compress:
            return "".join(f"[{p}]" for p in compress(mapped))
        return "".join(f"[{n}]" for n in mapped)

    pieces, last = [], 0
    for m in matches:
        pieces.append(body[last:m.start()])
        pieces.append(render(expand_citation(m.group(1))))
        last = m.end()
    pieces.append(body[last:])
    new_body = "".join(pieces)

    # ---- 重写文末列表
    ordered = sorted(new_num, key=lambda o: new_num[o])
    lines = [args.refs_heading.rstrip("\n"), ""]
    for old in ordered:
        txt = entries.get(old) or f"[待补：原编号 {old} 的文献条目缺失]"
        lines.append(f"[{new_num[old]}] {txt}")
    new_refs = "\n".join(lines) + "\n"

    result = new_body + new_refs

    print("=" * 64)
    print(f"重排预览：{os.path.basename(args.file)}")
    print("=" * 64)
    print(f"正文引用次数     ：{len(matches)}")
    print(f"唯一文献数       ：{len(used_order)}")
    print(f"文末条目数       ：{len(new_num)}")
    print("-" * 64)
    changed = [(o, new_num[o]) for o in used_order if o != new_num[o]]
    print(f"编号变动处数     ：{len(changed)}")
    for o, n in changed[:15]:
        print(f"    [{o}] -> [{n}]")
    if len(changed) > 15:
        print(f"    … 另有 {len(changed) - 15} 处")

    if args.dry_run:
        print("\n（--dry-run 模式，未写入文件）")
        return 0

    if not args.no_backup:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{args.file}.{stamp}.bak"
        shutil.copy2(args.file, backup)
        print(f"\n备份 -> {backup}")

    with open(args.file, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"✅ 已写入 -> {args.file}")
    print("下一步：python validate.py " + os.path.basename(args.file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
