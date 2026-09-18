#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
redundancy.py —— 文稿体检：车轱辘话 / 超长句 / 段落臃肿 / 篇幅总账

为什么需要它：
  论文写得"垃圾"，很多时候不是论点错，而是文字在**自我重复**——
  同一层意思换几种说法讲三遍（俗称"车轱辘话"），句子长到读者要断气，
  段落里五层信息挤在一个自然段。这些问题人眼通读时会被自动补全，
  读起来"还行"，但审稿人一看就烦。

  本脚本用机械手段把它们标出来，让修订有据可依，而不是凭感觉"润色"。

用法：
    python redundancy.py 论文正文_XX.md
    python redundancy.py 论文正文_XX.md --threshold 0.6 --max-sentence 90
    python redundancy.py 论文正文_XX.md --json 体检.json

退出码：0 = 未发现明显问题；1 = 发现需关注项；2 = 文件错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

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

CITE_RE = re.compile(r"\[\d+(?:\s*[-–—]\s*\d+)?(?:\s*[,，]\s*\d+)*\]")
FN_REF_RE = re.compile(r"\[\^\d+\]")
# 脚注定义行：[^1]: 参见某某……
FN_DEF_RE = re.compile(r"^\s*\[\^\d+\]\s*:")
MD_NOISE_RE = re.compile(r"^(#|\||>|```|[-*]{3,})")

# 标点与空白（含中英文全角/半角、直引号与弯引号）——全部用转义，避免引号嵌套问题
_PUNCT_CHARS = (
    r"\s\u3000"
    r"\u3002\u3001\uff0c\uff1b\uff1a\uff01\uff1f"      # 。、，；：！？
    r"\uff08\uff09\u300a\u300b\u3008\u3009\u3010\u3011"
    r"\u201c\u201d\u2018\u2019\u00ab\u00bb\u2014\u2013\u2026\u00b7"
    r"\[\]\(\)\-~\.,!?;:'\""
)
PUNCT_RE = re.compile("[" + _PUNCT_CHARS + "]+")

# 常见填充语（套话／口头禅）。这些词一多，文章就显得空转。
FILLER_PATTERNS = [
    (r"值得注意的是", "值得注意的是"),
    (r"需要指出的是|需要说明的是", "需要指出/说明的是"),
    (r"不难(看出|发现|理解)", "不难看出/发现"),
    (r"显而易见|不言而喻", "显而易见/不言而喻"),
    (r"换言(之|句话)", "换言之/换句话说"),
    (r"从这个?(意义|角度)(上|来说|看)", "从这个意义上/角度"),
    (r"就此而言|就前述而言", "就此而言"),
    (r"综上所述|一言以蔽之|总而言之|归根结底", "综上所述/归根结底"),
    (r"由此可见", "由此可见"),
    (r"如前所述|上文已述|如前文所述", "如前所述"),
    (r"本章将|本节将|下文将|本文将", "本章/本节/本文将"),
    (r"在一定程度上|从某种意义上", "在一定程度上"),
    (r"事实上|实际上", "事实上/实际上"),
]


def load_body(path: str) -> tuple[str, str]:
    text = _read_text_any(path)
    idx = text.find("## 参考文献")
    if idx < 0:
        return text, ""
    return text[:idx], text[idx:]


def strip_footnote_defs(body: str) -> str:
    """移除脚注定义行。

    脚注是引证装置，不是正文散文。同一文献在不同脚注里出现（页码不同）
    是正确做法，若纳入会全部被误判为"车轱辘话"。
    """
    return "\n".join(l for l in body.split("\n") if not FN_DEF_RE.match(l))


def split_sentences(body: str) -> list[str]:
    body = strip_footnote_defs(body)
    out: list[str] = []
    for line in body.split("\n"):
        s = line.strip()
        if not s or MD_NOISE_RE.match(s):
            continue
        if s.startswith("#"):
            continue
        for part in re.split(r"(?<=[。！？；])", s):
            part = part.strip()
            if part:
                out.append(part)
    return out


def normalize(s: str) -> str:
    s = CITE_RE.sub("", s)
    s = FN_REF_RE.sub("", s)
    s = re.sub(r"\*\*|`", "", s)
    return PUNCT_RE.sub("", s)


def find_near_duplicates(sentences: list[str], threshold: float,
                        min_len: int = 20, top: int = 15):
    """找出语义高度重叠的句子对。先按字符集预筛，再做相似度计算。"""
    norm = []
    for s in sentences:
        n = normalize(s)
        if len(n) >= min_len:
            norm.append((s, n, set(n)))

    pairs = []
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            a_raw, a, sa = norm[i]
            b_raw, b, sb = norm[j]
            # 预筛：字符集 Jaccard 太低就跳过，避免 O(n²) 全量比对
            inter = len(sa & sb)
            if inter == 0:
                continue
            jac = inter / len(sa | sb)
            if jac < threshold - 0.25:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            combined = max(ratio, jac)
            if combined >= threshold:
                pairs.append((combined, a_raw, b_raw))
    pairs.sort(key=lambda x: -x[0])
    return pairs[:top]


def find_filler(body: str, top: int = 12):
    """统计填充语（连接词／口头禅）。这些词密集出现，说明文字在空转。"""
    out = []
    for pattern, label in FILLER_PATTERNS:
        c = len(re.findall(pattern, body))
        if c >= 3:
            out.append((label, c))
    out.sort(key=lambda x: -x[1])
    return out[:top]


def find_repeated_chunks(sentences: list[str], size: int = 10,
                         min_count: int = 3, top: int = 10):
    """找出反复出现的长片段（≥10 字、≥3 次）。

    只看长片段：学科术语通常不超过 6 字，反复出现是正常的；
    而 10 字以上的串重复三次，几乎必然是复制粘贴的句子残片。
    """
    counter: Counter = Counter()
    for s in sentences:
        n = normalize(s)
        for k in range(len(n) - size + 1):
            counter[n[k:k + size]] += 1
    repeats = [(g, c) for g, c in counter.items() if c >= min_count]
    repeats.sort(key=lambda x: (-x[1], -len(x[0])))
    kept: list[tuple[str, int]] = []
    for g, c in repeats:
        if any(g in k or k in g for k, _ in kept):
            continue
        kept.append((g, c))
        if len(kept) >= top:
            break
    return kept


def paragraph_stats(body: str, limit: int):
    paras = [l.strip() for l in body.split("\n")
             if l.strip() and not MD_NOISE_RE.match(l.strip())
             and not l.strip().startswith("#")]
    lengths = [len(normalize(p)) for p in paras]
    bloated = [(len(normalize(p)), p) for p in paras
               if len(normalize(p)) > limit]
    bloated.sort(key=lambda x: -x[0])
    return paras, lengths, bloated


def section_stats(body: str):
    stats = []
    cur, buf = "（前言）", []
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("## "):
            if buf:
                stats.append((cur, sum(len(normalize(x)) for x in buf)))
            cur, buf = s[3:].strip(), []
        elif s and not MD_NOISE_RE.match(s):
            buf.append(s)
    if buf:
        stats.append((cur, sum(len(normalize(x)) for x in buf)))
    return stats


def version_curve(files: list[str]) -> int:
    """多版本体检：打印字数曲线，并对剧烈波动报警。

    经验值：健康的迭代是**平稳增长或小幅波动**。
    若某一版字数比上一版跌去 40% 以上，通常不是"精简"，而是**结构塌方**——
    说明论题或框架出了问题，此时应停下来重审论题，而不是继续打补丁。
    """
    print("=" * 66)
    print("版本曲线体检")
    print("=" * 66)
    rows = []
    for path in files:
        body, _ = load_body(path)
        body = strip_footnote_defs(body)
        sents = split_sentences(body)
        rows.append((os.path.basename(path),
                     sum(len(normalize(s)) for s in sents),
                     len(sents)))
    base = max(1, max(r[1] for r in rows))
    prev = None
    warns = 0
    for name, n, sc in rows:
        bar = "█" * max(1, round(n / base * 40))
        delta = ""
        if prev is not None:
            pct = (n - prev) / max(1, prev) * 100
            delta = f"{pct:+6.1f}%"
            if pct <= -40:
                delta += "  ⚠️ 结构塌方嫌疑"
                warns += 1
        prev = n
        print(f"  {name[:34]:<36} {n:>6} 字 {delta:>10}  {bar}")
    print("-" * 66)
    print(f"  版本数：{len(rows)}")
    if warns:
        print(f"  ⚠️  {warns} 处跌幅超过 40%。")
        print("     请**先重审核心论题是否清晰、章节框架是否自洽**，")
        print("     再决定是否继续修订。切忌用字符串替换式补丁硬撑。")
    else:
        print("  ✅ 字数曲线平稳，无结构塌方迹象。")
    print()
    return warns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="文稿体检：车轱辘话 / 超长句 / 段落臃肿 / 版本健康度")
    ap.add_argument("files", nargs="+", help="论文 Markdown 文件（可给多个版本以绘制曲线）")
    ap.add_argument("--threshold", type=float, default=0.65,
                    help="近似重复句的相似度阈值（0—1，默认 0.65）")
    ap.add_argument("--max-sentence", type=int, default=150,
                    help="超长句字数阈值（默认 150）。"
                         "⚠️ 不要设低于 120——实测 4 篇已发表论文的平均句长 46.7 字、"
                         "90 分位 89 字、最长 198 字，>100 字占 6%%（属正常文风）")
    ap.add_argument("--max-paragraph", type=int, default=500,
                    help="臃肿段落字数阈值（默认 500）")
    ap.add_argument("--baseline", type=float, default=None,
                    help="你的平均句长基线（实测已发表论文约 47）。"
                         "给了会据此判断本次是否明显偏离常态")
    ap.add_argument("--json", default=None, help="把结果另存为 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args(argv)

    for path in args.files:
        if not os.path.isfile(path):
            print(f"无法读取文件：{path}", file=sys.stderr)
            return 2

    curve_warns = 0
    if len(args.files) > 1:
        curve_warns = version_curve(args.files)

    # 单文件体检：多版本时只体检最后一个（通常是最新版）
    args.file = args.files[-1]

    if not os.path.isfile(args.file):
        print(f"无法读取文件：{args.file}", file=sys.stderr)
        return 2

    body, _refs = load_body(args.file)
    body = strip_footnote_defs(body)          # 脚注装置不参与散文体检
    sentences = split_sentences(body)
    total = sum(len(normalize(s)) for s in sentences)

    dups = find_near_duplicates(sentences, args.threshold)
    long_sents = sorted(((len(normalize(s)), s) for s in sentences
                         if len(normalize(s)) > args.max_sentence),
                        key=lambda x: -x[0])
    _paras, _lens, bloated = paragraph_stats(body, args.max_paragraph)
    filler = find_filler(body)
    chunks = find_repeated_chunks(sentences)
    sections = section_stats(body)

    issues = len(dups) + len(long_sents) + len(bloated) + len(filler) + len(chunks)

    if not args.quiet:
        print("=" * 66)
        print(f"文稿体检：{os.path.basename(args.file)}")
        print("=" * 66)
        print(f"正文字数（去标点）: {total}")
        print(f"句子总数          : {len(sentences)}")
        avg = total / max(1, len(sentences))
        print(f"平均句长          : {avg:.1f} 字"
              + (f"（你的基线 {args.baseline:.1f}）" if args.baseline else ""))
        # 句长分布——用于对照自己的已发表基线，而不是套用别人的标准
        lens = sorted(len(normalize(s)) for s in sentences)
        if lens:
            p = lambda q: lens[min(len(lens) - 1, int(len(lens) * q))]  # noqa: E731
            print(f"句长分布          : 中位 {p(0.5)} / 75分位 {p(0.75)} / "
                  f"90分位 {p(0.90)} / 最长 {lens[-1]} 字")
            over100 = sum(1 for x in lens if x > 100)
            print(f"                    >100字 {over100} 句（{over100/len(lens)*100:.0f}%）")
            if args.baseline:
                dev = (avg - args.baseline) / args.baseline * 100
                flag = "✅ 与基线接近" if abs(dev) <= 20 else "⚠️ 明显偏离基线"
                print(f"                    {flag}（{dev:+.0f}%）")
        print()

        print("── 篇幅总账（按章）──")
        for name, n in sections:
            bar = "█" * max(1, round(n / 200))
            print(f"  {name[:28]:<30} {n:>6}  {bar}")
        print()

        print(f"── ① 近似重复句（相似度 ≥ {args.threshold}）——车轱辘话 ──")
        if not dups:
            print("  ✅ 未发现明显重复句")
        else:
            for score, a, b in dups:
                print(f"  ⚠️  相似度 {score:.2f}")
                print(f"      A: {a[:70]}{'…' if len(a) > 70 else ''}")
                print(f"      B: {b[:70]}{'…' if len(b) > 70 else ''}")
        print()

        print(f"── ② 超长句（>{args.max_sentence} 字）──")
        if not long_sents:
            print("  ✅ 未发现超长句")
        else:
            for n, s in long_sents[:10]:
                print(f"  ⚠️  {n} 字：{s[:60]}…")
            print(f"  说明：长句本身不是缺点。实测 4 篇已发表论文平均句长 46.7 字、")
            print(f"        90 分位 89 字、最长 198 字，逾 100 字的句子占 6%，均为正常文风。")
            print(f"        只有明显失控（一句套三个以上分句且主语多次转换）才需拆。")
        print()

        print(f"── ③ 臃肿段落（>{args.max_paragraph} 字）──")
        if not bloated:
            print("  ✅ 未发现臃肿段落")
        else:
            for n, p in bloated[:8]:
                head = p[:40]
                print(f"  ⚠️  {n} 字：{head}…（建议按层次拆段）")
        print()

        print("── ④ 填充语（连接词／口头禅，出现 ≥ 3 次）──")
        if not filler:
            print("  ✅ 未发现密集填充语")
        else:
            for label, c in filler:
                print(f"  ⚠️  {label} × {c}")
            print("     填充语密集出现，通常意味着文字在空转而非推进论证。")
        print()

        print("── ⑤ 重复长片段（≥10 字、出现 ≥ 3 次）──")
        if not chunks:
            print("  ✅ 未发现重复长片段")
        else:
            for g, c in chunks:
                print(f"  ⚠️  ×{c}：{g}")
        print()

        print("=" * 66)
        if issues == 0:
            print("✅ 体检通过：未发现车轱辘话、超长句、臃肿段落、填充语或重复片段。")
        else:
            print(f"⚠️  共发现 {issues} 处需关注项"
                  f"（重复句 {len(dups)} / 超长句 {len(long_sents)} / "
                  f"臃肿段落 {len(bloated)} / 填充语 {len(filler)} / "
                  f"重复片段 {len(chunks)}）")
            print("   处理原则：**整段重写，不要做字符串替换式打补丁。**")
            print("   同一层意思只讲一遍；长句拆成短句；段落只承载一层信息。")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({
                "file": args.file,
                "char_count": total,
                "sentence_count": len(sentences),
                "avg_sentence_len": round(total / max(1, len(sentences)), 1),
                "sections": [{"name": n, "chars": c} for n, c in sections],
                "near_duplicates": [{"score": round(s, 3), "a": a, "b": b}
                                    for s, a, b in dups],
                "long_sentences": [{"chars": n, "text": s}
                                   for n, s in long_sents],
                "bloated_paragraphs": [{"chars": n, "text": p[:200]}
                                       for n, p in bloated],
                "filler_phrases": [{"phrase": g, "count": c} for g, c in filler],
                "repeated_chunks": [{"chunk": g, "count": c} for g, c in chunks],
            }, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 已写入：{args.json}")

    return 0 if (issues == 0 and curve_warns == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
