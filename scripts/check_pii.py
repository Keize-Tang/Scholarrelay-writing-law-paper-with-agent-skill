#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_pii.py —— 发布前隐私扫描（个人信息泄漏自检）

## 为什么需要它

本工作流的素材来自真实论文，而技能包是要公开发布的。**发布前必须确认仓库里
不含姓名、单位、联系方式、未发表内容、本地路径。**

配套文档：`references/16-privacy-protection.md`

## 用法

    # 全仓扫描
    python scripts/check_pii.py .

    # 指定自己的敏感词表（最可靠的做法：把你的姓名/学校/导师写进去）
    python scripts/check_pii.py . --terms 我的敏感词.txt

    # 只看结论
    python scripts/check_pii.py . --quiet

    # 允许某些词（避免误报）
    python scripts/check_pii.py . --allow 大学,学院

敏感词文件格式：一行一个，`#` 开头为注释。

## 退出码

0 = 未发现需处理项；1 = 发现需处理项；2 = 参数/路径错误

## ⚠️ 局限

自动扫描**不能替代人工通读**。脚本只能抓模式化信息；
可推断身份的组合信息（学校+方向+年份）需要你自己判断。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# ---------------------------------------------------------------- 常量

TEXT_EXT = {".md", ".markdown", ".txt", ".py", ".json", ".yml", ".yaml",
            ".toml", ".ini", ".cfg", ".html", ".htm", ".js", ".ts",
            ".css", ".sh", ".bat", ".ps1", ".csv", ".tsv", ""}

BINARY_EXT = {".pdf", ".caj", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
              ".pptx", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".7z",
              ".rar", ".pyc", ".exe", ".dll"}

# 脱敏占位形式——命中这些不算泄漏
REDACTED = re.compile(
    r"[××Xx]{2,}|某某|某大学|某学院|○○|000000|0{6}|"
    r"[【\[]\s*(作者|姓名|单位|待填写|待补|来源|日期)[^】\]]*[】\]]|"
    r"example\.com|user@|your[_-]?name|<[^>]{1,20}>"
)

PATTERNS: list[tuple[str, str, str, str]] = [
    # (类别, 严重度, 说明, 正则)
    ("联系方式", "高", "邮箱地址",
     r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    ("联系方式", "高", "中国大陆手机号",
     r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("联系方式", "高", "身份证号",
     r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"),
    ("联系方式", "中", "QQ号/长数字串",
     r"(?<!\d)[1-9]\d{7,10}(?!\d)"),
    ("本地路径", "高", "Windows 绝对路径（含机器用户名）",
     r"[A-Za-z]:[\\/](?:Users|用户)[\\/][^\\/\s\"']+"),
    ("本地路径", "中", "盘符绝对路径",
     r"(?<![\w.])[A-Za-z]:[\\/][^\s\"'<>|`]{4,}"),
    ("本地路径", "中", "Unix 家目录路径",
     r"/(?:home|Users)/[A-Za-z0-9._-]+/"),
    ("单位信息", "高", "作者单位字段（最可能是你自己的单位）",
     r"(?:作者|单位|通讯地址|联系地址|所在单位)\s*[:：]?\s*[（(]?\s*[\u4e00-\u9fff]{4,20}(?:大学|学院|研究院)"),
    ("身份信息", "中", "作者字段后的人名",
     r"(?:作者|姓名|著作人|执笔人)\s*[:：]\s*[\u4e00-\u9fff]{2,4}"),
    ("未发表内容", "中", "「以……为中心」式自拟标题",
     r"《[^》]{4,30}》[^\n]{0,10}(?:研究|探析|分析|论)[^\n]{0,25}(?:——|--)[^\n]{0,30}"),
    ("单位信息", "中", "英文机构名（含校名缩写）",
     r"(?:[A-Z][a-z]+\s+){1,4}(?:of\s+)?[A-Z][a-z]+\s*,?\s*[A-Z]{2,6}\b"),
    ("单位信息", "中", "英文单位行含校名缩写",
     r"\b(?:University|College|Institute|School|Academy)\b[^\n]{0,40}?\b[A-Z]{2,8}\b"),
]

# 常见非机构误报片段（出现在"大学/学院"前就跳过）
NON_INSTITUTION = (
    "的", "到", "是", "在", "和", "与", "或", "等", "用", "写", "为",
    "从", "对", "把", "被", "让", "使", "由", "向", "以", "将", "该",
    "本", "此", "各", "某", "所", "能", "可", "应", "需", "要",
    "国内", "国外", "境外", "知名", "重点", "普通", "民办", "公办",
    "中国", "全国", "各大", "法学", "政法", "财经", "师范", "医科",
)

# 引用语境标志：出现这些词的同一行里，机构名多为文献出处而非作者单位
CITATION_MARKERS = ("参见", "载《", "载于", "出处", "出版社", "学报", "期刊",
                    "学位论文", "硕士", "博士", "编译", "译", "[J]", "[M]", "[D]",
                    "第", "页", "年", "期")

# 常见姓氏（用于提高人名检测的准确率，减少误报）
SURNAMES = ("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
            "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方"
            "俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅"
            "皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧"
            "计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危"
            "江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫"
            "经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑"
            "裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
            "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭历戎祖武符刘"
            "景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙"
            "池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮"
            "牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向"
            "古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚"
            "越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢"
            "关蒯相查后荆红游竺权逯盖益桓公")


def is_binary(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in BINARY_EXT


def read_text(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
    except OSError:
        return None


def collect_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules",
                                    ".venv", "venv", ".idea", ".vscode")]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def scan_file(path: str, terms: list[str], allow: list[str]):
    hits = []
    ext = os.path.splitext(path)[1].lower()

    # 二进制品类文件：只查是否应被提交
    if is_binary(path):
        if ext in (".pdf", ".caj"):
            hits.append(("提交卫生", "高", "不应提交 PDF/CAJ（版权+可能含批注）", 0, ""))
        elif ext in (".doc", ".docx"):
            hits.append(("提交卫生", "中",
                         "不应提交 docx（除非是脱敏示例）", 0, ""))
        return hits

    if ext not in TEXT_EXT:
        return hits

    text = read_text(path)
    if text is None:
        return hits

    lines = text.split("\n")

    # 内置模式
    for cat, sev, desc, pat in PATTERNS:
        rx = re.compile(pat)
        for m in rx.finditer(text):
            frag = m.group(0).strip()
            if not frag or REDACTED.search(frag):
                continue
            if any(a and a in frag for a in allow):
                continue
            ln = text[:m.start()].count("\n") + 1
            # 姓氏校验：降低"人名"类误报
            if desc == "作者字段后的人名":
                name = re.sub(r"^(?:作者|姓名|著作人|执笔人)\s*[:：]\s*", "", frag)
                if not (name and name[0] in SURNAMES):
                    continue
            hits.append((cat, sev, desc, ln, frag[:80]))

    # 独立检查：机构名（只在"非引用语境"里才算可疑）
    inst_rx = re.compile(r"[\u4e00-\u9fff]{2,6}(?:大学|学院|研究院)")
    for m in inst_rx.finditer(text):
        frag = m.group(0)
        if REDACTED.search(frag) or any(a and a in frag for a in allow):
            continue
        head = frag[:frag.find("大") if "大" in frag else frag.find("学")]
        if not head or head in NON_INSTITUTION:
            continue
        if any(w in head for w in NON_INSTITUTION):
            continue
        ln = text[:m.start()].count("\n") + 1
        line = lines[ln - 1] if ln <= len(lines) else ""
        # 引用语境（文献出处）不算泄漏
        if any(k in line for k in CITATION_MARKERS) and "作者" not in line \
                and "单位" not in line:
            continue
        hits.append(("单位信息", "中", "疑似具体机构名（请确认是否为你自己的单位）",
                     ln, frag))

    # 自定义敏感词
    for t in terms:
        if not t.strip():
            continue
        for m in re.finditer(re.escape(t), text):
            ln = text[:m.start()].count("\n") + 1
            hits.append(("自定义", "高", f"命中敏感词「{t}」", ln,
                         lines[ln - 1].strip()[:80] if ln <= len(lines) else ""))

    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="发布前隐私扫描")
    ap.add_argument("root", nargs="?", default=".", help="要扫描的目录（默认当前目录）")
    ap.add_argument("--terms", default=None,
                    help="自定义敏感词文件（一行一个，# 开头为注释）。"
                         "强烈建议：把你的姓名、学校、导师写进去")
    ap.add_argument("--allow", default="",
                    help="允许出现的词，逗号分隔（用于排除误报）")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    args = ap.parse_args(argv)

    if not os.path.exists(args.root):
        print(f"路径不存在：{args.root}\n"
              f"    用法：python check_pii.py [目录或文件] [--terms 敏感词.txt]",
              file=sys.stderr)
        return 2
    single_file = os.path.isfile(args.root)

    terms: list[str] = []
    if args.terms:
        if not os.path.isfile(args.terms):
            print(f"敏感词文件不存在：{args.terms}", file=sys.stderr)
            return 2
        with open(args.terms, encoding="utf-8") as f:
            terms = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    allow = [a.strip() for a in args.allow.split(",") if a.strip()]

    all_hits: list[tuple[str, list]] = []
    n_files = 0
    walker = [args.root] if single_file else collect_files(args.root)
    base = os.path.dirname(args.root) if single_file else args.root
    for path in walker:
        n_files += 1
        hits = scan_file(path, terms, allow)
        if hits:
            all_hits.append((path, hits))

    if not terms and not args.quiet:
        print("提示：未提供 --terms 敏感词表。把你的姓名/学校写进一个文件后传入，"
              "检测会准得多。\n")

    print("=" * 70)
    print(f"隐私扫描：{args.root}")
    print("=" * 70)
    print(f"扫描文件数：{n_files}")

    if not all_hits:
        print("\n✅ 未发现需处理项。")
        print("\n⚠️  仍需人工通读：可推断身份的组合信息（学校+方向+年份）"
              "脚本抓不到。")
        print("⚠️  若曾提交过敏感内容，只改文件不够——Git 历史里仍有残留，"
              "见 references/16-privacy-protection.md 第四节。")
        return 0

    high = sum(1 for _, hs in all_hits for h in hs if h[1] == "高")
    mid = sum(1 for _, hs in all_hits for h in hs if h[1] == "中")
    low = sum(1 for _, hs in all_hits for h in hs if h[1] == "低")

    if not args.quiet:
        for path, hits in all_hits:
            rel = os.path.relpath(path, base)
            print(f"\n📄 {rel}")
            for cat, sev, desc, ln, frag in sorted(hits, key=lambda x: x[3]):
                mark = {"高": "❌", "中": "⚠️ ", "低": "·"}[sev]
                loc = f"第 {ln} 行" if ln else "文件级"
                print(f"  {mark} [{cat}/{sev}] {loc}：{desc}")
                if frag and not args.quiet:
                    print(f"        → {frag}")

    print("\n" + "-" * 70)
    print(f"合计：高 {high} / 中 {mid} / 低 {low}")
    print("\n处理建议：")
    print("  1. 高 严重度：必须在发布前删除或替换为 ××/某某 形式")
    print("  2. 中 严重度：逐条人工判断是否真的泄漏（可能有误报）")
    print("  3. 低 严重度：提示性，通常可忽略")
    print("  4. 若已推送过：Git 历史仍含残留，见 references/16 第四节")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
