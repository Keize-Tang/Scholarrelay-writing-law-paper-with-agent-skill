#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cnki2gbt.py —— 从知网题录生成规范参考文献条目

核心价值：知网题录里带有 %P / OP 字段（起止页码）和卷期信息，
因此页码与卷期可以**自动补全，无需人工填写，也就不可能编造**。
这正是审稿人最常指出的"期刊文献缺起止页码"问题的根治办法。

用法：
    # 1) 先解析题录
    python parse_cnki.py CNKI-xxx.txt -o 题录.tsv

    # 2) 挑选要引用的文献编号（一行一个），生成条目
    python cnki2gbt.py 题录.tsv --filter 已引文献.txt -o refs.md

    # 3) 全部生成
    python cnki2gbt.py 题录.tsv -o refs.md

    # 4) 按《法学引注手册》体例（带《》与"第X期""第A—B页"）
    python cnki2gbt.py 题录.tsv --filter 已引文献.txt --style law -o refs.md

两种体例：
    gbt (默认)  GB/T 7714 顺序编码制
                作者. 题名[J]. 刊名, 年, 卷(期): 起止页码.
    law         法学引注手册体例（多数法学核心期刊采用）
                作者：《题名》，《刊名》年份第X期，第A—B页。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

# ---------------------------------------------------------------- 工具

DASH = "\u2014"          # 全角破折号 —
HAN_COLON = "\uff1a"     # ：
HAN_PERIOD = "\u3002"    # 。
HAN_DUN = "\u3001"       # 、
HAN_BOOK_L = "\u300a"    # 《
HAN_BOOK_R = "\u300b"    # 》


def split_authors(raw: str) -> list[str]:
    """作者字段按 ';' 或 '；' 或 '、' 切分。"""
    if not raw:
        return []
    parts = re.split(r"\s*[;；]\s*", raw)
    return [p.strip() for p in parts if p.strip()]


def normalize_pages(pages: str) -> str:
    """'88-112+137' -> '88-112+137'；统一半角连字符。"""
    if not pages:
        return ""
    p = pages.strip().replace("－", "-").replace("—", "-").replace("–", "-")
    p = re.sub(r"\s+", "", p)
    return p


def guess_type_code(doc_type: str, journal: str) -> str:
    t = (doc_type or "").lower()
    if "dissertation" in t or "thesis" in t or "学位" in t:
        return "D"
    if "newspaper" in t or "报纸" in t:
        return "N"
    if "conference" in t or "会议" in t or "proceedings" in t:
        return "C"
    if "book" in t or "专著" in t or "monograph" in t:
        return "M"
    return "J"


def authors_gbt(authors: list[str]) -> str:
    """GB/T 7714：3 名以内全部列出，超过 3 名列前 3 名后加 ', 等'。"""
    if not authors:
        return ""
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + ", 等"


def authors_law(authors: list[str]) -> str:
    """法学引注手册：作者之间用 '、'。"""
    return HAN_DUN.join(authors)


def clean_doi(text: str) -> str:
    """删除 DOI 相关内容。"""
    text = re.sub(r"\s*DOI\s*[:：]\s*\S+", "", text, flags=re.I)
    text = re.sub(r"\s*https?://(dx\.)?doi\.org/\S+", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- 格式化

def format_entry_gbt(row: dict) -> str:
    """GB/T 7714 顺序编码制。"""
    authors = split_authors(row.get("authors", ""))
    title = (row.get("title") or "").strip().rstrip(".。")
    journal = (row.get("journal") or "").strip()
    year = (row.get("year") or "").strip()
    volume = (row.get("volume") or "").strip()
    issue = (row.get("issue") or "").strip()
    pages = normalize_pages(row.get("pages", ""))
    code = guess_type_code(row.get("type", ""), journal)

    a = authors_gbt(authors)
    if code == "J":
        head = f"{a}. {title}[J]. {journal}, {year}"
        if volume:
            head += f", {volume}"
        if issue:
            head += f"({issue})"
        if pages:
            head += f": {pages}"
        return head + "."
    if code == "D":
        return f"{a}. {title}[D]. {year}."
    if code == "N":
        return f"{a}. {title}[N]. {journal}, {year}."
    if code == "C":
        return f"{a}. {title}[C]. {year}."
    return f"{a}. {title}[M]. {journal}, {year}."


def format_entry_law(row: dict) -> str:
    """法学引注手册体例：作者：《题名》，《刊名》年份第X期，第A—B页。"""
    authors = split_authors(row.get("authors", ""))
    title = (row.get("title") or "").strip().rstrip(".。")
    journal = (row.get("journal") or "").strip()
    year = (row.get("year") or "").strip()
    issue = (row.get("issue") or "").strip()
    pages = normalize_pages(row.get("pages", ""))
    code = guess_type_code(row.get("type", ""), journal)

    a = authors_law(authors)
    prefix = f"{a}{HAN_COLON}" if a else ""

    if code == "J":
        s = f"{prefix}{HAN_BOOK_L}{title}{HAN_BOOK_R}"
        s += f"{HAN_BOOK_L}{journal}{HAN_BOOK_R}{year}年"
        if issue:
            s += f"第{issue}期"
        if pages:
            s += f"{HAN_DUN}第{pages.replace('-', DASH)}页"
        return s + HAN_PERIOD
    if code == "D":
        return f"{prefix}{HAN_BOOK_L}{title}{HAN_BOOK_R}，{year}年学位论文{HAN_PERIOD}"
    if code == "N":
        return f"{prefix}{HAN_BOOK_L}{title}{HAN_BOOK_R}，{HAN_BOOK_L}{journal}{HAN_BOOK_R}{year}年{HAN_PERIOD}"
    return f"{prefix}{HAN_BOOK_L}{title}{HAN_BOOK_R}，{journal}{year}年版{HAN_PERIOD}"


# ---------------------------------------------------------------- IO

def load_tsv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        raise ValueError(f"题录为空：{path}")
    if "title" not in rows[0]:
        raise ValueError(
            f"TSV 格式不符合预期（缺少 title 列）：{path}\n"
            f"请先用 parse_cnki.py 生成题录 TSV。")
    return rows


def load_filter(path: str) -> set[int]:
    ids: set[int] = set()
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            for token in re.split(r"[\s,，]+", line.strip()):
                if token:
                    ids.add(int(token))
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从知网题录生成规范参考文献条目")
    ap.add_argument("tsv", help="parse_cnki.py 产出的题录 TSV")
    ap.add_argument("-o", "--output", default="参考文献.md", help="输出文件")
    ap.add_argument("--filter", default=None,
                    help="仅输出该文件中列出的题录编号（一行一个）")
    ap.add_argument("--style", choices=["gbt", "law"], default="gbt",
                    help="gbt=GB/T 7714（默认）；law=法学引注手册体例")
    ap.add_argument("--keep-doi", action="store_true", help="保留 DOI（默认清理）")
    ap.add_argument("--start", type=int, default=1, help="起始编号，默认 1")
    ap.add_argument("--no-header", action="store_true", help="不写 Markdown 标题")
    args = ap.parse_args(argv)

    rows = load_tsv(args.tsv)
    wanted = load_filter(args.filter) if args.filter else None

    if wanted is not None:
        present = {int(r["id"]) for r in rows}
        missing = sorted(wanted - present)
        if missing:
            print(f"⚠️  以下编号在题录中不存在，已跳过：{missing}", file=sys.stderr)
        rows = [r for r in rows if int(r["id"]) in wanted]

    formatter = format_entry_law if args.style == "law" else format_entry_gbt

    lines, no_pages, no_journal = [], [], []
    num = args.start
    for r in rows:
        entry = formatter(r)
        if not args.keep_doi:
            entry = clean_doi(entry)
        lines.append(f"[{num}] {entry}")
        if guess_type_code(r.get("type", ""), r.get("journal", "")) == "J":
            if not normalize_pages(r.get("pages", "")):
                no_pages.append((r.get("id"), r.get("title", "")[:40]))
            if not (r.get("journal") or "").strip():
                no_journal.append((r.get("id"), r.get("title", "")[:40]))
        num += 1

    with open(args.output, "w", encoding="utf-8") as f:
        if not args.no_header:
            style_name = "法学引注手册体例" if args.style == "law" else "GB/T 7714 顺序编码制"
            f.write(f"# 参考文献（{style_name}）\n\n")
            f.write(f"> 由 cnki2gbt.py 自题录 `{os.path.basename(args.tsv)}` 生成，"
                    f"共 {len(lines)} 条。页码与卷期取自题录字段，非人工填写。\n\n")
        f.write("\n".join(lines) + "\n")

    print(f"✅ 生成 {len(lines)} 条 -> {args.output}")
    if no_pages:
        print(f"\n⚠️  {len(no_pages)} 条期刊文献缺起止页码（需人工核实，勿编造）：")
        for i, t in no_pages[:10]:
            print(f"    [{i}] {t}")
        if len(no_pages) > 10:
            print(f"    … 另有 {len(no_pages) - 10} 条")
    if no_journal:
        print(f"\n⚠️  {len(no_journal)} 条缺刊名：{[i for i, _ in no_journal]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
