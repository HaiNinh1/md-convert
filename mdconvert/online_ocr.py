"""OCR online độ chính xác cao qua OCR.space — tùy chọn, KHÔNG bật mặc định.

Vì sao có file này: Tesseract offline đọc scan tiếng Việt hay sai DẤU ở những từ
mà bản thân từ sai vẫn có nghĩa ("hạ tâng" vs "hạ tầng", "Cô phân" vs "Cổ phần").
Muốn sửa phải hiểu ngữ cảnh — thứ mà từ điển offline không làm được. OCR.space
Engine 2 có model mạnh hơn hẳn, đọc đúng các trường hợp đó (đã đo thực tế).

Đánh đổi: phải có mạng và gửi ảnh trang lên dịch vụ. Nên đây chỉ là CHẾ ĐỘ TÙY
CHỌN; mặc định vẫn là Tesseract offline theo đúng tinh thần của app.

Cấu hình khoá (chủ máy làm MỘT lần, mọi người dùng chung):
  - Đặt biến môi trường OCRSPACE_API_KEY, HOẶC
  - Tạo file "ocrspace_key.txt" ở thư mục gốc dự án (cạnh Mo-giao-dien-web.bat)
    rồi dán khoá vào đó.
Lấy khoá miễn phí tại https://ocr.space/ocrapi (đăng ký bằng email).

Quan trọng về tham số: Engine 2 KHÔNG nhận tham số 'language' (gửi vào báo lỗi
E201). Nó tự nhận diện chữ Latin có dấu, nên cứ để trống là đọc đúng tiếng Việt.
"""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .runtime import exe_dir, resource_dir

# OCR.space (overlay) trả dấu câu thành "từ" riêng. Khi nối lại phải bỏ khoảng
# trắng thừa trước dấu đóng và sau dấu mở, nếu không sẽ ra "Điều 1 ." / "( a".
_NO_SPACE_BEFORE = set(",.;:!?%)]}’”")
_NO_SPACE_AFTER = set("([{‘“")


def _join_words(cell: list[dict]) -> str:
    out = ""
    for i, w in enumerate(cell):
        t = w["text"]
        if i and t[:1] not in _NO_SPACE_BEFORE and out[-1:] not in _NO_SPACE_AFTER:
            out += " "
        out += t
    return out

OCRSPACE_URL = "https://api.ocr.space/parse/image"
KEY_ENV = "OCRSPACE_API_KEY"
# Ưu tiên khoá đặt CẠNH file .exe (chủ máy đổi được không cần đóng gói lại),
# rồi tới khoá đi kèm trong bản đóng gói, rồi bản ở gốc dự án khi chạy mã nguồn.
KEY_FILE_CANDIDATES = [
    exe_dir() / "ocrspace_key.txt",
    resource_dir() / "ocrspace_key.txt",
    Path(__file__).parent.parent / "ocrspace_key.txt",
    Path.home() / ".ocrspace_key",
]

# Khoá thử công khai của OCR.space, dùng để kiểm thử khi chủ máy chưa cấu hình
# khoá riêng. Bị giới hạn ngặt (vài lần/phút) nên KHÔNG dùng cho việc thật.
DEMO_KEY = "helloworld"

# Giới hạn dung lượng ảnh gửi lên (bản miễn phí ~1 MB). Ảnh vùng cắt thường nhỏ,
# còn ảnh cả trang được nén JPEG + hạ cạnh dài xuống mức này cho lọt.
MAX_UPLOAD_BYTES = 1024 * 1024
MAX_SIDE_PX = 2500


class OnlineOCRError(RuntimeError):
    pass


def get_api_key() -> str | None:
    """Khoá do chủ máy cấu hình; None nếu chưa có (khi đó UI ẩn chế độ online)."""
    v = os.environ.get(KEY_ENV)
    if v and v.strip():
        return v.strip()
    for f in KEY_FILE_CANDIDATES:
        try:
            if f.is_file():
                t = f.read_text(encoding="utf-8").strip()
                if t:
                    return t
        except OSError:
            continue
    return None


def available() -> bool:
    return get_api_key() is not None


def _encode_image(image) -> bytes:
    """PIL Image -> bytes JPEG đủ nhỏ để lọt giới hạn của bản miễn phí."""
    from PIL import Image

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    # Hạ cạnh dài nếu quá lớn — vẫn thừa nét để đọc, mà nhẹ đi nhiều.
    long_side = max(image.size)
    if long_side > MAX_SIDE_PX:
        r = MAX_SIDE_PX / long_side
        image = image.resize((max(1, int(image.width * r)), max(1, int(image.height * r))))

    for quality in (92, 85, 75, 60):
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= MAX_UPLOAD_BYTES:
            return data
    return data  # đã nén hết mức; cứ gửi, quá cỡ thì server tự báo


def _request(image_bytes: bytes, *, api_key: str, overlay: bool, timeout: int = 90) -> dict:
    b64 = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    form = {
        "apikey": api_key,
        "base64Image": b64,
        "OCREngine": "2",  # Engine 2: đọc tốt tiếng Việt, KHÔNG kèm 'language'.
        "isOverlayRequired": "true" if overlay else "false",
        "scale": "true",
        "detectOrientation": "true",
    }
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(OCRSPACE_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OnlineOCRError(
            f"Không gọi được dịch vụ OCR online (kiểm tra mạng): {e.reason}"
        ) from e
    except (ValueError, TimeoutError) as e:
        raise OnlineOCRError(f"Dịch vụ OCR online trả về dữ liệu lỗi: {e}") from e

    if payload.get("OCRExitCode") != 1:
        msg = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "không rõ"
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        # Thông báo hết hạn mức của OCR.space rất hay gặp với bản miễn phí.
        raise OnlineOCRError(f"OCR online báo lỗi: {msg}")
    results = payload.get("ParsedResults") or []
    if not results:
        raise OnlineOCRError("OCR online không trả về kết quả nào.")
    return results[0]


def ocr_image_text_online(image, *, api_key: str | None = None) -> str:
    """OCR một ảnh/vùng qua OCR.space, trả về chữ thuần. Dùng cho công cụ chọn vùng."""
    key = api_key or get_api_key()
    if not key:
        raise OnlineOCRError(
            "Chưa cấu hình khoá OCR online. Đặt biến OCRSPACE_API_KEY hoặc tạo "
            "file ocrspace_key.txt ở thư mục dự án."
        )
    result = _request(_encode_image(image), api_key=key, overlay=False)
    return (result.get("ParsedText") or "").strip()


def ocr_page_lines_online(page, *, dpi: int = 200, api_key: str | None = None):
    """OCR một trang PDF qua OCR.space, trả về list[Line] như nhánh Tesseract.

    Dùng overlay của OCR.space để lấy khung TỪNG TỪ, rồi dựng lại Line/Span y hệt
    ocr_page_lines — nhờ vậy toàn bộ tầng phân tích bố cục (tiêu đề, cột, bảng)
    dùng chung, không cần biết chữ đến từ engine nào.
    """
    from PIL import Image

    from .ocr import (
        MIN_LINE_CHARS,
        _group_into_cells,
        _line_wpc,
        _median,
        _size_from_wpc,
    )
    from .model import Line, Span

    key = api_key or get_api_key()
    if not key:
        raise OnlineOCRError(
            "Chưa cấu hình khoá OCR online. Đặt biến OCRSPACE_API_KEY hoặc tạo "
            "file ocrspace_key.txt ở thư mục dự án."
        )

    pix = page.get_pixmap(dpi=dpi, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    result = _request(_encode_image(img), api_key=key, overlay=True)

    overlay = result.get("TextOverlay") or {}
    overlay_lines = overlay.get("Lines") or []
    scale = 72.0 / dpi  # pixel ảnh -> point PDF, khớp quy ước ở ocr.py

    measured = []
    for oline in overlay_lines:
        words = []
        for w in oline.get("Words") or []:
            text = (w.get("WordText") or "").strip()
            if not text:
                continue
            left, top = float(w["Left"]), float(w["Top"])
            width, height = float(w["Width"]), float(w["Height"])
            words.append({
                "text": text,
                "x0": left * scale, "y0": top * scale,
                "x1": (left + width) * scale, "y1": (top + height) * scale,
            })
        if words:
            words.sort(key=lambda d: d["x0"])
            measured.append((_line_wpc(words), words))

    if not measured:
        return []

    page_wpc = _median(
        [wpc for (wpc, n), _w in measured if n >= MIN_LINE_CHARS and wpc > 0]
    )

    lines: list[Line] = []
    for (wpc, n), words in measured:
        size = _size_from_wpc(wpc if n >= MIN_LINE_CHARS and wpc > 0 else page_wpc)
        cells = _group_into_cells(words, size)
        spans = [
            Span(
                text=_join_words(cell)
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
