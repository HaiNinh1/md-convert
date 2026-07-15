"""OCR cho trang scan bằng Tesseract. Offline, miễn phí, không gọi API nào.

Vì sao Tesseract chứ không phải PaddleOCR/RapidOCR:

Dự án này ban đầu dùng rapidocr-onnxruntime với model latin_PP-OCRv3 lấy từ
OCR-Offline, vì cài bằng pip là xong, không cần binary. Đo thực tế thì hỏng:
"Báo cáo Kỹ thuật" ra "Bao cao Ky thuat", "Tổng quan hệ thống" ra "Tóng quan h
thóng". Nguyên nhân không phải model đoán kém — file latin_dict.txt đi kèm chỉ
có 186 ký tự và THIẾU 53/74 ký tự riêng của tiếng Việt (ă, ơ, ư, ả, ạ, ấ, ầ, ẩ,
ẫ, ậ...). Những ký tự đó không nằm trong vốn từ đầu ra của model, nên nó không
thể xuất ra dù có nhận đúng mặt chữ. Đó là model Latin châu Âu (é, ö, ä), không
phải model tiếng Việt.

Tesseract với vie.traineddata đọc đúng dấu, chỉ còn nhầm lẻ tẻ giữa các dấu gần
giống nhau. Đổi lại phải cài binary một lần — đánh đổi xứng đáng.

Đầu ra được quy về đúng kiểu Line/Span như nhánh PDF có text layer, nên tầng
phân tích layout dùng chung không cần biết trang đến từ đâu.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .model import Line, Span

TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]

# Thư mục tessdata ưu tiên: bản của OCR-Offline có sẵn vie + vie_best.
TESSDATA_CANDIDATES = [
    Path(r"C:\Works\OCR2\OCR-Offline\tessdata"),
    Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
]

LANG_ALIASES = {"vi": "vie", "vn": "vie", "en": "eng"}

MIN_CONF = 40.0  # dưới mức này Tesseract thường đang đoán bừa trên vệt nhiễu

# Ước lượng cỡ chữ từ bề rộng trung bình mỗi ký tự, KHÔNG dùng chiều cao khung.
#
# Chiều cao khung đo vệt mực chứ không đo cỡ chữ: dòng không có chữ thò lên/thụt
# xuống thì khung lùn hẳn. Đo trên bản scan thật: cùng cỡ 10pt mà chiều cao khung
# chênh nhau 1.46 lần, trong khi tiêu đề 15pt lại cho chiều cao BẰNG thân bài
# (tỉ lệ 1.00) và tiêu đề 12pt còn ra nhỏ hơn thân bài. Tín hiệu nhỏ hơn nhiễu
# nên không thể dùng.
#
# Bề rộng/ký tự tỉ lệ thuận với cỡ chữ và được lấy trung bình trên cả dòng: cùng
# phép đo đó cho nhiễu nội bộ thân bài chỉ 1.08 lần, còn tiêu đề nhỏ nhất vẫn
# cách 1.24 lần. Nhân 2.0 quy ngược ra point khá sát (H1 thật 22pt -> đo 22.2).
CHAR_WIDTH_TO_PT = 2.0
# Dòng ít hơn bấy nhiêu ký tự thì lấy cỡ trung vị của trang thay vì tự đo, vì
# mẫu quá nhỏ để trung bình hoá được nhiễu.
MIN_LINE_CHARS = 6
SIZE_CLAMP = (4.0, 96.0)


class TesseractMissing(RuntimeError):
    pass


@dataclass
class Engine:
    exe: str
    tessdata: str
    lang: str


def find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for p in TESSERACT_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def _resolve_tessdata(lang: str) -> str:
    """Chọn thư mục tessdata thật sự có file ngôn ngữ cần dùng."""
    wanted = {part for part in lang.split("+") if part}
    env = os.environ.get("TESSDATA_PREFIX")
    candidates = ([Path(env)] if env else []) + TESSDATA_CANDIDATES
    for d in candidates:
        if d.is_dir() and all((d / f"{w}.traineddata").exists() for w in wanted):
            return str(d)
    have = sorted(
        f.stem
        for d in candidates
        if d.is_dir()
        for f in d.glob("*.traineddata")
    )
    raise TesseractMissing(
        f"Không tìm thấy dữ liệu ngôn ngữ '{lang}'. "
        f"Các ngôn ngữ đang có: {', '.join(have) or 'không có'}. "
        f"Tải thêm tại https://github.com/tesseract-ocr/tessdata"
    )


def get_engine(lang: str = "vi") -> Engine:
    exe = find_tesseract()
    if not exe:
        raise TesseractMissing(
            "Chưa cài Tesseract. Cài bằng lệnh:\n"
            "    winget install --id tesseract-ocr.tesseract"
        )
    resolved = "+".join(LANG_ALIASES.get(p, p) for p in lang.split("+"))
    return Engine(exe=exe, tessdata=_resolve_tessdata(resolved), lang=resolved)


def _page_to_image(page, dpi: int):
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr_page_lines(engine: Engine, page, dpi: int = 300) -> list[Line]:
    """OCR một trang, trả về các Line theo đúng thứ tự đọc.

    Dùng image_to_data thay vì lấy text thuần: nó trả về khung của TỪNG TỪ kèm
    số hiệu block/paragraph/line do chính Tesseract phân tích. Nhờ vậy có sẵn
    quan hệ dòng và toạ độ để tầng layout dò tiêu đề, cột và bảng.
    """
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = engine.exe
    # Truyền thư mục tessdata qua biến môi trường, KHÔNG qua cờ --tessdata-dir:
    # pytesseract cắt chuỗi config bằng khoảng trắng, nên đường dẫn có dấu cách
    # (như "C:\Program Files\Tesseract-OCR\tessdata") sẽ bị xé làm nhiều mảnh,
    # còn nếu bọc nháy kép thì nháy bị giữ nguyên và lọt vào thành một phần của
    # đường dẫn.
    os.environ["TESSDATA_PREFIX"] = engine.tessdata

    img = _page_to_image(page, dpi)
    data = pytesseract.image_to_data(
        img,
        lang=engine.lang,
        # --dpi là BẮT BUỘC, không phải tuỳ chọn cho đẹp. Ảnh PIL truyền qua
        # pytesseract không mang theo metadata DPI, Tesseract đành tự đoán độ
        # phân giải, đoán sai thì tầng phân tích bố cục ÂM THẦM VỨT nguyên vùng
        # bảng có đường kẻ — không lỗi, không cảnh báo, chỉ thiếu dữ liệu.
        # Đo trên bản scan mẫu: thiếu cờ này ra 81 từ và mất sạch bảng, có cờ
        # thì ra 100 từ và bảng đầy đủ. Gán img.info["dpi"] không ăn thua vì
        # pytesseract không truyền tiếp.
        config=f"--psm 3 --dpi {dpi}",
        output_type=pytesseract.Output.DICT,
    )

    scale = 72.0 / dpi  # pixel ảnh -> point của PDF
    grouped: dict[tuple[int, int, int], list[dict]] = {}
    for i, text in enumerate(data["text"]):
        if not text or not text.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf < MIN_CONF:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "x0": data["left"][i] * scale,
                "y0": data["top"][i] * scale,
                "x1": (data["left"][i] + data["width"][i]) * scale,
                "y1": (data["top"][i] + data["height"][i]) * scale,
            }
        )

    if not grouped:
        return []

    for words in grouped.values():
        words.sort(key=lambda w: w["x0"])

    # Cỡ chữ đo trên CẢ DÒNG, không đo từng từ. Tiếng Việt đơn âm nên từ chỉ dài
    # 2-3 ký tự: lọc theo từng từ với ngưỡng 4 ký tự thì dòng "- Máy chủ ứng dụng
    # đặt tại Hà Nội" chỉ còn đúng một từ ("dụng") lọt lưới, và ước lượng dựa
    # trên một từ duy nhất nhiễu tới mức thân bài 11pt bị đo thành 10.8 rồi vọt
    # lên thành tiêu đề. Cộng dồn cả dòng thì trung bình hoá được nhiễu.
    measured = [(_line_wpc(ws), ws) for ws in grouped.values()]
    page_wpc = _median(
        [wpc for (wpc, n), _ws in measured if n >= MIN_LINE_CHARS and wpc > 0]
    )

    lines: list[Line] = []
    for (wpc, n), words in measured:
        size = _size_from_wpc(wpc if n >= MIN_LINE_CHARS and wpc > 0 else page_wpc)
        cells = _group_into_cells(words, size)
        spans = [
            Span(
                text=" ".join(w["text"] for w in cell)
                + (" " if i < len(cells) - 1 else ""),
                x0=cell[0]["x0"],
                y0=min(w["y0"] for w in cell),
                x1=cell[-1]["x1"],
                y1=max(w["y1"] for w in cell),
                size=size,
                font="OCR",
            )
            for i, cell in enumerate(cells)
        ]
        lines.append(Line(spans=spans))

    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


# Khoảng hở giữa hai từ vượt quá bấy nhiêu lần cỡ chữ thì coi là ranh giới ô bảng.
# Dấu cách thường rộng khoảng 0.25-0.35 lần cỡ chữ; kể cả khi căn đều hai bên bị
# giãn ra cũng hiếm khi vượt 1 lần. 1.5 lần thì chắc chắn là khoảng cách cột.
CELL_GAP_EM = 1.5


def _group_into_cells(words: list[dict], size: float) -> list[list[dict]]:
    """Gộp các từ trong một dòng thành ô, cắt tại những khoảng hở rộng bất thường.

    Bắt buộc phải làm bước này. Tầng dò bảng coi mỗi span là một ô — hợp đồng đó
    đúng với engine trả về từng vùng chữ, nhưng Tesseract trả về TỪNG TỪ một.
    Không gộp lại thì mỗi dòng văn 14 từ sẽ bị dò thành một hàng bảng 14 ô, và
    cả đoạn văn biến thành bảng.
    """
    if not words:
        return []
    cells: list[list[dict]] = []
    current = [words[0]]
    for prev, w in zip(words, words[1:]):
        if (w["x0"] - prev["x1"]) > size * CELL_GAP_EM:
            cells.append(current)
            current = [w]
        else:
            current.append(w)
    cells.append(current)
    return cells


def _line_wpc(words: list[dict]) -> tuple[float, int]:
    """Bề rộng trung bình mỗi ký tự của cả dòng, kèm số ký tự đã dùng để tính.

    Chỉ cộng bề rộng các từ, không tính khoảng hở giữa chúng — nếu tính cả hở
    thì dòng căn đều hai bên sẽ bị đo ra chữ to hơn thực tế.
    """
    total_w = sum(w["x1"] - w["x0"] for w in words)
    total_n = sum(len(w["text"].strip()) for w in words)
    return ((total_w / total_n) if total_n else 0.0, total_n)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _size_from_wpc(wpc: float) -> float:
    if wpc <= 0:
        wpc = 5.0
    return min(max(round(wpc * CHAR_WIDTH_TO_PT, 1), SIZE_CLAMP[0]), SIZE_CLAMP[1])
