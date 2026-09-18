#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2txt.py —— 把文献 PDF 批量提取为文本（本工作流的标准做法）

## 为什么要有这个脚本

**为了不再"重复造轮子"。** 历史上每开一个新任务窗口，AI 都要重新思考一遍
"这篇 PDF 怎么提取文本"，试库、试参数、试到能用为止——纯浪费时间和 token。

现在固定为一条命令：

    python scripts/pdf2txt.py 文献目录/

## 引擎选择（已实测选定，不要再纠结）

首选 **PyMuPDF**（导入名 `pymupdf`）。实测对比 8 篇真实知网文献：

| 引擎 | 耗时 | 非空白字符 | 汉字 | 警告输出 |
|---|---|---|---|---|
| **PyMuPDF** | **0.71 s** | 25 309 | 16 694 | 无 |
| pypdf | 8.47 s | 25 309 | 16 694 | 有（噪声） |

**内容完全相同**（pypdf 多出的只是空白符），PyMuPDF **快约 12 倍**，且不打印噪声警告。
所以：优先 PyMuPDF；环境没有时自动回退 pypdf。

> ⚠️ 不要用 `import fitz`——PyMuPDF 1.28 起已弃用该名，会打印 DeprecationWarning。
> 用 `import pymupdf`。

## 扫描版 PDF 的处理

没有文本层的 PDF（扫描件）提取出来是空的或只有零星字符。本脚本会按
**每页平均字符数**自动判定并报告，而不是静默产出空文件。

判定阈值（可用 `--min-per-page` 调整）：每页平均 < 80 字符 → 判定为"需 OCR"。

**遇到"需 OCR"的 PDF**：
1. 先用 `pdfkit-py` 的 OCR 功能，或在线 OCR 工具转出文本；
2. 把 txt 保存为与 PDF **同名的 .txt**，放进同一目录；
3. OCR 结果**必须人工抽查**——数字、年份、编号最容易识别错。

## 用法

    # 批量提取目录下所有 PDF（默认与 PDF 同目录，文件名相同、扩展名改 .txt）
    python scripts/pdf2txt.py 文献目录/

    # 只检查，不写文件（先看看哪些是扫描版、需要 OCR）
    python scripts/pdf2txt.py 文献目录/ --check

    # 输出到单独目录
    python scripts/pdf2txt.py 文献目录/ --outdir 文献txt/

    # 指定若干文件
    python scripts/pdf2txt.py a.pdf b.pdf

    # 强制重新提取（默认跳过已提取且比 PDF 新的 txt）
    python scripts/pdf2txt.py 文献目录/ --force

    # 不要分页标记（默认会插入 ===== PAGE n ===== 便于定位页码）
    python scripts/pdf2txt.py 文献目录/ --no-pages

退出码：0 = 全部成功；1 = 有文件需 OCR 或提取失败；2 = 参数/环境错误
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# ---------------------------------------------------------------- 引擎加载

ENGINE = None
ENGINE_NAME = ""


def load_engine():
    """按优先级加载 PDF 引擎。返回 (engine_module, name)。"""
    global ENGINE, ENGINE_NAME
    if ENGINE is not None:
        return ENGINE, ENGINE_NAME
    try:
        import pymupdf  # noqa: PLC0415
        ENGINE, ENGINE_NAME = pymupdf, "pymupdf"
        return ENGINE, ENGINE_NAME
    except ImportError:
        pass
    try:
        import fitz  # noqa: PLC0415
        ENGINE, ENGINE_NAME = fitz, "fitz(PyMuPDF 旧名)"
        return ENGINE, ENGINE_NAME
    except ImportError:
        pass
    try:
        import pypdf  # noqa: PLC0415
        # pypdf 会把 "Multiple definitions in dictionary..." 之类的解析警告
        # 打到控制台，混进我们的报告里。这里把它的日志级别压到 ERROR。
        import logging  # noqa: PLC0415
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        ENGINE, ENGINE_NAME = pypdf, "pypdf"
        return ENGINE, ENGINE_NAME
    except ImportError:
        pass
    return None, ""


def extract_with(engine, name: str, path: str, with_pages: bool):
    """返回 (页数, 文本)。"""
    if name.startswith("pymupdf") or name.startswith("fitz"):
        doc = engine.open(path)
        try:
            pages = doc.page_count
            parts = []
            for i, page in enumerate(doc, 1):
                # sort=False：按 PDF 内部顺序取，避免重排导致行序错乱
                txt = page.get_text(sort=False)
                parts.append(f"\n===== PAGE {i} =====\n{txt}" if with_pages else txt)
            return pages, "".join(parts)
        finally:
            doc.close()
    # pypdf
    reader = engine.PdfReader(path)
    parts = []
    for i, page in enumerate(reader.pages, 1):
        txt = page.extract_text() or ""
        parts.append(f"\n===== PAGE {i} =====\n{txt}" if with_pages else txt)
    return len(reader.pages), "".join(parts)


# ---------------------------------------------------------------- 主流程

def collect_pdfs(inputs: list[str]) -> list[str]:
    files: list[str] = []
    for p in inputs:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(".pdf"):
                    files.append(os.path.join(p, name))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"⚠️  路径不存在：{p}", file=sys.stderr)
    # 去重并保持顺序
    seen, out = set(), []
    for f in files:
        k = os.path.normcase(os.path.abspath(f))
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="批量把文献 PDF 提取为文本（默认 PyMuPDF，自动回退 pypdf）")
    ap.add_argument("inputs", nargs="+", help="PDF 文件或包含 PDF 的目录")
    ap.add_argument("--outdir", default=None, help="输出目录（默认与 PDF 同目录）")
    ap.add_argument("--check", action="store_true",
                    help="只检查（页数/字数/是否需 OCR），不写文件")
    ap.add_argument("--force", action="store_true",
                    help="强制重新提取（默认跳过已提取且比 PDF 新的 txt）")
    ap.add_argument("--min-per-page", type=float, default=80.0,
                    help="判定扫描版的阈值：每页平均字符数低于此值即视为需 OCR"
                         "（默认 80）")
    ap.add_argument("--no-pages", action="store_true",
                    help="不插入 ===== PAGE n ===== 分页标记")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)

    engine, engine_name = load_engine()
    if engine is None:
        print("❌ 未找到可用的 PDF 引擎。请任选其一安装：\n"
              "     pip install pymupdf     # 推荐，快约 12 倍\n"
              "     pip install pypdf       # 备选",
              file=sys.stderr)
        return 2

    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("未找到任何 PDF 文件。", file=sys.stderr)
        return 2

    with_pages = not args.no_pages
    if not args.quiet:
        print("=" * 74)
        print(f"PDF → 文本　引擎：{engine_name}　"
              f"{'（仅检查）' if args.check else ''}")
        print("=" * 74)
        print(f"{'文件':<38}{'页数':>5}{'字数':>8}{'每页':>7}  状态")
        print("-" * 74)

    ok, skipped, need_ocr, failed = 0, 0, 0, 0
    ocr_list: list[str] = []
    t_start = time.perf_counter()

    for path in pdfs:
        base = os.path.basename(path)
        stem = os.path.splitext(base)[0]
        outdir = args.outdir or os.path.dirname(os.path.abspath(path))
        outpath = os.path.join(outdir, stem + ".txt")
        short = base if len(base) <= 36 else base[:34] + "…"

        # 跳过已提取且较新的 txt
        if (not args.force and not args.check and os.path.isfile(outpath)
                and os.path.getmtime(outpath) >= os.path.getmtime(path)):
            if not args.quiet:
                print(f"{short:<38}{'—':>5}{'—':>8}{'—':>7}  ⏭ 已存在，跳过")
            skipped += 1
            continue

        try:
            pages, text = extract_with(engine, engine_name, path, with_pages)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"{short:<38}{'—':>5}{'—':>8}{'—':>7}  ❌ 提取失败：{str(exc)[:26]}",
                  file=sys.stderr)
            continue

        n_chars = len(text.strip())
        per_page = n_chars / pages if pages else 0

        if per_page < args.min_per_page:
            need_ocr += 1
            ocr_list.append(base)
            status = "⚠️ 需 OCR（无文本层）"
            if not args.check:
                # 仍然写出，便于人工确认确实是扫描版
                os.makedirs(outdir, exist_ok=True)
                with open(outpath, "w", encoding="utf-8") as f:
                    f.write(text)
        else:
            ok += 1
            status = "✅ 已提取"
            if not args.check:
                os.makedirs(outdir, exist_ok=True)
                with open(outpath, "w", encoding="utf-8") as f:
                    f.write(text)
            else:
                status = "✅ 可提取"

        if not args.quiet:
            print(f"{short:<38}{pages:>5}{n_chars:>8}{per_page:>7.0f}  {status}")

    elapsed = time.perf_counter() - t_start
    print("-" * 74)
    print(f"共 {len(pdfs)} 个 PDF　成功 {ok}　需 OCR {need_ocr}　"
          f"跳过 {skipped}　失败 {failed}　耗时 {elapsed:.2f}s")

    if ocr_list:
        print(f"\n⚠️  以下 {len(ocr_list)} 个文件没有文本层，需要 OCR：")
        for b in ocr_list[:10]:
            print(f"     · {b}")
        if len(ocr_list) > 10:
            print(f"     … 另有 {len(ocr_list) - 10} 个")
        print("\n   处理方式：用 OCR 工具转出文本，保存为与 PDF 同名的 .txt，"
              "放进同一目录；")
        print("   OCR 结果必须人工抽查——数字、年份、文献编号最容易识别错。")

    if not args.check and ok:
        print(f"\n✅ 文本已就绪。下一步：按 references/04-reading-notes-spec.md 精读，")
        print("   引用前按该项目约定回读原文核验（txt 中的 PAGE 标记可用于定位页码）。")

    return 0 if (need_ocr == 0 and failed == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
