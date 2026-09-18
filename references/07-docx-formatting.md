# 07 · 投稿排版（Markdown → 期刊体例 Word）

## 一、为什么用 python-docx 而不是手搓 Word

**不是偏好问题，是踩坑结论。**

用 JS 库（如 docx.js）生成中文 Word 时，中文引号在编码转换中会被破坏，出现乱码或半角化。对于一篇满是「""''」和《》的法学论文，这是灾难性的。

**结论：论文类文档的生成，一律用 python-docx。** 它在 XML 层显式控制字体属性，中文引号零损失。

## 二、中文 Word 排版最大的坑：字体不生效

在 python-docx 里只写 `run.font.name = '宋体'`，**中文字符不会应用宋体**——因为 Word 的中文字体由 `w:eastAsia` 属性控制，与西文的 `w:ascii` / `w:hAnsi` 分开。

**必须三个属性一起设**：

```python
from docx.oxml.ns import qn

def set_font(run, cn='宋体', en='Times New Roman', size=12, bold=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = en                                   # 西文
    run._element.rPr.rFonts.set(qn('w:eastAsia'), cn)     # 中文 ← 关键
```

`md2docx.py` 已封装好这件事。

## 三、中文期刊论文的标准体例

| 元素 | 字体 | 字号 | 对齐 | 其他 |
|---|---|---|---|---|
| 标题 | 黑体 | 三号(16pt) | 居中 | 段后 12pt |
| 副标题 | 黑体 | 小二(18pt) | 居中 | — |
| 作者信息 | 楷体 | 小四(12pt) | 居中 | 段后 18pt |
| 摘要标题 | 黑体 | 小三(15pt) | 居中 | — |
| 摘要正文 | 楷体 | 小四(12pt) | 两端对齐 | 通常不缩进 |
| 一级标题 | 黑体 | 小三(15pt) | 左对齐 | 段前 12pt |
| 二级标题 | 黑体 | 小四(12pt) | 左对齐 | 段前 6pt |
| **正文** | **宋体** | **小四(12pt)** | 两端对齐 | **首行缩进 2 字符、1.5 倍行距** |
| 参考文献条目 | 宋体 | 五号(10.5pt) | 左对齐 | 悬挂缩进、单倍行距 |
| 页下脚注 | 宋体 | 小五(9pt) | 左对齐 | 单倍行距 |
| 西文与数字 | Times New Roman | 随正文 | — | — |
| 页面 | A4 21×29.7cm | — | — | 上下边距 2.54cm，左右 3.17cm |

**首行缩进 2 字符的正确实现**：不要用空格，要用 `first_line_indent`：

```python
p.paragraph_format.first_line_indent = Pt(size * 2)   # 12pt 字号 → 24pt 缩进
```

**参考文献悬挂缩进**：

```python
p.paragraph_format.left_indent = Pt(21)
p.paragraph_format.first_line_indent = Pt(-21)   # 负值 = 悬挂
```

## 四、真正的页下脚注（进阶）

`python-docx` **原生不支持创建脚注**。这是法学论文排版最麻烦的一点——很多期刊要求页下连续编号脚注，而不是尾注。

**解决方案**：两步走

1. 用 python-docx 正常生成文档，正文里用占位标记 `«FN1»` `«FN2»` 标出脚注位置；
2. 把 `.docx` 当 ZIP 打开，改写 `word/document.xml`：把占位标记替换成真正的 `<w:footnoteReference w:id="N"/>` 运行块，同时生成 `word/footnotes.xml` 与关系文件，并把脚注样式加入 `word/styles.xml`。

`md2docx.py --profile footnote` 已完整实现这条管线。源文件脚注写法沿用 Markdown 约定：

```markdown
……某处论述需要注解[^1]。

[^1]: 参见某某某：《书名》，某某出版社2020年版，第12页。
```

脚本会自动：
- 提取脚注定义并按**正文首次出现顺序**重排编号；
- 生成真脚注而非尾注；
- 页脚放"作者简介"占位。

> ⚠️ 这条管线依赖 `lxml`。若环境没有，脚本会降级为"脚注转为文末注释区"并明确提示，不会静默失败。

## 五、用法

```bash
# 文末参考文献体例（GB/T 7714 顺序编码制）
python scripts/md2docx.py 论文正文_XX_定稿.md -o 投稿_XX.docx --profile journal

# 页下脚注体例（法学核心期刊常用）
python scripts/md2docx.py 论文正文_XX_定稿.md -o 投稿_XX.docx --profile footnote

# 自定义元数据
python scripts/md2docx.py 论文正文_XX_定稿.md -o 投稿_XX.docx \
  --profile journal \
  --title "《示例》不是质量保证书——以某争议为例" \
  --author "张三（XX大学法学院）" \
  --running-head "电影公映许可的功能边界"
```

## 六、投稿前排版终检

- [ ] 打开 Word 确认每处中文字体正确（选中文字看字体框是否显示宋体/黑体，而不是"等线"）
- [ ] 首行缩进是 2 字符而非空格
- [ ] 参考文献悬挂缩进正确
- [ ] 脚注编号从 1 开始连续，且在正确页面底部
- [ ] 中文引号显示正常（不是 `""` 方头引号）
- [ ] 文件名为"投稿_<论文名>.docx"，不含特殊字符
- [ ] 按目标期刊要求检查页边距、行距、字号是否需要微调
