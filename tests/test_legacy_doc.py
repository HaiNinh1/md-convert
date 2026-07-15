"""Test file .doc đời cũ (Word 97-2003).

Định dạng .doc là nhị phân OLE2, không phải ZIP/XML như .docx. Không có bộ đọc
thuần Python nào đủ tin cậy, nên app nhờ Microsoft Word (hoặc LibreOffice) chuyển
sang .docx rồi đi tiếp bằng đường cũ.
"""

from __future__ import annotations

import pytest

from mdconvert import legacy_doc
from mdconvert.office import LegacyDocError, is_legacy_doc
from mdconvert.router import convert_file

needs_doc = pytest.mark.skipif(
    legacy_doc.available() is None,
    reason="máy không có Microsoft Word lẫn LibreOffice",
)


def test_nhan_dien_doc_bang_chu_ky_file(tmp_path, fixtures):
    """Phải nhận diện bằng chữ ký OLE2, không tin phần đuôi file."""
    ole = tmp_path / "gia-danh.docx"  # đuôi .docx nhưng ruột là .doc
    ole.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    assert is_legacy_doc(ole)
    assert not is_legacy_doc(fixtures["docx"])


@needs_doc
def test_doc_tu_dong_chuyen_va_giu_cau_truc(fixtures, tmp_path):
    """Từng hỏng: app bắt người dùng tự chạy 'soffice --convert-to docx' thủ công,
    mà lệnh đó còn trỏ vào thư mục tạm đã bị xoá nên chạy cũng vô ích."""
    if "doc" not in fixtures:
        pytest.skip("không tạo được file .doc mẫu")

    md, stats = convert_file(fixtures["doc"], tmp_path)
    assert stats["converted_from"] == ".doc"
    assert stats["converted_by"] in ("Microsoft Word", "LibreOffice")

    assert "# Giải pháp và Phương pháp luận" in md
    assert "## 1. Phạm vi áp dụng" in md
    assert "**chữ đậm**" in md
    assert "*chữ nghiêng*" in md
    assert "- Mục thứ nhất" in md
    assert "| Máy chủ | 12 triệu | Đã duyệt |" in md


@needs_doc
def test_doc_qua_web(fixtures, tmp_path):
    if "doc" not in fixtures:
        pytest.skip("không tạo được file .doc mẫu")
    from mdconvert.web import app

    client = app.test_client()
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["doc"].open("rb"), "GIAI PHAP VA PP LUAN AGG.doc")]},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert res["ok"], res.get("error")
    assert res["out"] == "GIAI PHAP VA PP LUAN AGG.md"
    assert "# Giải pháp và Phương pháp luận" in res["markdown"]


@needs_doc
def test_doc_rac_phai_bao_loi_chu_khong_ra_markdown_rac(tmp_path):
    """Từng hỏng NGHIÊM TRỌNG — sai mà báo đúng, tệ hơn cả báo lỗi.

    Word rất "nhiệt tình": đưa nó file .doc rác, nó không từ chối mà lặng lẽ đọc
    từng byte nhị phân thành ký tự, cho ra markdown 'ﾐﾏ・' (chính là chữ ký OLE2
    D0 CF 11 E0 bị diễn giải thành chữ) — và app báo THÀNH CÔNG. Người dùng nhận
    file .md chứa rác mà tưởng đã xong.

    Chốt chặn: chính Word tự khai qua thuộc tính SaveFormat. File .doc thật cho 0
    (wdFormatDocument97), file rác cho 7 (wdFormatEncodedText) — tức nó đã bỏ
    cuộc và lùi về đọc như văn bản thuần.
    """
    fake = tmp_path / "hong.doc"
    fake.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)  # vỏ OLE2, ruột rỗng

    with pytest.raises(LegacyDocError) as e:
        convert_file(fake, tmp_path / "ra")
    msg = str(e.value)
    assert "hong.doc" in msg
    # Không được chỉ người dùng chạy lệnh trỏ vào thư mục tạm — nó bị xoá ngay
    # sau đó nên lệnh đó vô dụng. Đây là lỗi của thông báo cũ.
    assert "AppData" not in msg
    assert "mdconvert-" not in msg


def test_khong_co_cong_cu_thi_bao_cach_cai(tmp_path, monkeypatch):
    """Máy không có Word lẫn LibreOffice thì phải chỉ rõ cách khắc phục."""
    monkeypatch.setattr(legacy_doc, "has_word", lambda: False)
    monkeypatch.setattr(legacy_doc, "find_soffice", lambda: None)

    fake = tmp_path / "cu.doc"
    fake.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    with pytest.raises(LegacyDocError, match="LibreOffice"):
        convert_file(fake, tmp_path / "ra")
