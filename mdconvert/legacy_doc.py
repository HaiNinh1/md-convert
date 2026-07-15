"""Chuyển file .doc đời cũ (Word 97-2003) sang .docx.

Vì sao phải có module này: .docx là ZIP chứa XML nên đọc thẳng được, còn .doc là
định dạng nhị phân OLE2 hoàn toàn khác — một thứ phức tạp, không công khai đầy
đủ, và viết bộ đọc riêng cho nó là dự án cỡ vài tháng. Cách đúng là nhờ phần mềm
đã biết đọc nó chuyển sang .docx rồi xử lý tiếp bằng đường cũ.

Thứ tự ưu tiên:
  1. Microsoft Word qua COM — bản gốc của định dạng này nên độ trung thực cao
     nhất, và máy Windows văn phòng gần như luôn có sẵn.
  2. LibreOffice headless — dự phòng khi không có Word.

Cả hai đều chạy offline, không gọi API nào.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# wdFormatDocumentDefault — định dạng mặc định của Word 2007 trở lên, tức .docx
WD_FORMAT_DOCX = 16

# Các mã WdSaveFormat cho biết Word đã BỎ CUỘC và đọc file như văn bản thuần.
#
# Đây là chốt chặn quan trọng. Word rất "nhiệt tình": đưa nó một file .doc hỏng
# hay file rác mang đuôi .doc, nó không báo lỗi mà lặng lẽ đọc từng byte nhị phân
# thành ký tự. Kết quả là markdown chứa rác kiểu 'ﾐﾏ・' (chính là 4 byte chữ ký
# OLE2 D0 CF 11 E0 bị diễn giải thành chữ) mà app lại báo THÀNH CÔNG — tệ hơn cả
# báo lỗi, vì người dùng tưởng file đã chuyển xong.
#
# May là Word tự khai: thuộc tính SaveFormat cho biết nó hiểu file là gì. File
# .doc thật cho 0 (wdFormatDocument97); file rác cho 7 (wdFormatEncodedText).
WD_TEXT_FALLBACK_FORMATS = {
    2,  # wdFormatText
    3,  # wdFormatTextLineBreaks
    4,  # wdFormatDOSText
    5,  # wdFormatDOSTextLineBreaks
    7,  # wdFormatEncodedText
}


class NotAWordFile(RuntimeError):
    """File có vỏ OLE2 nhưng ruột không phải tài liệu Word."""

SOFFICE_CANDIDATES = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]

CONVERT_TIMEOUT = 180


class NoConverter(RuntimeError):
    """Không có Word lẫn LibreOffice trên máy."""


def find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for p in SOFFICE_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def has_word() -> bool:
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    try:
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001
        return False
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Quit()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass


def available() -> str | None:
    """Tên công cụ sẽ dùng, hoặc None nếu máy không có gì chuyển được .doc."""
    if has_word():
        return "Microsoft Word"
    if find_soffice():
        return "LibreOffice"
    return None


def _via_word(src: Path, dest: Path) -> None:
    import pythoncom
    import win32com.client

    # CoInitialize là BẮT BUỘC: Flask xử lý mỗi request trong một luồng riêng, và
    # luồng nền của GUI cũng vậy. COM chưa khởi tạo trên luồng đó thì Dispatch nổ
    # "CoInitialize has not been called".
    pythoncom.CoInitialize()
    word = None
    try:
        # DispatchEx tạo tiến trình Word RIÊNG, không chiếm dụng cửa sổ Word mà
        # người dùng đang mở — nếu không, thao tác của ta sẽ quấy nhiễu họ và
        # Quit() có thể đóng luôn tài liệu họ đang viết dở.
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # không bật hộp thoại nào, tránh treo vô hạn

        doc = word.Documents.Open(
            str(src.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        try:
            fmt = int(doc.SaveFormat)
            if fmt in WD_TEXT_FALLBACK_FORMATS:
                raise NotAWordFile(
                    f"Word không đọc được đây như một tài liệu Word — nó phải lùi về "
                    f"đọc như văn bản thuần (SaveFormat={fmt}). File nhiều khả năng "
                    f"bị hỏng, chép dở, hoặc chỉ là file khác được đổi tên đuôi "
                    f"thành .doc."
                )
            doc.SaveAs2(str(dest.resolve()), FileFormat=WD_FORMAT_DOCX)
        finally:
            doc.Close(SaveChanges=0)
    finally:
        # Bắt buộc Quit kể cả khi lỗi, không thì tiến trình WINWORD.EXE ẩn tích tụ
        # dần trong Task Manager cho tới khi hết RAM.
        if word is not None:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass


def _via_soffice(src: Path, dest: Path) -> None:
    soffice = find_soffice()
    if not soffice:
        raise NoConverter("Không tìm thấy LibreOffice")

    with tempfile.TemporaryDirectory(prefix="soffice-") as tmp:
        subprocess.run(
            [
                soffice, "--headless", "--norestore",
                "--convert-to", "docx", "--outdir", tmp, str(src.resolve()),
            ],
            check=True,
            capture_output=True,
            timeout=CONVERT_TIMEOUT,
        )
        made = list(Path(tmp).glob("*.docx"))
        if not made:
            raise NoConverter("LibreOffice chạy xong nhưng không tạo ra file .docx nào")
        shutil.move(str(made[0]), dest)


def to_docx(src: Path, dest: Path) -> str:
    """Chuyển .doc sang .docx. Trả về tên công cụ đã dùng.

    Ném NoConverter nếu máy không có Word lẫn LibreOffice.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    last: Exception | None = None
    if has_word():
        try:
            _via_word(src, dest)
            if dest.exists() and dest.stat().st_size > 0:
                return "Microsoft Word"
        except NotAWordFile:
            # Kết luận dứt khoát: file này không phải tài liệu Word. Thử tiếp
            # LibreOffice chỉ tổ mất thời gian rồi cũng ra rác y hệt.
            raise
        except Exception as e:  # noqa: BLE001
            # Còn lại có thể là file bị khoá, COM trục trặc... LibreOffice biết
            # đâu lại mở được, cứ thử hơn là bỏ cuộc ngay.
            last = e

    if find_soffice():
        _via_soffice(src, dest)
        if dest.exists() and dest.stat().st_size > 0:
            return "LibreOffice"

    if last is not None:
        raise NoConverter(f"Microsoft Word không mở được file này: {last}")
    raise NoConverter(
        "Máy chưa có công cụ đọc được .doc đời cũ. Cần Microsoft Word, "
        "hoặc cài LibreOffice miễn phí: winget install --id TheDocumentFoundation.LibreOffice"
    )
