#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mk_review_packet.py —— 生成「跨窗口审稿任务包」

## 为什么要这个脚本

本工作流的审稿环节在**独立的窗口**里做，并且**用更强的模型**。这不是偶然做法，而是设计：

  1. **窗口隔离 = 视角隔离。** 写作窗口里堆满了写作启动包、精读笔记、修改理由……
     同一个窗口读稿，会不自觉地替自己辩护，看不见盲点。
     真实审稿人只看到一份稿件——**隔离才是审稿人视角的前提**。
  2. **换更贵的模型 = 换一套判断。** 起草可以用快模型，但审稿要求"挑错"，
     需要更强的推理能力，也更值得投入。

  窗口隔离带来一个硬性要求：**交接只能靠文件**。所以必须先把稿件清干净，
  连同审稿指令一起打包，带到另一个窗口去。

## 清洗什么

原稿里带着大量**只有作者才该看到**的东西，审稿窗口不应该看到：

  - 元信息块（`> 题目：…` `> 写作状态：全文初稿 v3·编号定稿` `> 目标篇幅：…`）
  - 内部文件标题（`# 论文正文_XX（全文 v5）`）
  - HTML 注释（`<!-- 待核 -->`）
  - 作者信息、基金项目（如要匿名评审）

## 用法

    # 生成第 1 轮审稿包（默认保留 [待核] 标记，好让"审稿人"抓出来）
    python mk_review_packet.py 论文正文_XX_v5.md --round 1

    # 匿名评审
    python mk_review_packet.py 论文正文_XX_v5.md --round 1 --anonymize

    # 连 [待核] 标记一并清掉（模拟真实审稿人看不到任何标记的情形）
    python mk_review_packet.py 论文正文_XX_v5.md --round 1 --strip-todo

输出：
    审稿稿_M1.md          干净的稿件（交给另一个窗口）
    审稿任务说明_M1.md     给审稿窗口的指令 + 检查清单
"""

from __future__ import annotations

import argparse
import os
import re
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

# 只有作者该看到的元信息键
META_KEYS = [
    "题目", "副标题", "作者", "基金项目", "引注体例", "篇幅", "目标期刊",
    "页眉", "写作状态", "篇幅目标", "字数目标", "评审轮次",
    "说明", "备注", "写作说明", "版本", "轮次", "日期", "字数",
]

META_LINE_RE = re.compile(
    r"^>\s*(" + "|".join(META_KEYS) + r")\s*[:：]\s*(.*)$")

# 内部文件标题： # 论文正文_XX（全文 v5）
INTERNAL_H1_RE = re.compile(r"^#\s*论文正文[^\n]*$", re.M)

# 其它内部标记
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TODO_RE = re.compile(r"\[(待核|待补|需用户核实|待确认|TODO)\]")
PLACEHOLDER_RE = re.compile(r"【(新京报|广州日报|[^】]{1,12})】")
STATUS_LINE_RE = re.compile(r"^\s*(状态|写作状态)\s*[:：].*$", re.M)

REVIEW_INSTRUCTIONS = """# 审稿任务说明（第 {round_no} 轮）

> 本文件是**任务说明**，请连同 `{manuscript}` 一起交给审稿窗口。

## 一、你的身份

你是**目标期刊的外审专家**，不是本文的合作者。

**你有且仅有以下材料**：

- `{manuscript}`（稿件全文）
{extra_materials}

**你没有被提供、并且不应当索要的材料**：

- ❌ 写作启动包（里面写着作者的论证意图）
- ❌ 文献筛选清单、文献精读笔记
- ❌ 作者与 AI 的对话记录、修改理由、版本对比
- ❌ 此前的审稿意见

> 之所以不给你这些，是因为**真实的审稿人也没有**。
> 如果你需要读到作者的"意图说明"才能理解某段论证，那这段论证在稿件里就是失败的——
> 这正是你要指出的问题。

## 二、你的任务

通读稿件，出具一份审稿意见报告。**以挑错为目的，不以确认为目的。**

### 必查的四类"低级但致命"问题

1. **事实性硬伤**：地名/机构归属、年份、案例归属、人物职务。
   方法：把全文所有地名、机构名、案例名抽出来，逐个核对上级归属与准确性。
2. **口径混淆**：地方数据 vs 国家数据、不同时点数据混用、统计范围不同。
   方法：每组数据问三个问题——谁的？什么时候的？统计口径是什么？
3. **引注不达标**：缺起止页码、缺发布日期或网址、正文引用的政策文件未列入参考文献、
   刊名错误、重号、跳号、正文编号与文末列表不一一对应。
4. **数值嫁接**：把两个不同基准的巧合数字说成"恰相对应/正好印证"。
   方法：全文搜索"恰/正好/恰好/相对应/相吻合/印证"，逐个复核。

### 同时评估的维度

| 维度 | 权重 | 看什么 |
|---|---|---|
| 选题价值 | 25% | 是真问题吗？有无现实/理论意义？是否同质化？ |
| 论证质量 | 25% | 逻辑链是否完整？有无"结论先于证据"？有无跳步？ |
| 创新性 | 20% | 有无知识增量？是否只是文献搬运？ |
| 文献质量 | 15% | 是否覆盖重要文献？有无遗漏关键对手？引注是否规范？ |
| 表达规范 | 15% | 结构、术语一致性、有无 AI 腔与空转语言 |

### 语言层面另外留意

- 摘要是否 200—300 字、单段、**有没有出现"本文"**（法学核心期刊严禁）
- 是否说大话（"里程碑式""具有深远意义""填补空白"）
- 是否模糊归因（"学界普遍认为""通说认为"却不给具体文献）
- 是否公式化结论（"综上所述"反复出现）
- 是否车轱辘话（同一层意思换几种说法讲三遍）
- 是否有超长句（>100 字）、臃肿段落（>500 字）

## 三、输出格式（必须遵守）

按以下格式逐条输出，**每条必须有五要素**：

```markdown
### 问题N【类别·严重度】一句话标题

- **位置**：第X章（X），第NN行
- **原文**："……被引用的原句……"
- **问题**：为什么这是问题（说清道理，不要只说"不好"）
- **修改方案**：给出**可直接替换的完整文字**
  > "……"
- **依据**：为什么这么改（引用文献/文件/规范）
```

**关键要求**：

- `修改方案` 必须给出**可直接替换的完整文字**，而不是"建议进一步论证"这类空话。
  作者拿到意见后应该能直接动手。
- 按优先级排序，并在报告开头给出**总体评价与打分**。
- 报告末尾写明 **"审稿人特别提醒"**：一句话点出最致命的 2—3 处，说明为什么它们优先级最高。
- 报告末尾另起一节 **"给原作 AI 的执行提示"**：把意见转化为明确的动作序列。

## 四、最后一步：落盘

把报告写成文件 `审稿意见_M{round_no}.md`，放在稿件同目录。

> 这一步不可省。因为你在**独立窗口**里工作，**文件是唯一的交接方式**——
> 不落盘，你的判断就传不回写作窗口。

## 五、不许做的事

- ❌ 不要修改稿件本身，只出意见
- ❌ 不要因为"作者可能是对的"就放过可疑处；有疑问就写出来
- ❌ 不要编造你无法核实的事实来支持或反驳稿件
- ❌ 不要泛泛而谈（"论证还可以更扎实"是无用意见）
"""


def unwrap_title(t: str) -> str:
    """只在标题被书名号**整体包裹**时去掉书名号。

    不能简单用 strip("《》")：那会把《示例》"某某"概念探析——…
    开头的书名号一并啃掉（因为结尾不是》）。
    """
    t = (t or "").strip()
    if len(t) > 2 and t.startswith("《") and t.endswith("》"):
        return t[1:-1].strip()
    return t


def load(path: str) -> str:
    return _read_text_any(path)


def clean_manuscript(text: str, anonymize: bool, strip_todo: bool):
    """返回 (清洗后的稿件, 提取到的题目, 清洗日志)。"""
    log: list[str] = []
    lines = text.split("\n")

    meta_seen: dict[str, str] = {}
    internal_h1 = 0
    first_h1 = ""
    body_lines: list[str] = []
    seen_section = False          # 是否已进入正文（遇到第一个 ## 小节）

    for line in lines:
        s = line.strip()
        if not seen_section:
            m = META_LINE_RE.match(s)
            if m:
                meta_seen[m.group(1)] = m.group(2).strip()
                continue
            if INTERNAL_H1_RE.match(s):
                internal_h1 += 1
                continue
            if s.startswith(">"):
                continue            # 文件头部的说明性引用行
            if s.startswith("# ") and not s.startswith("## "):
                # 头部的一级标题：记下文本备用，但先移除（题目统一从元信息取）
                if not first_h1:
                    first_h1 = s[2:].strip()
                internal_h1 += 1
                continue
            if s.startswith("## "):
                seen_section = True
        body_lines.append(line)

    body_text = "\n".join(body_lines)

    title = (
        unwrap_title(meta_seen.get("题目", ""))
        or unwrap_title(first_h1)
    )
    if meta_seen.get("题目"):
        log.append(f"从元信息提取题目：{title}")
    elif first_h1:
        log.append(f"从原一级标题提取题目：{title}")
    if meta_seen:
        log.append("已移除元信息块：" + "、".join(meta_seen.keys()))
    if internal_h1:
        log.append(f"已移除内部标题 {internal_h1} 处"
                   f"（如「# 论文正文_XX（全文 v5）」）")

    # HTML 注释
    n_c = len(HTML_COMMENT_RE.findall(body_text))
    if n_c:
        body_text = HTML_COMMENT_RE.sub("", body_text)
        log.append(f"已移除 HTML 注释 {n_c} 处")

    # 状态行
    n_s = len(STATUS_LINE_RE.findall(body_text))
    if n_s:
        body_text = STATUS_LINE_RE.sub("", body_text)
        log.append(f"已移除状态行 {n_s} 处")

    # 前置规范题目
    if title:
        body_text = f"# {title}\n\n" + body_text.lstrip()
        log.append("已在文首加入规范一级标题")
    else:
        log.append("⚠️ 未识别到题目，请手工在文首补 `# 题目`")

    # 占位符（如「【新京报】」）
    n_p = len(PLACEHOLDER_RE.findall(body_text))
    if n_p:
        log.append(f"提示：发现 {n_p} 处占位符（如「【来源】」），"
                   f"审稿前建议先处理——保留原样会让'审稿人'看到内部标记")

    # 待核标记
    n_todo = len(TODO_RE.findall(body_text))
    if n_todo:
        if strip_todo:
            body_text = TODO_RE.sub("", body_text)
            log.append(f"已移除待核标记 {n_todo} 处（--strip-todo）")
        else:
            log.append(f"保留待核标记 {n_todo} 处（让'审稿人'抓出来；"
                       f"加 --strip-todo 可移除）")

    # 匿名化
    if anonymize:
        body_text = re.sub(r"（?作者信息[:：][^）\n]*）?", "", body_text)
        body_text = META_LINE_RE.sub("", body_text)
        body_text = re.sub(r"^\s*[*\-#]*\s*作者姓名.*$", "", body_text, flags=re.M)
        body_text = re.sub(r"^\s*[*\-#]*\s*\[?作者姓名待填写\]?.*$", "",
                           body_text, flags=re.M)
        log.append("已做匿名化处理（移除作者信息与基金项目）")

    # 收尾：压缩多余空行
    body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip() + "\n"
    return body_text, title, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="生成跨窗口审稿任务包（清洗稿件 + 审稿指令）")
    ap.add_argument("src", help="论文 Markdown 文件")
    ap.add_argument("--round", type=int, default=1, help="审稿轮次，默认 1")
    ap.add_argument("--anonymize", action="store_true",
                    help="匿名化（移除作者信息与基金项目）")
    ap.add_argument("--strip-todo", action="store_true",
                    help="移除 [待核] 等内部标记")
    ap.add_argument("--extra", default=None,
                    help="额外提供给审稿人的材料（如目标期刊投稿要求 PDF/网页），"
                         "填路径或说明")
    ap.add_argument("--outdir", default=None, help="输出目录（默认与稿件同目录）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.src):
        print(f"无法读取文件：{args.src}", file=sys.stderr)
        return 2

    text = load(args.src)
    clean, title, log = clean_manuscript(text, args.anonymize, args.strip_todo)

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.src))
    ms_name = f"审稿稿_M{args.round}.md"
    ms_path = os.path.join(outdir, ms_name)
    ins_name = f"审稿任务说明_M{args.round}.md"
    ins_path = os.path.join(outdir, ins_name)

    with open(ms_path, "w", encoding="utf-8") as f:
        f.write(clean)

    extra = (f"- ✅ `{args.extra}`（作者指定的额外材料）" if args.extra else "")
    with open(ins_path, "w", encoding="utf-8") as f:
        f.write(REVIEW_INSTRUCTIONS.format(
            round_no=args.round, manuscript=ms_name, extra_materials=extra))

    print("=" * 62)
    print(f"审稿任务包（第 {args.round} 轮）已生成")
    print("=" * 62)
    print(f"  题目      ：{title or '（未识别到题目，请手工确认）'}")
    print(f"  原稿      ：{os.path.basename(args.src)}（{len(text)} 字符）")
    print(f"  审稿稿    ：{ms_name}（{len(clean)} 字符）")
    print(f"  任务说明  ：{ins_name}")
    print("-" * 62)
    print("清洗记录：")
    for item in log:
        print(f"  · {item}")
    print("-" * 62)
    print("下一步：")
    print("  1. 新建一个**独立的窗口**（不要在本写作窗口里审稿）")
    print("  2. 选用**更强的推理模型**")
    print(f"  3. 把 {ins_name} 与 {ms_name} 一起交给它")
    print(f"  4. 让它把结果落盘为 审稿意见_M{args.round}.md")
    print(f"  5. 回到本窗口，把 审稿意见_M{args.round}.md 交给我执行修订")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
