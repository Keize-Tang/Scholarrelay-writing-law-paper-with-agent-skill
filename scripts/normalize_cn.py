#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_cn.py —— 中文标点规范化（对齐人工定稿的标点习惯）

## 为什么需要它

对比"AI 生成稿 → 人工终稿"的真实差异后发现：**最高频、最一致的一类修改是标点**。

实测（同一篇论文的两个版本）：

| 版本 | 半角直引号 `"` | 全角弯引号 `“”` |
|---|---|---|
| AI 生成稿 | **634** | 0 |
| 人工终稿 | **0** | **646** |

也就是说，人工终稿把**全部 634 处直引号改成了中文弯引号**。
这类修改纯机械、量极大、却必须逐处手改——这正是应该交给脚本的部分。

本脚本把可机械化的部分自动完成，让人工修改集中在**真正需要判断的地方**。

## 规则清单

| # | 规则 | 依据 |
|---|---|---|
| 1 | 半角直双引号 `"` → 中文弯双引号 `“ ”`（成对） | 实测 634/634 处被人工改正 |
| 2 | 半角直单引号 `'` → 中文弯单引号 `‘ ’`（仅中文语境） | 实测 10 处被人工改正 |
| 3 | `...` / `。。。` → `……` | 中文省略号规范 |
| 4 | 中文语境中的半角逗号 `,` → `，` | 中英混排常见问题 |
| 5 | 中文语境中的半角句号 `.` → `。`（不碰编号 `1.`） | 同上 |
| 6 | 中文语境中的半角分号 `;` 冒号 `:` 问号 `?` 叹号 `!` → 全角 | 同上 |
| 7 | 年份区间 `2023—2026` → `2023-2026`（**可选**，默认关闭） | 人工终稿倾向半角，但并非全部统一（17→10），故设为可选 |

## 用法

    # 先看会改什么（不改文件）
    python scripts/normalize_cn.py 论文.md --dry-run

    # 就地规范化（自动备份原文件）
    python scripts/normalize_cn.py 论文.md

    # 另存
    python scripts/normalize_cn.py 论文.md -o 论文_规范.md

    # 只做体检报告，不改
    python scripts/normalize_cn.py 论文.md --report

    # 连年份区间也改
    python scripts/normalize_cn.py 论文.md --range-hyphen

退出码：0 = 无需修改或已修改；1 = 发现问题（--report 模式下）；2 = 文件错误
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

CJK = r"\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\u3005\u3007"
CJK_RE = re.compile(f"[{CJK}]")
CJK_CHAR = f"[{CJK}]"


def _fix_quote_pairs(text: str) -> tuple[str, int]:
    """把半角直双引号成对转成中文弯引号。逐段重置配对状态。

    逐段重置是必要的：引号不应跨段，否则一段里的落单引号会让后面全部翻转。
    """
    changed = 0
    out_lines = []
    for line in text.split("\n"):
        buf, open_next = [], True
        for ch in line:
            if ch == '"':
                buf.append("\u201c" if open_next else "\u201d")
                open_next = not open_next
                changed += 1
            else:
                buf.append(ch)
        out_lines.append("".join(buf))
    return "\n".join(out_lines), changed


def _fix_single_quotes(text: str) -> tuple[str, int]:
    """半角直单引号 → 中文弯单引号，仅限中文语境。

    只处理"紧邻中日韩字符"的单引号，避免误伤英文所有格（don't、it's）。
    """
    changed = 0
    # 成对处理：按出现顺序交替左右
    out_lines = []
    for line in text.split("\n"):
        buf, open_next = [], True
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'":
                prev_cjk = i > 0 and CJK_RE.match(line[i - 1])
                next_cjk = i + 1 < len(line) and CJK_RE.match(line[i + 1])
                if prev_cjk or next_cjk:
                    buf.append("\u2018" if open_next else "\u2019")
                    open_next = not open_next
                    changed += 1
                    i += 1
                    continue
            buf.append(ch)
            i += 1
        out_lines.append("".join(buf))
    return "\n".join(out_lines), changed


def _fix_ellipsis(text: str) -> tuple[str, int]:
    n = len(re.findall(r"\.{3,}", text)) + len(re.findall(r"\u3002{2,}", text))
    text = re.sub(r"\.{3,}", "\u2026\u2026", text)
    text = re.sub(r"\u3002{2,}", "\u2026\u2026", text)
    return text, n


def _fix_cjk_punct(text: str) -> tuple[str, dict]:
    """中文语境中的半角标点 → 全角。只处理"两侧都是中文"的安全情形。"""
    counts: dict[str, int] = {}

    def sub_both_sides(pat: str, repl: str, label: str) -> None:
        nonlocal text
        rx = re.compile(f"(?<={CJK_CHAR}){pat}(?={CJK_CHAR})")
        counts[label] = len(rx.findall(text))
        text = rx.sub(repl, text)

    sub_both_sides(",", "\uff0c", "逗号")
    # 句点：仅"中文.中文"，不碰 1. / 1.1 / 英文缩写
    sub_both_sides(r"\.", "\u3002", "句号")
    sub_both_sides(";", "\uff1b", "分号")
    sub_both_sides(":", "\uff1a", "冒号")
    sub_both_sides(r"\?", "\uff1f", "问号")
    sub_both_sides("!", "\uff01", "叹号")
    return text, {k: v for k, v in counts.items() if v}


def _fix_year_range(text: str) -> tuple[str, int]:
    rx = re.compile(r"(\d{4})\s*[\u2014\u2013]\s*(\d{4})")
    n = len(rx.findall(text))
    text = rx.sub(r"\1-\2", text)
    return text, n


def analyze(text: str) -> dict:
    """统计当前问题分布（不做修改）。"""
    return {
        "半角直双引号": text.count('"'),
        "半角直单引号(中文语境)": len(re.findall(f"(?<=[{CJK}])'|'(?=[{CJK}])", text)),
        "中文语境半角逗号": len(re.findall(f"(?<={CJK_CHAR}),(?={CJK_CHAR})", text)),
        "中文语境半角句号": len(re.findall(f"(?<={CJK_CHAR})\\.(?={CJK_CHAR})", text)),
        "半角省略号(...)": len(re.findall(r"\.{3,}", text)),
        "年份区间用一字线": len(re.findall(r"\d{4}\s*[\u2014\u2013]\s*\d{4}", text)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="中文标点规范化（对齐人工定稿习惯）")
    ap.add_argument("src", help="Markdown 文件")
    ap.add_argument("-o", "--output", default=None, help="输出文件（默认就地修改）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    ap.add_argument("--report", action="store_true", help="只出体检报告，不改")
    ap.add_argument("--no-backup", action="store_true", help="就地修改时不备份")
    ap.add_argument("--range-hyphen", action="store_true",
                    help="把年份区间的一字线改为半角连字符（默认不改）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.src):
        print(f"无法读取文件：{args.src}", file=sys.stderr)
        return 2

    text = _read_text_any(args.src)

    before = analyze(text)

    if args.report:
        print("=" * 60)
        print(f"中文标点体检：{os.path.basename(args.src)}")
        print("=" * 60)
        total = 0
        for k, v in before.items():
            mark = "⚠️ " if v else "✅ "
            print(f"  {mark}{k:<24}{v:>6} 处")
            total += v
        print("-" * 60)
        if total == 0:
            print("✅ 标点规范，未发现问题。")
        else:
            print(f"⚠️  共 {total} 处可机械化修正。")
            print("   执行 python scripts/normalize_cn.py <文件> 自动修正。")
        return 0 if total == 0 else 1

    dirty = text
    log: list[tuple[str, int]] = []

    dirty, n = _fix_quote_pairs(dirty)
    log.append(("半角直双引号 → 中文弯引号", n))
    dirty, n = _fix_single_quotes(dirty)
    log.append(("半角直单引号 → 中文弯单引号", n))
    dirty, n = _fix_ellipsis(dirty)
    log.append(("省略号 → ……", n))
    dirty, cjk_counts = _fix_cjk_punct(dirty)
    for k, v in cjk_counts.items():
        log.append((f"中文语境半角{k} → 全角", v))
    if args.range_hyphen:
        dirty, n = _fix_year_range(dirty)
        log.append(("年份区间一字线 → 半角连字符", n))

    changes = [(k, v) for k, v in log if v]

    print("=" * 60)
    print(f"中文标点规范化：{os.path.basename(args.src)}")
    print("=" * 60)
    if not changes:
        print("  ✅ 无需修改。")
        return 0
    for k, v in changes:
        print(f"  · {k}：{v} 处")

    # 配对平衡检查（引号转换后可能仍不平衡）
    after = analyze(dirty)
    if after["半角直单引号(中文语境)"] or after["半角直双引号"]:
        print("  ⚠️ 仍有未配对的直引号——请人工确认（不影响已配对部分）")

    if args.dry_run:
        print("\n（--dry-run：未写入文件）")
        return 0

    if args.output:
        out = args.output
    else:
        out = args.src
        if not args.no_backup:
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = f"{args.src}.{stamp}.bak"
            shutil.copy2(args.src, bak)
            print(f"\n  备份 → {bak}")

    with open(out, "w", encoding="utf-8") as f:
        f.write(dirty)
    print(f"  ✅ 已写入 → {out}")
    print("\n  下一步：人工处理脚本管不了的部分——")
    print("    · 标题层级编号（一、/（一）/1.）与措辞")
    print("    · 删除元叙述与机械过渡语（\"从最基本的层面开始\"\"第一个差异在于\"）")
    print("    · 见 references/15-human-editing-patterns.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
