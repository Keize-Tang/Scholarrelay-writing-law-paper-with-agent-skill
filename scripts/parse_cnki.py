#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_cnki.py —— 知网题录解析器

把从知网导出的题录文本（RefWorks 或 EndNote 格式，自动识别）解析为结构化 TSV，
并可选生成一份便于人工浏览的 Markdown 清单。

支持两种知网导出格式：
  * RefWorks : 以 "RT Journal Article" 开头，字段形如 "A1 作者"
  * EndNote  : 以 "%0 Journal Article" 开头，字段形如 "%A 作者"

用法：
    python parse_cnki.py CNKI-20260827143104583.txt -o 题录.tsv
    python parse_cnki.py 题录目录/ -o 题录.tsv --md 题录清单.md
    python parse_cnki.py a.txt b.txt c.txt -o 题录.tsv

输出 TSV 列：
    id  type  authors  title  journal  year  volume  issue  pages
    keywords  doi  abstract  source_file
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- 字段定义

FIELDS = [
    "id", "type", "authors", "title", "journal", "year", "volume",
    "issue", "pages", "keywords", "doi", "abstract", "source_file",
]

# RefWorks 字段码 -> 内部字段名。注意知网 RefWorks 的卷号字段是小写 "vo"。
REFWORKS_MAP = {
    "RT": "type", "A1": "authors", "T1": "title", "JF": "journal",
    "YR": "year", "vo": "volume", "IS": "issue", "OP": "pages",
    "K1": "keywords", "DO": "doi", "AB": "abstract",
}

# 已知但不需要保留的 RefWorks 字段码（用于识别"这是字段行"而非摘要续行）
REFWORKS_IGNORED = {
    "sr", "a2", "a3", "ad", "t2", "t3", "jo", "pp", "pd", "pb", "rp",
    "id", "av", "et", "wt", "ol", "cl", "sn", "cn", "la", "ds", "lk",
    "vo", "is", "yr", "op", "k1", "do", "ab", "jf", "t1", "a1", "rt",
}

# EndNote 字段码 -> 内部字段名
ENDNOTE_MAP = {
    "%0": "type", "%A": "authors", "%T": "title", "%J": "journal",
    "%D": "year", "%V": "volume", "%N": "issue", "%P": "pages",
    "%K": "keywords", "%R": "doi", "%X": "abstract",
}


# ---------------------------------------------------------------- 编码处理

def read_text(path: str) -> str:
    """多编码尝试读取，优先 UTF-8，回退 GB18030 / GBK。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------- 格式识别

def detect_format(text: str) -> str:
    """返回 'refworks' / 'endnote' / 'unknown'。"""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("%0") or s.startswith("%A") or s.startswith("%T"):
            return "endnote"
        if s.startswith("RT ") or s.startswith("A1 ") or s.startswith("T1 "):
            return "refworks"
        break
    return "unknown"


# ---------------------------------------------------------------- 解析核心

def _is_refworks_field(line: str) -> tuple[str | None, str | None]:
    """判断是否为 RefWorks 字段行。是则返回 (code, value)，否则 (None, None)。

    只认已知字段码，避免把长摘要的续行误判为字段。
    注意：知网对空值字段会导出成 "vo " 这样的裸字段码行（尾随空格），
    strip 之后必须仍能识别为字段行，否则会被误接成上一字段的续行。
    """
    # 裸字段码行（空值字段）
    bare = line.strip()
    if bare in REFWORKS_MAP or bare.lower() in REFWORKS_IGNORED:
        return bare, ""
    m = re.match(r"^([A-Za-z][A-Za-z0-9]?)\s+(.*)$", line)
    if not m:
        return None, None
    code = m.group(1)
    if code in REFWORKS_MAP or code.lower() in REFWORKS_IGNORED:
        return code, m.group(2)
    return None, None


def _split_records_refworks(text: str) -> list[list[str]]:
    """RefWorks：每条记录以 'RT ' 开头。"""
    records, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("RT "):
            if current:
                records.append(current)
            current = [s]
            continue
        if current is None:
            continue
        if _is_refworks_field(s)[0] is not None:
            current.append(s)
        else:
            # 长摘要被拆行 -> 拼到上一行
            current[-1] = current[-1] + " " + s
    if current:
        records.append(current)
    return records


def _split_records_endnote(text: str) -> list[list[str]]:
    """EndNote：每条记录以 '%0' 开头。"""
    records, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("%0"):
            if current:
                records.append(current)
            current = [s]
            continue
        if current is None:
            continue
        if re.match(r"^%[A-Z0-9@!?+*$&]", s):
            current.append(s)
        else:
            if current:
                current[-1] = current[-1] + " " + s
    if current:
        records.append(current)
    return records


def _fields_from_lines(lines: list[str], fmt: str) -> dict:
    mapping = REFWORKS_MAP if fmt == "refworks" else ENDNOTE_MAP
    rec: dict[str, list[str]] = {}
    for line in lines:
        if fmt == "refworks":
            code, value = _is_refworks_field(line)
        else:
            m = re.match(r"^(%[A-Z0-9@!?+*$&])\s*(.*)$", line)
            code, value = (m.group(1), m.group(2)) if m else (None, None)
        if not code:
            continue
        name = mapping.get(code) or mapping.get(code.lower())
        if not name:
            continue
        rec.setdefault(name, []).append((value or "").strip())
    return rec


def parse_file(path: str) -> list[dict]:
    text = read_text(path)
    fmt = detect_format(text)
    if fmt == "unknown":
        raise ValueError(f"无法识别的题录格式：{path}")
    lines_list = (_split_records_refworks(text) if fmt == "refworks"
                  else _split_records_endnote(text))
    out = []
    for lines in lines_list:
        rec = _fields_from_lines(lines, fmt)
        if not rec.get("title"):
            continue
        row = {}
        row["type"] = (rec.get("type", [""])[0] or "").strip()
        # 多作者：用 "; " 连接，便于后续按需切分
        row["authors"] = "; ".join(a.strip() for a in rec.get("authors", []) if a.strip())
        for key in ("title", "journal", "year", "volume", "issue", "pages",
                    "keywords", "doi"):
            row[key] = (rec.get(key, [""])[0] or "").strip()
        abstract = " ".join(rec.get("abstract", []))
        row["abstract"] = re.sub(r"\s+", " ", abstract).strip()
        row["source_file"] = os.path.basename(path)
        out.append(row)
    return out


# ---------------------------------------------------------------- 去重

def _norm_title(t: str) -> str:
    return re.sub(r"[\s《》〈〉“”\"'’‘·：:，,。.、\-—–（）()\[\]【】]", "", t or "").lower()


def dedupe(records: list[dict]) -> tuple[list[dict], int]:
    """按 (标题归一化 + 第一作者) 去重，保留首次出现的记录。"""
    seen, kept, dup = set(), [], 0
    for r in records:
        first_author = (r.get("authors", "").split(";")[0] or "").strip()
        key = (_norm_title(r.get("title", "")), first_author)
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        kept.append(r)
    return kept, dup


# ---------------------------------------------------------------- 输出

def assign_ids(records: list[dict]) -> None:
    """按当前顺序写入 id（题录原序号，用于回溯）。就地修改。"""
    for i, r in enumerate(records, 1):
        r["id"] = i


def write_tsv(records: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        from csv import DictWriter
        w = DictWriter(f, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)


def write_markdown(records: list[dict], path: str) -> None:
    years = [r["year"] for r in records if r.get("year")]
    journals = [r["journal"] for r in records if r.get("journal")]
    has_ab = sum(1 for r in records if r.get("abstract"))
    top = Counter(journals).most_common(10)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 题录清单\n\n")
        f.write(f"- 记录数：{len(records)}\n")
        f.write(f"- 含摘要：{has_ab}\n")
        if years:
            f.write(f"- 年份范围：{min(years)} — {max(years)}\n")
        f.write(f"- 来源文件：{', '.join(sorted({r['source_file'] for r in records}))}\n\n")
        if top:
            f.write("## 载文量前十期刊\n\n")
            for j, c in top:
                f.write(f"- {j}（{c} 篇）\n")
            f.write("\n---\n\n")
        f.write("## 题录明细\n\n")
        for r in records:
            f.write(f"### [{r['id']}] {r['title']}\n\n")
            f.write(f"- 作者：{r.get('authors') or '—'}\n")
            f.write(f"- 出处：{r.get('journal') or '—'} "
                    f"{r.get('year') or ''}"
                    f"{'，' + r['volume'] if r.get('volume') else ''}"
                    f"{'(' + r['issue'] + ')' if r.get('issue') else ''}"
                    f"{'：' + r['pages'] if r.get('pages') else ''}\n")
            if r.get("keywords"):
                f.write(f"- 关键词：{r['keywords']}\n")
            if r.get("abstract"):
                ab = r["abstract"]
                f.write(f"- 摘要：{ab[:400]}{'…' if len(ab) > 400 else ''}\n")
            f.write("\n")


# ---------------------------------------------------------------- 入口

def collect_inputs(paths: list[str]) -> list[str]:
    files = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(".txt"):
                    files.append(os.path.join(p, name))
        else:
            files.append(p)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="解析知网题录（RefWorks / EndNote 自动识别）为 TSV")
    ap.add_argument("inputs", nargs="+", help="题录 txt 文件或包含题录的目录")
    ap.add_argument("-o", "--output", default="题录.tsv", help="输出 TSV 路径")
    ap.add_argument("--md", default=None, help="可选：同时输出 Markdown 清单")
    ap.add_argument("--no-dedupe", action="store_true", help="不去重")
    ap.add_argument("--abstract-limit", type=int, default=0,
                    help="TSV 中摘要截断长度，0 表示不截断")
    args = ap.parse_args(argv)

    files = collect_inputs(args.inputs)
    if not files:
        print("未找到任何题录文件", file=sys.stderr)
        return 2

    all_records, bad = [], []
    for path in files:
        try:
            recs = parse_file(path)
            print(f"  解析 {os.path.basename(path)}：{len(recs)} 条")
            all_records.extend(recs)
        except Exception as exc:  # noqa: BLE001
            bad.append((path, str(exc)))
            print(f"  ⚠️  跳过 {os.path.basename(path)}：{exc}", file=sys.stderr)

    if not all_records:
        print("没有解析到任何记录。请确认导出格式为 RefWorks 或 EndNote。",
              file=sys.stderr)
        return 1

    raw_n = len(all_records)
    if not args.no_dedupe:
        all_records, dup_n = dedupe(all_records)
    else:
        dup_n = 0

    if args.abstract_limit > 0:
        for r in all_records:
            r["abstract"] = (r["abstract"] or "")[:args.abstract_limit]

    assign_ids(all_records)
    write_tsv(all_records, args.output)
    print(f"\n✅ 原始 {raw_n} 条，去重 {dup_n} 条，输出 {len(all_records)} 条")
    print(f"   TSV  -> {args.output}")

    if args.md:
        write_markdown(all_records, args.md)
        print(f"   清单 -> {args.md}")
    if bad:
        print(f"   ⚠️  {len(bad)} 个文件解析失败", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
