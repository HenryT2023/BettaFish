# -*- coding: utf-8 -*-
"""
DOCX Renderer — 将 ReportEngine IR 渲染为 .docx 文件

输出兼容 wechat_publisher/docx_parser.py 的格式。
支持的 IR block 类型：heading, paragraph, list, blockquote, hr, table, callout。
不支持（WeChat 不兼容）：math, code, figure, chart, widget。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

try:
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE
except ImportError:
    raise ImportError("python-docx 未安装，请运行: pip install python-docx")


class DocxRenderer:
    """将 IR blocks 渲染为 .docx 文件"""

    def __init__(self):
        self.doc = Document()
        self._setup_styles()

    def _setup_styles(self):
        """配置基本样式，确保中文字体"""
        style = self.doc.styles["Normal"]
        font = style.font
        font.name = "微软雅黑"
        font.size = Pt(11)

        # 设置中文字体（通过 XML 操作）
        try:
            from docx.oxml.ns import qn
            style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        except Exception:
            pass

    def render_blocks(self, blocks: List[Dict[str, Any]]) -> Document:
        """渲染 IR blocks 列表"""
        for block in blocks:
            block_type = block.get("type", "")
            handler = getattr(self, f"_render_{block_type}", None)
            if handler:
                handler(block)
            else:
                logger.debug(f"跳过不支持的 block 类型: {block_type}")
        return self.doc

    def render_from_markdown(self, markdown_text: str) -> Document:
        """
        从 Markdown 文本渲染 .docx（简化路径，不走 IR）。
        适用于 Quill 直接从 LLM 输出 Markdown 的场景。
        """
        lines = markdown_text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()

            # 空行
            if not line:
                i += 1
                continue

            # 标题
            if line.startswith("#"):
                level = 0
                while level < len(line) and line[level] == "#":
                    level += 1
                text = line[level:].strip()
                self._add_heading(text, min(level, 4))
                i += 1
                continue

            # 分隔线
            if line.strip() in ("---", "***", "___"):
                self._render_hr({})
                i += 1
                continue

            # 引用
            if line.startswith(">"):
                quote_lines = []
                while i < len(lines) and lines[i].startswith(">"):
                    quote_lines.append(lines[i].lstrip("> ").rstrip())
                    i += 1
                self._add_blockquote("\n".join(quote_lines))
                continue

            # 无序列表
            if line.lstrip().startswith("- ") or line.lstrip().startswith("* "):
                list_items = []
                while i < len(lines) and (lines[i].lstrip().startswith("- ") or lines[i].lstrip().startswith("* ")):
                    item_text = lines[i].lstrip().lstrip("-* ").strip()
                    list_items.append(item_text)
                    i += 1
                for item in list_items:
                    p = self.doc.add_paragraph(style="List Bullet")
                    self._add_rich_text(p, item)
                continue

            # 有序列表
            if len(line.lstrip()) > 2 and line.lstrip()[0].isdigit() and ". " in line.lstrip()[:5]:
                list_items = []
                while i < len(lines):
                    stripped = lines[i].lstrip()
                    if len(stripped) > 2 and stripped[0].isdigit() and ". " in stripped[:5]:
                        item_text = stripped.split(". ", 1)[-1].strip()
                        list_items.append(item_text)
                        i += 1
                    else:
                        break
                for item in list_items:
                    p = self.doc.add_paragraph(style="List Number")
                    self._add_rich_text(p, item)
                continue

            # 普通段落
            p = self.doc.add_paragraph()
            self._add_rich_text(p, line)
            i += 1

        return self.doc

    def save(self, output_path: str) -> str:
        """保存 .docx 文件"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(output_path)
        logger.info(f"DOCX 已保存: {output_path}")
        return output_path

    # ========== IR Block Handlers ==========

    def _render_heading(self, block: Dict):
        level = block.get("level", 1)
        text = block.get("text", "")
        self._add_heading(text, level)

    def _render_paragraph(self, block: Dict):
        p = self.doc.add_paragraph()
        inlines = block.get("inlines", [])
        if inlines:
            for inline in inlines:
                self._add_inline_run(p, inline)
        else:
            p.add_run("")

        align = block.get("align")
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def _render_list(self, block: Dict):
        list_type = block.get("listType", "bullet")
        items = block.get("items", [])
        style_name = "List Bullet" if list_type == "bullet" else "List Number"

        for item_blocks in items:
            p = self.doc.add_paragraph(style=style_name)
            for sub_block in item_blocks:
                if sub_block.get("type") == "paragraph":
                    for inline in sub_block.get("inlines", []):
                        self._add_inline_run(p, inline)

    def _render_blockquote(self, block: Dict):
        inner_blocks = block.get("blocks", [])
        text_parts = []
        for b in inner_blocks:
            if b.get("type") == "paragraph":
                for inline in b.get("inlines", []):
                    text_parts.append(inline.get("text", ""))
        self._add_blockquote(" ".join(text_parts))

    def _render_engineQuote(self, block: Dict):
        title = block.get("title", "Agent 观点")
        inner_blocks = block.get("blocks", [])
        text_parts = []
        for b in inner_blocks:
            if b.get("type") == "paragraph":
                for inline in b.get("inlines", []):
                    text_parts.append(inline.get("text", ""))
        self._add_blockquote(f"[{title}] " + " ".join(text_parts))

    def _render_hr(self, block: Dict):
        p = self.doc.add_paragraph()
        p.add_run("─" * 40)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _render_table(self, block: Dict):
        rows_data = block.get("rows", [])
        if not rows_data:
            return

        max_cols = max(len(r.get("cells", [])) for r in rows_data)
        table = self.doc.add_table(rows=len(rows_data), cols=max_cols)
        table.style = "Table Grid"

        for row_idx, row in enumerate(rows_data):
            for col_idx, cell in enumerate(row.get("cells", [])):
                if col_idx < max_cols:
                    cell_blocks = cell.get("blocks", [])
                    text = ""
                    for b in cell_blocks:
                        if b.get("type") == "paragraph":
                            for inline in b.get("inlines", []):
                                text += inline.get("text", "")
                    table.cell(row_idx, col_idx).text = text

    def _render_callout(self, block: Dict):
        tone = block.get("tone", "info")
        title = block.get("title", "")
        prefix_map = {"info": "💡", "warning": "⚠️", "success": "✅", "danger": "❌"}
        prefix = prefix_map.get(tone, "📌")

        inner_blocks = block.get("blocks", [])
        text_parts = []
        for b in inner_blocks:
            if b.get("type") == "paragraph":
                for inline in b.get("inlines", []):
                    text_parts.append(inline.get("text", ""))

        full_text = f"{prefix} {title}\n{' '.join(text_parts)}" if title else f"{prefix} {' '.join(text_parts)}"
        self._add_blockquote(full_text)

    def _render_kpiGrid(self, block: Dict):
        items = block.get("items", [])
        if not items:
            return
        table = self.doc.add_table(rows=2, cols=len(items))
        table.style = "Table Grid"
        for i, item in enumerate(items):
            table.cell(0, i).text = item.get("label", "")
            value_text = item.get("value", "")
            if item.get("unit"):
                value_text += f" {item['unit']}"
            table.cell(1, i).text = value_text

    # ========== Helpers ==========

    def _add_heading(self, text: str, level: int):
        heading = self.doc.add_heading(text, level=min(level, 4))
        for run in heading.runs:
            run.font.color.rgb = RGBColor(0, 0, 0)

    def _add_blockquote(self, text: str):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.5)
        run = p.add_run(text)
        run.italic = True
        run.font.color.rgb = RGBColor(100, 100, 100)

    def _add_inline_run(self, paragraph, inline: Dict):
        """添加 IR inline run 到段落"""
        text = inline.get("text", "")
        run = paragraph.add_run(text)

        marks = inline.get("marks", [])
        for mark in marks:
            mark_type = mark.get("type", "")
            if mark_type == "bold":
                run.bold = True
            elif mark_type == "italic":
                run.italic = True
            elif mark_type == "underline":
                run.underline = True
            elif mark_type == "strike":
                run.font.strike = True
            elif mark_type == "color":
                color_val = mark.get("value", "")
                if isinstance(color_val, str) and len(color_val) == 7 and color_val.startswith("#"):
                    try:
                        run.font.color.rgb = RGBColor(
                            int(color_val[1:3], 16),
                            int(color_val[3:5], 16),
                            int(color_val[5:7], 16),
                        )
                    except (ValueError, IndexError):
                        pass

    def _add_rich_text(self, paragraph, text: str):
        """解析简单 Markdown 标记（**bold**, *italic*）并添加到段落"""
        import re
        parts = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith("*") and part.endswith("*"):
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            else:
                paragraph.add_run(part)
