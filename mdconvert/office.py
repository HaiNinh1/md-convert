"""Đọc DOCX và XLSX.

Khác hẳn PDF: ở đây không phải suy đoán gì cả. File .docx là một file ZIP chứa
XML, trong đó Word ghi thẳng ra "đoạn này là Heading 1", "chữ này in đậm",
"đây là bảng". Ta chỉ việc đọc đúng thứ đã được ghi sẵn, nên độ chính xác gần
như tuyệt đối — không cần OCR, không cần AI, không cần đoán cỡ chữ.
"""

from __future__ import annotations

import itertools
import re
import tempfile
import zipfile
from pathlib import Path

import mammoth
from markdownify import markdownify

# Word ghi tên style nội bộ bằng tiếng Anh kể cả khi giao diện là tiếng Việt,
# nên map mặc định của mammoth đã chạy đúng. Phần dưới chỉ để bắt thêm các style
# tự chế hay gặp trong template tiếng Việt.
STYLE_MAP = """
p[style-name='Title'] => h1:fresh
p[style-name='Subtitle'] => h2:fresh
p[style-name^='Đầu đề 1'] => h1:fresh
p[style-name^='Đầu đề 2'] => h2:fresh
p[style-name^='Đầu đề 3'] => h3:fresh
p[style-name^='Tiêu đề 1'] => h1:fresh
p[style-name^='Tiêu đề 2'] => h2:fresh
p[style-name^='Tiêu đề 3'] => h3:fresh
p[style-name='Quote'] => blockquote:fresh
p[style-name='Intense Quote'] => blockquote:fresh
r[style-name='Code'] => code
p[style-name='Code'] => pre:fresh
"""


class LegacyDocError(RuntimeError):
    """File .doc nhị phân đời cũ — không phải ZIP/XML, cần convert trung gian."""


def _image_handler(assets_dir: Path):
    counter = itertools.count(1)

    @mammoth.images.img_element
    def handler(image):
        ext = (image.content_type or "image/png").split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        assets_dir.mkdir(parents=True, exist_ok=True)
        name = f"docx_img{next(counter):03d}.{ext}"
        with image.open() as stream:
            (assets_dir / name).write_bytes(stream.read())
        return {"src": f"{assets_dir.name}/{name}", "alt": image.alt_text or ""}

    return handler


@mammoth.images.inline
def _drop_image(image):
    """Bỏ hẳn ảnh, KHÔNG nhúng base64.

    Đây là cái bẫy đã làm hỏng file .md: mammoth mặc định dùng data_uri, tức nhúng
    thẳng base64 vào. Chỉ cần không truyền convert_image là dính ngay — tên cờ nói
    "không tách ảnh" mà hành vi lại là nhúng inline, thứ tệ nhất trong các lựa
    chọn. Tài liệu 195 ảnh cho ra file .md nặng 25-76 MB, mỗi dòng ảnh dài hàng
    trăm nghìn ký tự: trình soạn thảo treo, không đọc nổi chữ.
    """
    return []


def _is_blank_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|(\s*\|)+", line.strip()))


def _fix_empty_table_headers(md: str) -> str:
    """Đôn hàng đầu lên làm tiêu đề khi bảng Word không đánh dấu hàng tiêu đề.

    Rất nhiều bảng Word không dùng "Header Row", nên mammoth không sinh <thead>
    và markdownify đành đẻ ra một hàng tiêu đề rỗng '|  |  |'. Hậu quả là hàng
    tiêu đề thật bị tụt xuống thành dữ liệu, và bảng nhìn lệch hẳn khi render.
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        # Mẫu cần bắt: hàng rỗng, ngay dưới là hàng gạch ngang, rồi tới dữ liệu.
        if (
            i + 2 < len(lines)
            and _is_blank_row(lines[i])
            and re.fullmatch(r"\|(\s*:?-{2,}:?\s*\|)+", lines[i + 1].strip())
            and lines[i + 2].strip().startswith("|")
            and not _is_blank_row(lines[i + 2])
        ):
            out.append(lines[i + 2])  # hàng dữ liệu đầu tiên trở thành tiêu đề
            out.append(lines[i + 1])
            i += 3
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def is_legacy_doc(path: Path) -> bool:
    """.docx là ZIP; .doc đời cũ thì không. Kiểm tra bằng chữ ký file, không tin đuôi."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    # D0 CF 11 E0 = OLE2 compound file, định dạng của Word 97-2003.
    return head[:4] == b"\xd0\xcf\x11\xe0"


def read_docx(path: Path, assets_dir: Path, extract_images: bool = True) -> tuple[str, dict]:
    """Đọc .docx. File .doc đời cũ được tự động chuyển sang .docx trước.

    Không bắt người dùng tự convert thủ công: máy Windows văn phòng gần như luôn
    có sẵn Microsoft Word, cứ nhờ nó làm rồi đi tiếp là xong.
    """
    if is_legacy_doc(path):
        from . import legacy_doc

        with tempfile.TemporaryDirectory(prefix="doc2docx-") as tmp:
            converted = Path(tmp) / f"{path.stem}.docx"
            try:
                tool = legacy_doc.to_docx(path, converted)
            except legacy_doc.NotAWordFile as e:
                raise LegacyDocError(f"Không đọc được '{path.name}'. {e}") from e
            except legacy_doc.NoConverter as e:
                raise LegacyDocError(
                    f"'{path.name}' là định dạng Word 97-2003 (.doc) nhị phân. {e}"
                ) from e
            md, stats = _read_docx(converted, assets_dir, extract_images)
            stats["converted_from"] = ".doc"
            stats["converted_by"] = tool
            return md, stats

    return _read_docx(path, assets_dir, extract_images)


def _read_docx(path: Path, assets_dir: Path, extract_images: bool) -> tuple[str, dict]:
    if not zipfile.is_zipfile(path):
        raise LegacyDocError(
            f"'{path.name}' không phải file .docx hợp lệ — không đọc được cấu trúc ZIP. "
            f"File có thể bị hỏng hoặc chỉ được đổi tên phần đuôi."
        )

    # PHẢI luôn đặt convert_image. Bỏ trống là mammoth tự nhúng base64.
    opts: dict = {
        "style_map": STYLE_MAP,
        "convert_image": _image_handler(assets_dir) if extract_images else _drop_image,
    }

    with open(path, "rb") as f:
        result = mammoth.convert_to_html(f, **opts)

    # _drop_image chặn được base64 nhưng vẫn để lại thẻ <img /> rỗng, mà
    # markdownify sẽ biến chúng thành "![]()" rác. Phải bỏ luôn thẻ.
    strip = ["span"] if extract_images else ["span", "img"]
    md = markdownify(
        result.value,
        heading_style="ATX",
        bullets="-",
        strip=strip,
    )
    md = _fix_empty_table_headers(md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"

    warnings = [m.message for m in result.messages if m.type == "warning"]
    stats = {
        "source": "docx",
        "warnings": len(warnings),
        "warning_sample": warnings[:5],
    }
    return md, stats


def read_xlsx(path: Path, max_rows: int = 5000) -> tuple[str, dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[str] = []
    sheets = 0

    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for row in ws.iter_rows(max_row=max_rows, values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue

        # Cắt bỏ các cột rỗng ở đuôi để bảng không thừa một loạt ô trống.
        width = max(
            (i + 1 for r in rows for i, c in enumerate(r) if c),
            default=0,
        )
        if not width:
            continue
        rows = [(r + [""] * width)[:width] for r in rows]

        sheets += 1
        out.append(f"## {ws.title}")
        head = rows[0]
        body = rows[1:]
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in head) + " |")
        out.append("| " + " | ".join(["---"] * width) + " |")
        for r in body:
            out.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in r) + " |")
        out.append("")

    wb.close()
    text = "\n".join(out).strip() + "\n"
    return text, {"source": "xlsx", "sheets": sheets}
