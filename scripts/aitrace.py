#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aitrace.py —— AI 写作痕迹扫描（去 AI 腔）

配套文档：references/11-de-ai-patterns.md

检测七类痕迹：
  ① AI 词汇密度（段落级 ≥ 3 个即告警）
  ② 模糊归因（"学界普遍认为""通说认为"等无出处表述）
  ③ "本文"用法（摘要中出现 = 严重；正文中统计）
  ④ 膨胀词（里程碑式／深远意义／填补空白／开创性 …）
  ⑤ 公式化结论（综上所述／通过上述分析／基于以上讨论）
  ⑥ 标点滥用（破折号、省略号计数与密度）
  ⑦ 段落长度均一度（标准差过小 = 机器生成特征）

用法：
    python aitrace.py 论文正文_XX.md
    python aitrace.py 论文正文_XX.md --density 3 --json 痕迹.json
    python aitrace.py 论文正文_XX.md --quiet

⚠️ 定位工具，不是裁判。是否要改，由人看上下文决定。

退出码：0 = 未发现明显问题；1 = 发现需关注项；2 = 文件错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
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

# ---------------------------------------------------------------- 词表

# AI 高频词
AI_WORDS = [
    "值得注意的是", "综上所述", "毋庸置疑", "应当指出", "不仅如此",
    "具有重要意义", "发挥着重要作用", "提供了重要参考", "具有里程碑意义",
    "深入研究", "系统梳理", "全面分析", "积极意义", "不断完善", "日益凸显",
    "亟待解决", "蓬勃发展", "从根本上说", "不可忽视", "在此基础上",
    "与此同时", "进一步", "极其", "至关重要", "总的来说", "总而言之",
]

# 模糊归因（无出处的笼统归因）
VAGUE_ATTRIBUTION = [
    "学界普遍认为", "学界普遍主张", "学界普遍", "学界认为", "学界已达成共识",
    "通说认为", "按照通说", "一般认为", "通常认为", "多数学者认为",
    "大多数学者认为", "有学者指出", "有学者认为", "有观点认为",
    "主流观点认为", "普遍认为", "众所周知",
]

# 膨胀词：按类别（用正则，容许中间插入定语，如"填补了该领域的研究空白"）
INFLATION = {
    "案例重要性膨胀": [
        r"里程碑式", r"里程碑意义", r"标志性意义", r"标志性判决", r"开创性",
        r"重大突破", r"历史性意义", r"划时代", r"辐射效应", r"示范效应",
    ],
    "政策／理论意义虚高": [
        r"深远的理论与实践意义", r"深远.{0,4}意义", r"理论与实践意义",
        r"重要参考", r"积极意义", r"坚实基础", r"重要价值", r"重大贡献",
        r"重要借鉴", r"有所裨益", r"具有.{0,6}(重大|重要).{0,4}意义",
    ],
    "学术贡献夸大": [
        r"填补.{0,10}空白", r"尚无.{0,6}研究", r"尚无人", r"首次从",
        r"独创", r"开辟.{0,6}新路径", r"率先提出", r"前所未有", r"开创了",
        r"学界.{0,6}(无人|尚未)",
    ],
}

# 公式化结构
FORMULAIC = ["综上所述", "通过上述分析", "基于以上讨论", "由此可知",
             "通过以上分析", "以上分析表明", "如上所述"]

# 填充短语
FILLER = ["在当前的背景下", "在此基础之上", "不可忽视的是", "从某种意义上说",
          "毫无疑问", "不言而喻", "简而言之", "具体来说", "总而言之",
          "在很大程度上", "总的来说"]

ABSTRACT_HEAD_RE = re.compile(r"^#{1,3}\s*摘\s*要\s*$", re.M)
HEADING_RE = re.compile(r"^#{1,6}\s")
REFS_HEAD_RE = re.compile(r"^#{1,3}\s*参考文献\s*$", re.M)
FN_DEF_RE = re.compile(r"^\s*\[\^\d+\]\s*:")
CITE_RE = re.compile(r"\[\d+(?:\s*[-–—]\s*\d+)?(?:\s*[,，]\s*\d+)*\]|\[\^\d+\]")
MD_NOISE_RE = re.compile(r"^(\||>|```|[-*]{3,})")

CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
CJK_CHAR = f"[{CJK}]"

# 中文论文标题编号：应为 一、/（一）/1./（1）
# ⚠️ 必须带 re.M，否则 ^ 只匹配全文开头，检测恒为 0
ARABIC_H1_RE = re.compile(r"^#{2,4}\s*\d+\s+\S", re.M)        # "## 1 数据来源"
ARABIC_H2_RE = re.compile(r"^#{2,4}\s*\d+\.\d+", re.M)        # "### 1.1 数据来源"
CN_H1_RE = re.compile(r"^#{2,4}\s*[一二三四五六七八九十]+、", re.M)
CN_H2_RE = re.compile(r"^#{2,4}\s*（[一二三四五六七八九十]+）", re.M)


# ---------------------------------------------------------------- 工具

def load(path: str) -> str:
    return _read_text_any(path)


def split_abstract(text: str) -> tuple[str, str]:
    """返回 (摘要文本, 其余正文)。"""
    m = ABSTRACT_HEAD_RE.search(text)
    if not m:
        return "", text
    rest = text[m.end():]
    nxt = re.search(r"^#{1,6}\s", rest, re.M)
    if nxt:
        return rest[:nxt.start()], text[:m.start()] + rest[nxt.start():]
    return rest, text[:m.start()]


def get_paragraphs(body: str) -> list[tuple[int, str]]:
    """把正文切成段落，返回 [(行号, 段落文本)]。跳过标题/脚注定义/噪声行。"""
    out = []
    for i, line in enumerate(body.split("\n"), 1):
        s = line.strip()
        if not s or HEADING_RE.match(s) or MD_NOISE_RE.match(s):
            continue
        if FN_DEF_RE.match(s):
            continue
        # 表内单元格行
        if s.count("|") >= 2:
            continue
        out.append((i, s))
    return out


def clean(p: str) -> str:
    return CITE_RE.sub("", p)


def count_hits(text: str, words: list[str]) -> Counter:
    c: Counter = Counter()
    for w in words:
        n = text.count(w)
        if n:
            c[w] += n
    return c


# ---------------------------------------------------------------- 检测

def check_ai_density(paras, threshold: int):
    rows = []
    for ln, p in paras:
        t = clean(p)
        hits = count_hits(t, AI_WORDS)
        total = sum(hits.values())
        if total >= threshold:
            rows.append((ln, total, len(t), dict(hits)))
    return rows


def check_vague(text: str):
    c = count_hits(text, VAGUE_ATTRIBUTION)
    # 合并重复项：只保留最长匹配，避免"学界普遍"与"学界普遍认为"重复计数
    seen: list[tuple[str, int]] = []
    for w, n in c.most_common():
        if any(w in k for k, _ in seen):
            continue
        seen.append((w, n))
    return seen


def check_benwen(abstract: str, body: str):
    abs_hits = re.findall(r"本文", abstract)
    body_n = len(re.findall(r"本文", clean(body)))
    first_person = len(re.findall(r"笔者认为|笔者主张|本人认为", abstract + body))
    return len(abs_hits), body_n, first_person


def check_inflation(text: str):
    """膨胀词检测（正则模式，容许中间插入定语）。"""
    out = {}
    for cat, patterns in INFLATION.items():
        hits = Counter()
        for pat in patterns:
            for m in re.finditer(pat, text):
                hits[m.group(0)] += 1
        if hits:
            out[cat] = hits.most_common()
    return out


def check_punct(text: str):
    """统计标点。注意：只把「——」（双破折号，做插入语）算作破折号。

    不能用 t.count("—")，否则会把「——」里的两个横线各自计一次，
    造成三倍虚高；也会把页码区间「第65—71页」误算成破折号。
    """
    t = clean(text)
    dash = t.count("——")
    ell = t.count("……")
    return dash, ell, len(t)


def check_heading_system(text: str):
    """检查标题编号体系是否为中文规范：一、/（一）/1./（1）。"""
    return {
        "阿拉伯一级(1 )": len(ARABIC_H1_RE.findall(text)),
        "阿拉伯二级(1.1)": len(ARABIC_H2_RE.findall(text)),
        "中文一级(一、)": len(CN_H1_RE.findall(text)),
        "中文二级(（一）)": len(CN_H2_RE.findall(text)),
    }


def check_punct_cn(text: str):
    """中文标点规范检查（对齐人工终稿习惯）。"""
    return {
        "半角直双引号": text.count('"'),
        "中文语境半角逗号": len(re.findall(f"(?<={CJK_CHAR}),(?={CJK_CHAR})", text)),
        "中文语境半角句号": len(re.findall(f"(?<={CJK_CHAR})\\.(?={CJK_CHAR})", text)),
        "半角省略号(...)": len(re.findall(r"\.{3,}", text)),
    }


def check_uniformity(paras):
    lens = [len(clean(p)) for _, p in paras]
    lens = [x for x in lens if x >= 30]
    if len(lens) < 5:
        return None
    mean = statistics.mean(lens)
    sd = statistics.pstdev(lens)
    cv = sd / mean if mean else 0
    return mean, sd, cv, lens


# ---------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI 写作痕迹扫描（去 AI 腔）")
    ap.add_argument("file", help="论文 Markdown 文件")
    ap.add_argument("--density", type=int, default=3,
                    help="段落 AI 词汇密度告警阈值（默认 3）")
    ap.add_argument("--json", default=None, help="另存 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.file):
        print(f"无法读取文件：{args.file}", file=sys.stderr)
        return 2

    text = load(args.file)
    # 只扫正文：去掉参考文献区
    rm = REFS_HEAD_RE.search(text)
    scan_text = text[:rm.start()] if rm else text

    abstract, body = split_abstract(scan_text)
    paras = get_paragraphs(body)
    # 摘要作为一个独立段落参与扫描（行号 0 代表摘要）
    if abstract.strip():
        paras = [(0, re.sub(r"\s+", " ", abstract).strip())] + paras
    # 文本级检测覆盖摘要 + 正文——AI 腔最爱藏在摘要里
    all_text = abstract + "\n" + body
    body_clean = clean(all_text)

    density = check_ai_density(paras, args.density)
    vague = check_vague(body_clean)
    abs_bw, body_bw, first_person = check_benwen(abstract, body)
    infl = check_inflation(body_clean)
    formula = count_hits(body_clean, FORMULAIC)
    filler = count_hits(body_clean, FILLER)
    dash, ell, char_n = check_punct(all_text)
    uni = check_uniformity(paras)
    heads = check_heading_system(scan_text)
    punct_cn = check_punct_cn(all_text)

    severe, warn = [], []

    if abs_bw > 0:
        severe.append(f"摘要中出现「本文」{abs_bw} 次 —— 法学核心期刊摘要严禁使用")
    if first_person > 0:
        severe.append(f"出现第一人称表述（笔者认为／笔者主张／本人认为）{first_person} 次")
    if density:
        severe.append(f"{len(density)} 个段落的 AI 词汇密度 ≥ {args.density}")
    if vague:
        warn.append(f"模糊归因 {sum(n for _, n in vague)} 处（需逐条补出处或改写）")
    if infl:
        tot = sum(n for lst in infl.values() for _, n in lst)
        warn.append(f"膨胀词 {tot} 处（涉及 {len(infl)} 类）")
    if formula:
        warn.append(f"公式化表述 {sum(formula.values())} 处")
    if filler:
        warn.append(f"填充短语 {sum(filler.values())} 处")
    if body_bw > 3:
        warn.append(f"正文中「本文」出现 {body_bw} 次（正文可用，但过多显机械）")
    if char_n and dash / max(1, char_n / 1000) > 8:
        warn.append(f"破折号（——）{dash} 处，密度偏高"
                    f"（每千字 {dash / (char_n / 1000):.1f} 处）")
    if punct_cn["半角直双引号"]:
        severe.append(f"半角直引号 {punct_cn['半角直双引号']} 处"
                      f" —— 中文论文必须用全角弯引号“ ”"
                      f"（跑 normalize_cn.py 可自动修正）")
    cjk_punct = punct_cn["中文语境半角逗号"] + punct_cn["中文语境半角句号"] \
        + punct_cn["半角省略号(...)"]
    if cjk_punct:
        warn.append(f"中文语境半角标点/省略号 {cjk_punct} 处（建议 normalize_cn.py）")
    if heads["阿拉伯一级(1 )"] or heads["阿拉伯二级(1.1)"]:
        warn.append(
            f"标题编号用的是阿拉伯体系（一级 {heads['阿拉伯一级(1 )']} 处、"
            f"二级 {heads['阿拉伯二级(1.1)']} 处）—— "
            f"**请核对目标期刊稿约**：情报计量类与实务类刊物常用阿拉伯体系，"
            f"法学专业刊常用「一、/（一）」。全篇不得混用两套体系。")
    if uni and uni[2] < 0.35:
        warn.append(f"段落长度过于均匀（变异系数 {uni[2]:.2f}），是机器生成特征")

    issues = len(severe) + len(warn)

    if not args.quiet:
        print("=" * 66)
        print(f"AI 写作痕迹扫描：{os.path.basename(args.file)}")
        print("=" * 66)
        if uni:
            print(f"段落数 {len(paras)}    平均段长 {uni[0]:.0f} 字    "
                  f"标准差 {uni[1]:.0f}    变异系数 {uni[2]:.2f}")
        print()

        print(f"── ① AI 词汇密度（阈值 每段 ≥ {args.density} 个）──")
        if not density:
            print("  ✅ 未发现高密度段落")
        else:
            for ln, total, length, hits in density:
                detail = "、".join(f"{w}×{n}" for w, n in
                                   sorted(hits.items(), key=lambda x: -x[1]))
                where = "摘要" if ln == 0 else f"第 {ln} 行"
                print(f"  ⚠️  {where}（{length} 字）共 {total} 个：{detail}")
        print()

        print("── ② 模糊归因 ──")
        if not vague:
            print("  ✅ 未发现无出处的笼统归因")
        else:
            for w, n in vague:
                print(f"  ⚠️  「{w}」× {n}  → 归因到具体学者+文献+页码")
        print()

        print("── ③ 「本文」与第一人称 ──")
        if abs_bw == 0 and body_bw == 0 and first_person == 0:
            print("  ✅ 未使用「本文」，无第一人称")
        else:
            if abs_bw:
                print(f"  ❌ 摘要：「本文」× {abs_bw}  ← 严重，必须删除")
            if body_bw:
                print(f"  ⚠️  正文：「本文」× {body_bw}")
            if first_person:
                print(f"  ❌ 第一人称表述 × {first_person}")
        print()

        print("── ④ 膨胀词 ──")
        if not infl:
            print("  ✅ 未发现")
        else:
            for cat, lst in infl.items():
                detail = "、".join(f"{w}×{n}" for w, n in lst)
                print(f"  ⚠️  {cat}：{detail}")
        print()

        print("── ⑤ 公式化结论／填充短语 ──")
        if not formula and not filler:
            print("  ✅ 未发现")
        else:
            for w, n in formula.most_common():
                print(f"  ⚠️  公式化：「{w}」× {n}")
            for w, n in filler.most_common():
                print(f"  ⚠️  填充语：「{w}」× {n}")
        print()

        print("── ⑥ 标点 ──")
        rate = dash / (char_n / 1000) if char_n else 0
        print(f"  破折号（——）{dash} 处（每千字 {rate:.1f} 处）    "
              f"省略号（……）{ell} 处    正文 {char_n} 字")
        print("  说明：破折号密度**因文体而异**。思辨／文本分析类论文用破折号做解释性插入")
        print("        是正常笔法，不必强压。此处仅作提示，不构成修改要求。")
        print()

        print("── ⑦ 中文标点规范 ──")
        pc = punct_cn
        if not any(pc.values()):
            print("  ✅ 引号与标点规范")
        else:
            if pc["半角直双引号"]:
                print(f"  ❌ 半角直引号 {pc['半角直双引号']} 处"
                      f"  ← 实测人工终稿会把全部直引号改为“ ”")
            if pc["中文语境半角逗号"]:
                print(f"  ⚠️  中文语境半角逗号 {pc['中文语境半角逗号']} 处")
            if pc["中文语境半角句号"]:
                print(f"  ⚠️  中文语境半角句号 {pc['中文语境半角句号']} 处")
            if pc["半角省略号(...)"]:
                print(f"  ⚠️  半角省略号 {pc['半角省略号(...)']} 处 → 应为 ……")
            print("     修正：python scripts/normalize_cn.py <文件>")
        print()

        print("── ⑧ 标题编号体系 ──")
        h = heads
        if h["中文一级(一、)"] or h["中文二级(（一）)"]:
            print(f"  当前：中文体系（一级 {h['中文一级(一、)']} 处、"
                  f"二级 {h['中文二级(（一）)']} 处）")
        if h["阿拉伯一级(1 )"] or h["阿拉伯二级(1.1)"]:
            print(f"  当前：阿拉伯体系（一级 {h['阿拉伯一级(1 )']} 处、"
                  f"二级 {h['阿拉伯二级(1.1)']} 处）")
        if (h["中文一级(一、)"] or h["中文二级(（一）)"]) and \
           (h["阿拉伯一级(1 )"] or h["阿拉伯二级(1.1)"]):
            print("  ❌ **混用两套体系**——这一条是硬性的，必须统一")
        elif h["阿拉伯一级(1 )"] or h["阿拉伯二级(1.1)"]:
            print("  ℹ️  阿拉伯体系不是错误：请核对目标期刊稿约。")
            print("      情报计量类/实务类刊物常用 1 / 1.1；")
            print("      法学专业刊常用 一、/（一）。")
        else:
            print("  ✅ 中文编号体系，全篇一致")
        print()

        print("=" * 66)
        if issues == 0:
            print("✅ 扫描通过：未发现明显 AI 写作痕迹。")
        else:
            print(f"⚠️  发现 严重 {len(severe)} 项 / 提示 {len(warn)} 项")
            for s in severe:
                print(f"   ❌ {s}")
            for w in warn:
                print(f"   ⚠️  {w}")
            print()
            print("   处理原则：改写而非删词。空泛处用**具体内容**替换，")
            print("   模糊归因补上**具体文献与页码**。详见 references/11-de-ai-patterns.md")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({
                "file": args.file,
                "paragraph_count": len(paras),
                "density_hits": [{"line": ln, "count": t, "length": l,
                                  "words": h} for ln, t, l, h in density],
                "vague_attribution": [{"phrase": w, "count": n} for w, n in vague],
                "benwen": {"abstract": abs_bw, "body": body_bw},
                "first_person": first_person,
                "inflation": infl,
                "formulaic": dict(formula),
                "filler": dict(filler),
                "punct": {"dash": dash, "ellipsis": ell, "chars": char_n},
                "uniformity": ({"mean": round(uni[0], 1), "sd": round(uni[1], 1),
                                "cv": round(uni[2], 3)} if uni else None),
                "heading_system": heads,
                "punct_cn": punct_cn,
                "severe": severe,
                "warn": warn,
            }, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 已写入：{args.json}")

    return 0 if issues == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
