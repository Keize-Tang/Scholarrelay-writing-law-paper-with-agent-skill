#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_textio.py —— 本工作流内部共用的文本读写helper（私有模块）

## 为什么需要它

Windows 上的中文用户经常遇到**非 UTF-8 编码**的文本文件：

- 知网导出的题录可能是 GBK / GB18030
- 用记事本另存为的 md 可能是 GBK 或带 BOM 的 UTF-8
- 从 Word 复制粘贴到 txt 的，编码取决于系统

如果脚本硬用 `encoding="utf-8"` 打开，会直接抛 `UnicodeDecodeError` ——
对非专业使用者就是"程序报错、不知道怎么办"。

本模块提供**多编码自动识别读取**，把这类崩溃变成正常处理。

## 说明

- 这是**内部辅助模块**，各脚本按以下方式引用（并带降级）：
  ```python
  try:
      sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
      from _textio import read_text
  except ImportError:               # 单独复制某一个脚本导致找不到本模块
      def read_text(p):
          with open(p, encoding="utf-8") as f:
              return f.read()
  ```
- 也就是说：**单独拿走一个脚本仍然能用**，只是失去多编码容错。
"""

from __future__ import annotations

# 尝试顺序：UTF-8 系 → 中文常见 → 繁体 → 最后兜底
CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")


def read_text(path: str) -> str:
    """多编码尝试读取文本文件。

    返回文件内容（已统一为 str，换行保持原样）。
    读不到任何编码都不会抛异常——最后以 errors="replace" 的 UTF-8 兜底，
    保证脚本不因编码问题崩溃。
    """
    with open(path, "rb") as f:
        raw = f.read()
    for enc in CANDIDATE_ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # 兜底：不崩溃，但把无法解码的字节替换掉
    return raw.decode("utf-8", errors="replace")


def detect_encoding(path: str) -> str:
    """返回实际使用的编码名（排查问题时用）。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in CANDIDATE_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "unknown(replaced)"


def write_text(path: str, text: str) -> None:
    """统一以 UTF-8（无 BOM）+ LF 写出。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
