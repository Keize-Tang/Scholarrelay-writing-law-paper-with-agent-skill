#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2docx.py —— Markdown 论文 → 期刊体例 Word

设计要点（都是踩坑换来的）：
  1. 用 python-docx 而非 JS 方案：中文引号在 JS 编码转换中会被破坏。
  2. 中文字体必须同时设置 w:eastAsia 属性，只设 font.name 中文不生效。
  3. 首行缩进用 first_line_indent，不用空格。
  4. 参考文献条目用悬挂缩进。
  5. 页下脚注必须生成"真脚注"（<w:footnoteReference>），而非文末尾注。

两种体例：
  journal  ：文末参考文献（GB/T 7714 顺序编码制），正文用 [n]
  footnote ：页下脚注（法学核心期刊常用），正文用 Markdown 脚注 [^n]

用法：
    python md2docx.py 论文定稿.md -o 投稿.docx
    python md2docx.py 论文定稿.md -o 投稿.docx --profile footnote
    python md2docx.py 论文定稿.md -o 投稿.docx --title "论文题目" --author "张三（XX大学）"

依赖：python-docx（含 lxml）
"""

from __future__ import annotations

import argparse
import os
import re
import sys

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    HAS_DOCX = True
except ImportError:
    # ⚠️ 不在这里退出——否则用户连 `--help` 都看不到。
    # 依赖检查推迟到 main() 里 argparse 之后。
    HAS_DOCX = False

try:
    from lxml import etree
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    HAS_FOOTNOTE_SUPPORT = True
except ImportError:
    HAS_FOOTNOTE_SUPPORT = False

# 中文标点规范化（同目录的 normalize_cn.py）。缺失时降级为不规范化。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from normalize_cn import (  # noqa: PLC0415
        _fix_cjk_punct, _fix_ellipsis, _fix_quote_pairs, _fix_single_quotes,
    )
    HAS_NORMALIZER = True
except ImportError:
    HAS_NORMALIZER = False

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
FOOTNOTES_CT = ("application/vnd.openxmlformats-officedocument."
                "wordprocessingml.footnotes+xml")

FN_MARK = "\u00abFN{0}\u00bb"          # «FN1» 占位标记
FN_MARK_RE = re.compile(r"\u00abFN(\d+)\u00bb")

# 字号（磅）
SZ_TITLE, SZ_SUBTITLE = 16, 14
SZ_H1, SZ_ABSTRACT_HEAD, SZ_REFS_HEAD = 15, 15, 15
SZ_H2, SZ_BODY, SZ_AUTHOR = 12, 12, 12
SZ_REF, SZ_FOOTNOTE = 10.5, 9


# ------------------------------------------------------------------ 字体

def set_font(run, cn="宋体", en="Times New Roman", size=SZ_BODY, bold=False):
    """同时设置中文与西文字体。中文靠 w:eastAsia，只设 font.name 无效。"""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = en
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rPr.insert(0, rf)
    rf.set(qn("w:eastAsia"), cn)
    rf.set(qn("w:ascii"), en)
    rf.set(qn("w:hAnsi"), en)


def add_para(doc, cn="宋体", size=SZ_BODY, bold=False, align=None,
             indent=True, line=1.5, before=0, after=0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    if align is not None:
        pf.alignment = align
    if indent:
        pf.first_line_indent = Pt(size * 2)     # 首行缩进 2 字符
    pf.line_spacing = line
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    return p


def add_runs(p, text, cn, size, bold=False, fn_texts=None):
    """写入文本，处理 **粗体**、Markdown 脚注 [^n] 与 «FNn» 占位符。

    脚注必须渲染成**单独一个 run**，后续 XML 后处理才能整块替换为
    <w:footnoteReference>。
    """
    tokens = re.split(r"(\*\*.+?\*\*|\[\^\d+\]|\u00abFN\d+\u00bb)", text)
    for tok in tokens:
        if not tok:
            continue
        # Markdown 脚注引用 [^n] -> 内部占位标记 «FNn»
        m = re.fullmatch(r"\[\^(\d+)\]", tok)
        if m:
            tok = FN_MARK.format(m.group(1))
        if FN_MARK_RE.fullmatch(tok):
            if fn_texts is None:
                continue                      # 非脚注体例：丢弃脚注标记
            r = p.add_run(tok)
            set_font(r, cn, size=size, bold=bold)
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            set_font(r, cn, size=size, bold=True)
        else:
            r = p.add_run(tok)
            set_font(r, cn, size=size, bold=bold)
    return p


# ------------------------------------------------------------------ 脚注

def _w(tag):
    return f"{{{W_NS}}}{tag}"


def build_footnotes_xml(fn_texts: dict[int, str]) -> bytes:
    """构造 word/footnotes.xml。含分隔符脚注（id=-1/0）与正文脚注。"""
    root = etree.Element(_w("footnotes"), nsmap={"w": W_NS})

    for ftype, fid, child in (("separator", "-1", "separator"),
                              ("continuationSeparator", "0",
                               "continuationSeparator")):
        fn = etree.SubElement(root, _w("footnote"))
        fn.set(_w("type"), ftype)
        fn.set(_w("id"), fid)
        p = etree.SubElement(fn, _w("p"))
        pPr = etree.SubElement(p, _w("pPr"))
        sp = etree.SubElement(pPr, _w("spacing"))
        sp.set(_w("after"), "0")
        sp.set(_w("line"), "240")
        sp.set(_w("lineRule"), "auto")
        r = etree.SubElement(p, _w("r"))
        etree.SubElement(r, _w(child))

    for fid in sorted(fn_texts):
        fn = etree.SubElement(root, _w("footnote"))
        fn.set(_w("id"), str(fid))
        p = etree.SubElement(fn, _w("p"))
        pPr = etree.SubElement(p, _w("pPr"))
        sp = etree.SubElement(pPr, _w("spacing"))
        sp.set(_w("line"), "240")
        sp.set(_w("lineRule"), "auto")
        ind = etree.SubElement(pPr, _w("ind"))
        ind.set(_w("firstLine"), "0")
        jc = etree.SubElement(pPr, _w("jc"))
        jc.set(_w("val"), "both")
        # 脚注序号（上标）
        r = etree.SubElement(p, _w("r"))
        rPr = etree.SubElement(r, _w("rPr"))
        va = etree.SubElement(rPr, _w("vertAlign"))
        va.set(_w("val"), "superscript")
        etree.SubElement(r, _w("footnoteRef"))
        # 脚注正文
        r2 = etree.SubElement(p, _w("r"))
        rPr2 = etree.SubElement(r2, _w("rPr"))
        rf = etree.SubElement(rPr2, _w("rFonts"))
        rf.set(_w("eastAsia"), "宋体")
        rf.set(_w("ascii"), "Times New Roman")
        rf.set(_w("hAnsi"), "Times New Roman")
        sz = etree.SubElement(rPr2, _w("sz"))
        sz.set(_w("val"), str(int(SZ_FOOTNOTE * 2)))
        szcs = etree.SubElement(rPr2, _w("szCs"))
        szcs.set(_w("val"), str(int(SZ_FOOTNOTE * 2)))
        t = etree.SubElement(r2, _w("t"))
        t.set(XML_SPACE, "preserve")
        t.text = " " + fn_texts[fid]
    return etree.tostring(root, xml_declaration=True,
                          encoding="UTF-8", standalone=True)


def inject_footnotes(doc, fn_texts: dict[int, str]) -> int:
    """把文档中的 «FNn» 占位 run 替换为真正的脚注引用 run。返回替换数量。"""
    count = 0
    for p in doc.paragraphs:
        for run in list(p.runs):
            m = FN_MARK_RE.fullmatch(run.text or "")
            if not m:
                continue
            fid = m.group(1)
            if int(fid) not in fn_texts:
                continue
            old = run._element
            new_r = OxmlElement("w:r")
            rPr = OxmlElement("w:rPr")
            va = OxmlElement("w:vertAlign")
            va.set(qn("w:val"), "superscript")
            rPr.append(va)
            new_r.append(rPr)
            ref = OxmlElement("w:footnoteReference")
            ref.set(qn("w:id"), fid)
            new_r.append(ref)
            old.addnext(new_r)
            old.getparent().remove(old)
            count += 1
    return count


def attach_footnotes_part(doc, fn_texts: dict[int, str]) -> None:
    """把 footnotes.xml 作为新的 OPC part 挂到文档包上。"""
    xml_bytes = build_footnotes_xml(fn_texts)
    part = Part(
        PackURI("/word/footnotes.xml"),
        FOOTNOTES_CT,
        xml_bytes,
        doc.part.package,
    )
    doc.part.relate_to(part, RT.FOOTNOTES)


# ------------------------------------------------------------------ Markdown 解析

def unwrap_title(t: str) -> str:
    """只在标题被书名号**整体包裹**时去掉书名号。

    不能用 strip("《》")：《示例》“某某”概念探析——… 结尾不是》，会把开头啃掉。
    """
    t = (t or "").strip()
    if len(t) > 2 and t.startswith("《") and t.endswith("》"):
        return t[1:-1].strip()
    return t


class Md:
    """极简 Markdown 论文解析：元信息 / 摘要 / 关键词 / 标题层级 / 正文 / 参考文献。"""

    def __init__(self, text: str):
        self.meta: dict[str, str] = {}
        self.title = ""
        self.subtitle = ""
        self.abstract = ""
        self.keywords = ""
        self.refs: list[str] = []
        self.body: list[tuple[str, str]] = []      # (kind, text)
        self.fn_defs: dict[int, str] = {}
        self._parse(text)

    def _parse(self, text: str) -> None:
        # 脚注定义
        for m in re.finditer(r"^\[\^(\d+)\]:\s*(.+?)(?=\n\[\^\d+\]:|\n\s*\n|\Z)",
                             text, re.M | re.S):
            self.fn_defs[int(m.group(1))] = re.sub(r"\s+", " ", m.group(2)).strip()
        text = re.sub(r"^\[\^(\d+)\]:\s*.+?(?=\n\[\^\d+\]:|\n\s*\n|\Z)",
                      "", text, flags=re.M | re.S)

        lines = text.split("\n")
        i, n = 0, len(lines)
        stripped_body: list[str] = []
        in_refs = False

        while i < n:
            raw = lines[i]
            line = raw.rstrip()
            s = line.strip()

            # 元信息块（引用行）
            m = re.match(r"^>\s*(题目|副标题|作者|基金项目|引注体例|篇幅|目标期刊|页眉)\s*[:：]\s*(.+)$", s)
            if m and not stripped_body:
                key, val = m.group(1), m.group(2).strip()
                val = unwrap_title(val)
                self.meta[key] = val
                i += 1
                continue
            if s.startswith(">") and not stripped_body:
                i += 1
                continue

            # 一级标题：仅当还没取到标题时作为标题，否则作为正文标题
            if s.startswith("# ") and not self.title and not stripped_body:
                self.title = unwrap_title(s[2:].strip())
                i += 1
                continue

            # 参考文献区
            if re.match(r"^#{1,3}\s*参考文献\s*$", s):
                in_refs = True
                i += 1
                continue
            if in_refs:
                m = re.match(r"^\[(\d+)\]\s*(.+)$", s)
                if m:
                    self.refs.append(m.group(2).strip())
                elif s and not s.startswith("#"):
                    if self.refs:
                        self.refs[-1] += " " + s
                i += 1
                continue

            # 摘要 / 关键词
            if re.match(r"^#{1,3}\s*摘\s*要\s*$", s):
                i += 1
                buf = []
                while i < n and not re.match(r"^#{1,3}\s", lines[i].strip()) \
                        and not lines[i].strip().startswith("**关键词"):
                    if lines[i].strip():
                        buf.append(lines[i].strip())
                    i += 1
                self.abstract = " ".join(buf)
                continue
            if re.match(r"^\*{0,2}关键词\*{0,2}\s*[:：]", s):
                self.keywords = re.sub(r"^\*{0,2}关键词\*{0,2}\s*[:：]\s*", "", s)
                i += 1
                continue

            stripped_body.append(line)
            i += 1

        # 二级/三级标题与段落
        for line in stripped_body:
            s = line.strip()
            if not s or s in ("---", "***", "___"):
                continue
            if s.startswith("## "):
                self.body.append(("h1", s[3:].strip()))
            elif s.startswith("### "):
                self.body.append(("h2", s[4:].strip()))
            elif s.startswith("> "):
                self.body.append(("quote", s[2:].strip()))
            elif s.startswith("|") and s.endswith("|"):
                self.body.append(("table", s))
            else:
                self.body.append(("p", s))


# ------------------------------------------------------------------ 生成

def apply_heading_style(p, level: int) -> None:
    """套用 Word 内置标题样式。

    实测：AI 稿常靠"手动设字体+加粗"模拟标题外观，人工终稿改成真正的
    标题样式（heading 1 / heading 2）。只有用了样式，Word 才能生成目录与
    文档结构图，多数期刊的排版检查也据此进行。
    """
    for name in (f"Heading {level}", f"标题 {level}"):
        try:
            p.style = p.part.document.styles[name]
            return
        except KeyError:
            continue


def build_document(md: Md, profile: str, title: str, author: str,
                   running_head: str, keep_refs: bool):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(3.17)

    fn_texts = md.fn_defs if profile == "footnote" else {}
    has_fn = bool(fn_texts) and HAS_FOOTNOTE_SUPPORT

    # 页眉
    if running_head:
        hp = sec.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = hp.add_run(running_head)
        set_font(r, "楷体", size=9)

    # 标题
    p = add_para(doc, "黑体", SZ_TITLE, align=WD_ALIGN_PARAGRAPH.CENTER,
                 indent=False, after=6)
    add_runs(p, title, "黑体", SZ_TITLE, fn_texts=None)
    if md.subtitle:
        p = add_para(doc, "黑体", SZ_SUBTITLE, align=WD_ALIGN_PARAGRAPH.CENTER,
                     indent=False, after=6)
        add_runs(p, md.subtitle, "黑体", SZ_SUBTITLE)

    # 作者
    p = add_para(doc, "楷体", SZ_AUTHOR, align=WD_ALIGN_PARAGRAPH.CENTER,
                 indent=False, after=18)
    add_runs(p, author or "（作者信息）", "楷体", SZ_AUTHOR)

    # 摘要
    if md.abstract:
        p = add_para(doc, "黑体", SZ_ABSTRACT_HEAD, align=WD_ALIGN_PARAGRAPH.CENTER,
                     indent=False, before=6, after=6)
        add_runs(p, "摘  要", "黑体", SZ_ABSTRACT_HEAD)
        p = add_para(doc, "楷体", SZ_BODY, indent=True, line=1.5)
        add_runs(p, md.abstract, "楷体", SZ_BODY)
    if md.keywords:
        p = add_para(doc, "楷体", SZ_BODY, indent=False, before=6)
        add_runs(p, f"关键词：{md.keywords}", "楷体", SZ_BODY)

    # 正文
    rows: list[list[str]] = []
    for kind, text in md.body:
        if kind == "h1":
            rows = _flush_table(doc, rows)
            p = add_para(doc, "黑体", SZ_H1, indent=False, before=12, after=6)
            add_runs(p, text, "黑体", SZ_H1)
            apply_heading_style(p, 1)
        elif kind == "h2":
            rows = _flush_table(doc, rows)
            p = add_para(doc, "黑体", SZ_H2, indent=False, before=6, after=3)
            add_runs(p, text, "黑体", SZ_H2)
            apply_heading_style(p, 2)
        elif kind == "quote":
            rows = _flush_table(doc, rows)
            p = add_para(doc, "楷体", SZ_BODY, indent=True, before=6, after=6)
            add_runs(p, text, "楷体", SZ_BODY)
        elif kind == "table":
            cells = [c.strip() for c in text.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                continue                      # 表格分隔行
            rows.append(cells)
        else:
            rows = _flush_table(doc, rows)
            p = add_para(doc, "宋体", SZ_BODY, indent=True, line=1.5)
            add_runs(p, text, "宋体", SZ_BODY,
                     fn_texts=fn_texts if has_fn else None)
    _flush_table(doc, rows)

    # 参考文献
    show_refs = md.refs and (profile == "journal" or keep_refs)
    if show_refs:
        p = add_para(doc, "黑体", SZ_REFS_HEAD, align=WD_ALIGN_PARAGRAPH.CENTER,
                     indent=False, before=18, after=6)
        add_runs(p, "参考文献", "黑体", SZ_REFS_HEAD)
        for entry in md.refs:
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.line_spacing = 1.15
            pf.left_indent = Pt(21)
            pf.first_line_indent = Pt(-21)      # 悬挂缩进
            pf.space_after = Pt(2)
            r = p.add_run(entry)
            set_font(r, "宋体", size=SZ_REF)

    # 作者简介（页脚）
    fp = sec.footer.paragraphs[0]
    r = fp.add_run("作者简介：姓名、单位、职务职称、联系电话、电子邮箱")
    set_font(r, "宋体", size=9)

    return doc, fn_texts, has_fn


def _flush_table(doc, rows: list[list[str]]) -> list[list[str]]:
    """把累积的表格行渲染为 Word 表格，返回空列表。"""
    if not rows:
        return []
    cols = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=cols)
    t.style = "Table Grid"
    for row in rows:
        cells = t.add_row().cells
        for i in range(cols):
            txt = row[i] if i < len(row) else ""
            cp = cells[i].paragraphs[0]
            cp.paragraph_format.line_spacing = 1.0
            r = cp.add_run(txt)
            set_font(r, "宋体", size=9)
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Markdown 论文 → 期刊体例 Word")
    ap.add_argument("src", help="Markdown 论文文件")
    ap.add_argument("-o", "--output", default=None, help="输出 .docx 路径")
    ap.add_argument("--profile", choices=["journal", "footnote"], default="journal",
                    help="journal=文末参考文献；footnote=页下脚注")
    ap.add_argument("--title", default=None, help="覆盖题目")
    ap.add_argument("--subtitle", default=None, help="副标题")
    ap.add_argument("--author", default=None, help="作者信息")
    ap.add_argument("--running-head", default=None, help="页眉文字")
    ap.add_argument("--keep-refs", action="store_true",
                    help="footnote 体例下仍保留文末参考文献列表")
    ap.add_argument("--no-normalize-cn", action="store_true",
                    help="不做中文标点规范化（默认会把半角直引号转为全角弯引号）")
    args = ap.parse_args(argv)

    # 依赖检查放在 argparse 之后：这样即使没装 python-docx，`--help` 也能看
    if not HAS_DOCX:
        print("缺少依赖：本脚本需要 python-docx 才能生成 Word。\n"
              "    pip install python-docx\n\n"
              "（其余 10 个脚本无需安装任何包；"
              "`pdf2txt.py` 另需 PyMuPDF 或 pypdf。）", file=sys.stderr)
        return 2


    try:
        with open(args.src, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print(f"无法读取文件：{exc}", file=sys.stderr)
        return 2

    # ---- 中文标点规范化（人工终稿实测：AI 稿 634 处直引号 → 定稿全部为弯引号）
    if not args.no_normalize_cn and HAS_NORMALIZER:
        t, n_dq = _fix_quote_pairs(text)
        t, n_sq = _fix_single_quotes(t)
        t, n_el = _fix_ellipsis(t)
        t, cjk = _fix_cjk_punct(t)
        fixed = n_dq + n_sq + n_el + sum(cjk.values())
        if fixed:
            print(f"🔧 中文标点规范化：直引号 {n_dq}、单引号 {n_sq}、"
                  f"省略号 {n_el}、中文语境半角标点 {sum(cjk.values())}")
        text = t
    elif not args.no_normalize_cn and not HAS_NORMALIZER:
        print("⚠️  未找到 normalize_cn.py，跳过标点规范化"
              "（Word 里可能出现半角直引号）", file=sys.stderr)

    md = Md(text)
    title = args.title or md.meta.get("题目") or md.title or "（论文题目）"
    subtitle = args.subtitle or md.meta.get("副标题", "")
    md.subtitle = subtitle
    author = args.author or md.meta.get("作者", "")
    running_head = args.running_head or md.meta.get("页眉", "")

    if args.profile == "footnote" and not md.fn_defs:
        print("⚠️  指定了 footnote 体例，但正文里没有找到 [^n] 脚注定义。")
        print("   将只生成普通文档（无脚注）。请检查 Markdown 中的脚注写法。")
    if args.profile == "footnote" and not HAS_FOOTNOTE_SUPPORT:
        print("⚠️  环境缺少 lxml，无法注入真脚注。请安装：pip install lxml",
              file=sys.stderr)

    doc, fn_texts, has_fn = build_document(
        md, args.profile, title, author, running_head, args.keep_refs)

    n_inj = 0
    if has_fn:
        n_inj = inject_footnotes(doc, fn_texts)
        attach_footnotes_part(doc, fn_texts)

    out = args.output or (os.path.splitext(args.src)[0] + ".docx")
    doc.save(out)

    print("=" * 60)
    print(f"✅ 已生成：{out}")
    print(f"   体例      ：{'页下脚注' if args.profile == 'footnote' else '文末参考文献'}")
    print(f"   题目      ：{title}")
    print(f"   正文段落  ：{sum(1 for k, _ in md.body if k == 'p')}")
    if args.profile == "footnote" and md.refs and not args.keep_refs:
        print(f"   参考文献  ：{len(md.refs)} 条 —— 脚注体例下已省略文末列表"
              f"（加 --keep-refs 可保留）")
    else:
        print(f"   参考文献  ：{len(md.refs)} 条")
    if has_fn:
        print(f"   脚注定义  ：{len(fn_texts)} 条，正文中共 {n_inj} 处脚注引用")
        used = {int(m.group(1)) for m in
                re.finditer(r"\[\^(\d+)\]", "\n".join(t for _, t in md.body))}
        unused = sorted(set(fn_texts) - used)
        if unused:
            print(f"   ⚠️  以下脚注定义了但正文未引用：{unused}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
