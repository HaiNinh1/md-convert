"""Đọc PDF bằng PyMuPDF, tự động chuyển sang OCR khi trang không có lớp text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .model import ImageMarker, Line, Span, TableMarker

# Cờ định dạng của PyMuPDF trong span["flags"].
FLAG_ITALIC = 1 << 1
FLAG_MONO = 1 << 3
FLAG_BOLD = 1 << 4

# Dưới ngưỡng này coi như trang không có lớp text -> phải OCR.
SCAN_CHAR_THRESHOLD = 50
# Ảnh nhỏ hơn mức này thường là logo, đường kẻ, artifact -> bỏ qua.
MIN_IMAGE_PX = 80


# Chuẩn hoá khoảng trắng lạ về dấu cách thường.
#
# Font nhúng trong PDF hay map glyph sai: gõ dấu cách thường trong Word với font
# Times New Roman, PyMuPDF trích ra lại là U+00A0 NON-BREAKING SPACE. Mắt thường
# không phân biệt được vì NBSP trông y hệt dấu cách, nhưng nó phá grep, phá
# copy-paste và phá cách xuống dòng của trình render markdown.
WS_TRANSLATE = {
    0x00A0: " ",  # no-break space — thủ phạm hay gặp nhất
    0x2002: " ", 0x2003: " ", 0x2004: " ", 0x2005: " ",
    0x2006: " ", 0x2007: " ", 0x2008: " ", 0x2009: " ", 0x200A: " ",
    0x202F: " ",  # narrow no-break space
    0x3000: " ",  # ideographic space
    0x200B: "",   # zero-width space
    0xFEFF: "",   # zero-width no-break space / BOM
}


def _span_from_pymupdf(raw: dict) -> Span:
    flags = raw.get("flags", 0)
    font = raw.get("font", "")
    low = font.lower()
    x0, y0, x1, y1 = raw["bbox"]
    return Span(
        text=raw.get("text", "").translate(WS_TRANSLATE),
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        size=raw.get("size", 10.0),
        font=font,
        # Ưu tiên cờ của PyMuPDF, nhưng nhiều PDF nhúng font không đặt cờ đúng
        # nên vẫn phải soi tên font để bắt bù.
        bold=bool(flags & FLAG_BOLD) or "bold" in low or "black" in low,
        italic=bool(flags & FLAG_ITALIC) or "italic" in low or "oblique" in low,
        mono=bool(flags & FLAG_MONO) or "mono" in low or "courier" in low,
    )


def extract_lines(page: fitz.Page) -> list[Line]:
    data = page.get_text("dict")
    lines: list[Line] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = text
            continue
        for raw_line in block.get("lines", []):
            spans = [
                _span_from_pymupdf(s)
                for s in raw_line.get("spans", [])
                if s.get("text")
            ]
            if spans and any(s.text.strip() for s in spans):
                lines.append(Line(spans=spans))
    return lines


def extract_tables(page: fitz.Page) -> list[TableMarker]:
    """Dò bảng bằng đường kẻ và căn cột thật của PyMuPDF."""
    out: list[TableMarker] = []
    try:
        finder = page.find_tables()
    except Exception:
        return out
    for tbl in finder.tables:
        try:
            rows = tbl.extract()
        except Exception:
            continue
        # Ô bảng không đi qua _span_from_pymupdf nên phải tự chuẩn hoá khoảng trắng.
        rows = [
            [(c.translate(WS_TRANSLATE) if c else "") for c in r] for r in rows
        ]
        if len(rows) < 2 or not any(any(c.strip() for c in r) for r in rows):
            continue
        x0, y0, _x1, _y1 = tbl.bbox
        out.append(TableMarker(y0=y0, x0=x0, rows=rows))
    return out


def extract_images(page: fitz.Page, assets_dir: Path, page_no: int) -> list[ImageMarker]:
    out: list[ImageMarker] = []
    doc = page.parent
    for idx, info in enumerate(page.get_images(full=True)):
        xref = info[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        if not rects:
            continue
        try:
            base = doc.extract_image(xref)
        except Exception:
            continue
        if base.get("width", 0) < MIN_IMAGE_PX or base.get("height", 0) < MIN_IMAGE_PX:
            continue
        assets_dir.mkdir(parents=True, exist_ok=True)
        name = f"p{page_no:03d}_img{idx + 1}.{base.get('ext', 'png')}"
        (assets_dir / name).write_bytes(base["image"])
        r = rects[0]
        out.append(ImageMarker(y0=r.y0, x0=r.x0, path=f"{assets_dir.name}/{name}"))
    return out


def _drop_inside_tables(lines: list[Line], tables: list[TableMarker], page: fitz.Page) -> list[Line]:
    """Bỏ các dòng nằm trong vùng bảng — nội dung của chúng đã có trong bảng rồi."""
    if not tables:
        return lines
    boxes = []
    try:
        for tbl in page.find_tables().tables:
            boxes.append(fitz.Rect(tbl.bbox))
    except Exception:
        return lines
    kept: list[Line] = []
    for ln in lines:
        cx = (ln.x0 + ln.x1) / 2
        cy = (ln.y0 + ln.y1) / 2
        if any(b.contains(fitz.Point(cx, cy)) for b in boxes):
            continue
        kept.append(ln)
    return kept


def page_is_scanned(page: fitz.Page, threshold: int = SCAN_CHAR_THRESHOLD) -> bool:
    return len(page.get_text().strip()) < threshold


def strip_headers_footers(pages: list[list[Line]], min_share: float = 0.6) -> list[list[Line]]:
    """Bỏ header/footer lặp lại và số trang.

    Chỉ xét dòng trên cùng và dưới cùng mỗi trang. Nội dung nào lặp lại trên phần
    lớn số trang thì đó là header/footer chứ không phải nội dung thật.
    """
    if len(pages) < 3:
        return pages

    def norm(t: str) -> str:
        return re.sub(r"\d+", "#", t.strip().lower())

    counts: dict[str, int] = {}
    for lines in pages:
        if not lines:
            continue
        ordered = sorted(lines, key=lambda l: l.y0)
        for ln in {id(ordered[0]): ordered[0], id(ordered[-1]): ordered[-1]}.values():
            key = norm(ln.text)
            if key:
                counts[key] = counts.get(key, 0) + 1

    banned = {k for k, n in counts.items() if n >= len(pages) * min_share}
    if not banned:
        return pages

    out: list[list[Line]] = []
    for lines in pages:
        if not lines:
            out.append(lines)
            continue
        ordered = sorted(lines, key=lambda l: l.y0)
        drop = set()
        for ln in (ordered[0], ordered[-1]):
            if norm(ln.text) in banned:
                drop.add(id(ln))
        out.append([ln for ln in lines if id(ln) not in drop])
    return out


@dataclass
class PageParts:
    lines: list[Line]
    tables: list[TableMarker]
    images: list[ImageMarker]
    scanned: bool


def read_pdf(
    path: Path,
    assets_dir: Path,
    ocr_lang: str = "vi",
    dpi: int = 300,
    psm: int = 3,
    use_online: bool = False,
    online_key: str | None = None,
    extract_images_flag: bool = True,
    force_ocr: bool = False,
    on_page=None,
) -> tuple[list[PageParts], float, dict]:
    """Đọc toàn bộ PDF, trả về (các_trang, page_width, thống_kê).

    Hai nhánh text-layer và OCR nhập lại làm một ngay tại đây: cả hai đều sinh ra
    cùng kiểu Line/Span, nên mọi tầng phía sau không cần biết trang đến từ đâu.
    """
    doc = fitz.open(path)
    pages: list[PageParts] = []
    page_width = 0.0
    stats = {"pages": len(doc), "ocr_pages": 0, "text_pages": 0, "tables": 0, "images": 0}

    ocr_engine = None

    for page_no, page in enumerate(doc, start=1):
        page_width = max(page_width, page.rect.width)
        scanned = force_ocr or page_is_scanned(page)

        if scanned:
            from .layout import tables_from_lines

            if use_online:
                from .online_ocr import ocr_page_lines_online

                lines = ocr_page_lines_online(page, dpi=dpi, api_key=online_key)
            else:
                from .ocr import get_engine, ocr_page_lines

                if ocr_engine is None:
                    ocr_engine = get_engine(ocr_lang)
                lines = ocr_page_lines(ocr_engine, page, dpi=dpi, psm=psm)
            tables, lines = tables_from_lines(lines)
            images: list[ImageMarker] = []
            stats["ocr_pages"] += 1
        else:
            lines = extract_lines(page)
            tables = extract_tables(page)
            lines = _drop_inside_tables(lines, tables, page)
            images = (
                extract_images(page, assets_dir, page_no) if extract_images_flag else []
            )
            stats["text_pages"] += 1

        stats["tables"] += len(tables)
        stats["images"] += len(images)
        pages.append(PageParts(lines=lines, tables=tables, images=images, scanned=scanned))
        if on_page:
            on_page(page_no, len(doc), scanned)

    doc.close()
    return pages, (page_width or 595.0), stats
