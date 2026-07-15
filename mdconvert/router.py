"""Định tuyến theo loại file và ráp toàn bộ pipeline thành markdown."""

from __future__ import annotations

from pathlib import Path

from .emit import render
from .layout import (
    build_heading_map,
    detect_body_size,
    group_blocks,
    refine_heading_levels,
    split_columns,
)
from .model import Line

PDF_EXT = {".pdf"}
DOCX_EXT = {".docx", ".docm"}
LEGACY_DOC_EXT = {".doc"}
XLSX_EXT = {".xlsx", ".xlsm"}
SUPPORTED = PDF_EXT | DOCX_EXT | LEGACY_DOC_EXT | XLSX_EXT


class UnsupportedFile(RuntimeError):
    pass


def _assign_to_columns(markers: list, columns: list[list[Line]]) -> list[list]:
    """Xếp bảng/ảnh vào đúng cột dựa trên toạ độ x."""
    if len(columns) == 1:
        return [list(markers)]
    bounds = []
    for col in columns:
        if col:
            bounds.append((min(l.x0 for l in col), max(l.x1 for l in col)))
        else:
            bounds.append((0.0, 0.0))
    out: list[list] = [[] for _ in columns]
    for m in markers:
        best = min(
            range(len(bounds)),
            key=lambda i: abs(m.x0 - bounds[i][0]),
        )
        out[best].append(m)
    return out


def convert_pdf(
    src: Path,
    out_dir: Path,
    ocr_lang: str = "vi",
    dpi: int = 300,
    extract_images: bool = True,
    force_ocr: bool = False,
    keep_headers: bool = False,
    on_page=None,
) -> tuple[str, dict]:
    from .pdf import read_pdf, strip_headers_footers

    assets_dir = out_dir / f"{src.stem}_assets"
    pages, page_width, stats = read_pdf(
        src,
        assets_dir,
        ocr_lang=ocr_lang,
        dpi=dpi,
        extract_images_flag=extract_images,
        force_ocr=force_ocr,
        on_page=on_page,
    )

    lines_per_page = [p.lines for p in pages]
    if not keep_headers:
        lines_per_page = strip_headers_footers(lines_per_page)

    # Cỡ chữ thân bài và bảng cấp tiêu đề tính trên TOÀN tài liệu, không phải từng
    # trang. Nếu tính theo trang, một trang toàn tiêu đề (trang bìa) sẽ tự coi cỡ
    # tiêu đề của nó là thân bài và mọi cấp sẽ lệch nhau giữa các trang.
    all_lines = [ln for page_lines in lines_per_page for ln in page_lines]
    if not all_lines and not any(p.tables for p in pages):
        return "", {**stats, "empty": True}

    body_size = detect_body_size(all_lines)
    # Trang OCR chỉ ước lượng được cỡ chữ với sai số ~10%, nên phải nới dung sai
    # gom cụm; PDF số có cỡ chữ chính xác nên giữ chặt để không gộp nhầm hai cấp.
    ocr_heavy = stats["ocr_pages"] > stats["text_pages"]
    heading_map = build_heading_map(
        all_lines, body_size, rel_tolerance=0.10 if ocr_heavy else 0.0
    )

    blocks = []
    for parts, page_lines in zip(pages, lines_per_page):
        columns = split_columns(page_lines, page_width)
        markers = list(parts.tables) + list(parts.images)
        marker_cols = _assign_to_columns(markers, columns)
        for col_lines, col_markers in zip(columns, marker_cols):
            blocks.extend(
                group_blocks(list(col_lines) + col_markers, body_size, heading_map)
            )

    blocks = refine_heading_levels(blocks)

    stats["body_size"] = body_size
    stats["heading_levels"] = len(set(heading_map.values()))
    stats["columns"] = "multi" if any(
        len(split_columns(p, page_width)) > 1 for p in lines_per_page
    ) else "single"
    return render(blocks), stats


def convert_file(
    src: Path,
    out_dir: Path,
    **kw,
) -> tuple[str, dict]:
    """Chuyển một file bất kỳ sang markdown. Tự chọn nhánh xử lý theo loại file."""
    ext = src.suffix.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    if ext in PDF_EXT:
        return convert_pdf(src, out_dir, **kw)

    if ext in DOCX_EXT or ext in LEGACY_DOC_EXT:
        from .office import read_docx

        return read_docx(
            src,
            out_dir / f"{src.stem}_assets",
            extract_images=kw.get("extract_images", True),
        )

    if ext in XLSX_EXT:
        from .office import read_xlsx

        return read_xlsx(src)

    raise UnsupportedFile(
        f"Chưa hỗ trợ đuôi '{ext}'. Các loại nhận được: {', '.join(sorted(SUPPORTED))}"
    )
