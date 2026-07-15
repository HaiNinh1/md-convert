"""Đổ các khối đã nhận dạng ra text markdown."""

from __future__ import annotations

import re

from .model import Block, Span

# Chỉ thoát những ký tự thực sự đổi nghĩa markdown khi nằm giữa dòng.
INLINE_ESCAPE = re.compile(r"([\\`*_\[\]<>])")
LINE_START_ESCAPE = re.compile(r"^(\s*)([#>|]|\d+[.)]\s|[-+*]\s)")


def escape_inline(text: str) -> str:
    return INLINE_ESCAPE.sub(r"\\\1", text)


def _merge_spans(spans: list[Span]) -> list[tuple[tuple[bool, bool, bool], str]]:
    """Gộp các span liền kề cùng kiểu để không sinh ra `**a****b**`."""
    out: list[tuple[tuple[bool, bool, bool], str]] = []
    for s in spans:
        if not s.text:
            continue
        key = s.style_key
        if out and out[-1][0] == key:
            out[-1] = (key, out[-1][1] + s.text)
        else:
            out.append((key, s.text))
    return out


def render_inline(spans: list[Span]) -> str:
    """Sinh markdown inline, đẩy khoảng trắng ra ngoài cặp dấu nhấn.

    Markdown không chấp nhận `** đậm **` — dấu nhấn phải dính liền chữ, nếu không
    trình render sẽ in ra nguyên dấu sao thay vì bôi đậm.
    """
    parts: list[str] = []
    for (bold, italic, mono), text in _merge_spans(spans):
        if not text.strip():
            parts.append(text)
            continue
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()) :]
        core = text.strip()

        if mono:
            core = f"`{core}`"
        else:
            core = escape_inline(core)
            if bold and italic:
                core = f"***{core}***"
            elif bold:
                core = f"**{core}**"
            elif italic:
                core = f"*{core}*"
        parts.append(lead + core + trail)

    out = "".join(parts)
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    norm = [[(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in r] + [""] * (ncols - len(r)) for r in rows]
    head = norm[0]
    body = norm[1:]
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def render(blocks: list[Block]) -> str:
    """Ghép danh sách khối thành một tài liệu markdown hoàn chỉnh."""
    out: list[str] = []
    for b in blocks:
        if b.kind == "heading":
            text = render_inline(b.spans)
            # Chữ đã nằm trong tiêu đề thì không cần bôi đậm nữa.
            text = re.sub(r"^\*\*(.*)\*\*$", r"\1", text)
            if text:
                out.append("#" * max(1, min(6, b.level)) + " " + text)

        elif b.kind == "para":
            text = render_inline(b.spans)
            if text:
                out.append(LINE_START_ESCAPE.sub(r"\1\\\2", text))

        elif b.kind == "list":
            lines: list[str] = []
            counters: dict[int, int] = {}
            for it in b.items:
                text = render_inline(it.spans)
                if not text:
                    continue
                indent = "  " * max(0, it.level)
                if it.ordered:
                    counters[it.level] = counters.get(it.level, 0) + 1
                    for deeper in [k for k in counters if k > it.level]:
                        counters.pop(deeper, None)
                    lines.append(f"{indent}{counters[it.level]}. {text}")
                else:
                    lines.append(f"{indent}- {text}")
            if lines:
                out.append("\n".join(lines))

        elif b.kind == "table":
            t = _md_table(b.rows)
            if t:
                out.append(t)

        elif b.kind == "code":
            out.append("```\n" + b.text + "\n```")

        elif b.kind == "image":
            out.append(f"![]({b.text})")

        elif b.kind == "rule":
            out.append("---")

    text = "\n\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
