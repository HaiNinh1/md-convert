"""Test hồi quy. Mỗi test dưới đây ứng với một lỗi ĐÃ THẬT SỰ xảy ra khi dựng
dự án, không phải lỗi giả định. Phần docstring ghi lại triệu chứng để người sau
biết vì sao ngưỡng lại đặt ở con số đó.
"""

from __future__ import annotations

import re

import pytest

from mdconvert.layout import BULLET_RE, _gap_thresholds, detect_body_size
from mdconvert.ocr import find_tesseract
from mdconvert.router import convert_file

needs_tesseract = pytest.mark.skipif(
    find_tesseract() is None, reason="chưa cài Tesseract"
)


def structure(md: str) -> list[str]:
    """Rút gọn markdown thành chuỗi loại khối, để so cấu trúc mà bỏ qua sai chính tả."""
    out = []
    for line in md.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            out.append(s.split(" ")[0])
        elif s.startswith("|"):
            out.append("TBL")
        elif re.match(r"^[-*]\s|^\d+\.\s", s):
            out.append("LIST")
        else:
            out.append("P")
    return out


# --------------------------------------------------------------------------
# PDF có lớp text
# --------------------------------------------------------------------------

def test_pdf_structure(fixtures, tmp_path):
    md, stats = convert_file(fixtures["pdf"], tmp_path)
    assert structure(md) == ["#", "##", "P", "P", "##", "LIST", "LIST", "###"] + ["TBL"] * 4
    assert stats["tables"] == 1


def test_pdf_giu_dau_tieng_viet(fixtures, tmp_path):
    md, _ = convert_file(fixtures["pdf"], tmp_path)
    assert "# Báo cáo Kỹ thuật Quý IV" in md
    assert "Hệ thống được triển khai trên nền tảng đám mây" in md
    assert "| Máy chủ | 12 triệu | Đã thanh toán |" in md


def test_tieu_de_khong_bi_tuot_thanh_danh_sach(fixtures, tmp_path):
    """Từng hỏng: HEADING_MAX_SHARE=0.12 loại nhầm tiêu đề 15pt vì nó chiếm
    12.3% ký tự — hoàn toàn bình thường với tài liệu ngắn — khiến "1. Tổng quan
    hệ thống" rơi xuống thành mục danh sách đánh số."""
    md, _ = convert_file(fixtures["pdf"], tmp_path)
    assert "## 1. Tổng quan hệ thống" in md
    assert "## 2. Danh mục thiết bị" in md
    assert not re.search(r"^\d+\. \*\*Tổng quan", md, re.M)


def test_khong_con_khoang_trang_la(fixtures, tmp_path):
    """Từng hỏng: font Times New Roman làm PyMuPDF trích dấu cách thường ra thành
    U+00A0 NON-BREAKING SPACE. Nhìn bằng mắt không thấy gì bất thường vì NBSP
    trông y hệt dấu cách, nhưng nó phá grep và phá copy-paste. Chỉ so khớp chuỗi
    mới lộ ra."""
    md, _ = convert_file(fixtures["pdf"], tmp_path)
    for bad in [" ", " ", " ", "​", "﻿"]:
        assert bad not in md, f"còn sót ký tự khoảng trắng lạ U+{ord(bad):04X}"


def test_bullet_soft_hyphen():
    """Từng hỏng: gõ dấu trừ ASCII trong Word với font Times New Roman, PyMuPDF
    trích ra thành U+00AD SOFT HYPHEN, BULLET_RE trượt, cả danh sách dính thành
    một đoạn văn."""
    assert BULLET_RE.match("­ Máy chủ ứng dụng")
    assert BULLET_RE.match("- Máy chủ ứng dụng")
    assert BULLET_RE.match("• Máy chủ ứng dụng")
    assert BULLET_RE.match("– Máy chủ ứng dụng")
    assert not BULLET_RE.match("-khong co dau cach")


def test_bullet_nhan_dien_trong_pdf(fixtures, tmp_path):
    md, _ = convert_file(fixtures["pdf"], tmp_path)
    assert "- Máy chủ ứng dụng đặt tại Hà Nội" in md
    assert "- Thiết bị lưu trữ dự phòng ở Đà Nẵng" in md


def test_tach_doan_van(fixtures, tmp_path):
    """Từng hỏng: typical_gap lấy trung vị của MỌI cặp dòng nên bị khoảng cách
    trước tiêu đề và giữa ô bảng kéo lên 8.65, ngưỡng tách đoạn thành 15.56,
    trong khi chỗ xuống đoạn thật chỉ cách 12.26 nên hai đoạn dính làm một."""
    md, _ = convert_file(fixtures["pdf"], tmp_path)
    assert md.count("Hệ thống được triển khai") == 1
    body = [l for l in md.split("\n") if l.startswith(("Hệ thống", "Đoạn thứ hai"))]
    assert len(body) == 2, "hai đoạn văn phải tách rời"


def test_gap_thresholds_bo_qua_dong_khac_co_chu():
    """Ngưỡng tách đoạn chỉ được đo trên dòng cùng cỡ thân bài."""
    from mdconvert.model import Line, Span

    def line(y: float, size: float) -> Line:
        return Line(spans=[Span(text="x" * 30, x0=0, y0=y, x1=100, y1=y + size, size=size)])

    lines = [line(0, 20)] + [line(20 + i * 14, 10) for i in range(6)]
    typical, para = _gap_thresholds(lines, body_size=10.0)
    assert typical == pytest.approx(4.0, abs=0.6)
    assert para > typical


# --------------------------------------------------------------------------
# PDF scan (OCR)
# --------------------------------------------------------------------------

@needs_tesseract
def test_scan_cau_truc_khop_pdf_so(fixtures, tmp_path):
    """Bản scan thuần ảnh phải cho ra cấu trúc y hệt bản PDF số."""
    goc, _ = convert_file(fixtures["pdf"], tmp_path)
    scan, stats = convert_file(fixtures["scan"], tmp_path)
    assert stats["ocr_pages"] == 1
    assert structure(scan) == structure(goc)


@needs_tesseract
def test_scan_doc_duoc_dau_tieng_viet(fixtures, tmp_path):
    """Từng hỏng: model latin_PP-OCRv3 của RapidOCR thiếu 53/74 ký tự tiếng Việt
    trong từ điển đầu ra nên "Báo cáo" ra "Bao cao". Tesseract + vie đọc đúng."""
    md, _ = convert_file(fixtures["scan"], tmp_path)
    assert "Báo cáo Kỹ thuật Quý IV" in md
    assert "Tổng quan hệ thống" in md
    assert "Máy chủ ứng dụng đặt tại Hà Nội" in md


@needs_tesseract
def test_scan_khong_mat_bang(fixtures, tmp_path):
    """Từng hỏng: thiếu cờ --dpi, Tesseract đoán sai độ phân giải rồi ÂM THẦM
    vứt nguyên vùng bảng có đường kẻ — 81 từ thay vì 100, không một cảnh báo."""
    md, stats = convert_file(fixtures["scan"], tmp_path)
    assert stats["tables"] == 1
    assert "Hạng mục" in md
    assert "12 triệu" in md


@needs_tesseract
def test_scan_doan_van_khong_thanh_bang(fixtures, tmp_path):
    """Từng hỏng: Tesseract trả về TỪNG TỪ một span, tầng dò bảng coi span là ô
    nên dòng văn 14 từ thành hàng bảng 14 ô, cả đoạn văn biến thành bảng."""
    md, _ = convert_file(fixtures["scan"], tmp_path)
    assert "| Hệ | thống |" not in md
    assert "Hệ thống được" in md.replace("triền", "triển")


@needs_tesseract
def test_scan_bullet_khong_thanh_tieu_de(fixtures, tmp_path):
    """Từng hỏng: lọc từ ≥4 ký tự để đo cỡ chữ làm dòng tiếng Việt chỉ còn 1 từ
    lọt lưới (từ tiếng Việt đơn âm, 2-3 ký tự), ước lượng nhiễu tới mức thân bài
    11pt đo thành 10.8 rồi vọt lên thành tiêu đề H3."""
    md, _ = convert_file(fixtures["scan"], tmp_path)
    assert not re.search(r"^#+ *- Máy chủ", md, re.M)
    assert re.search(r"^- Máy chủ", md, re.M)


# --------------------------------------------------------------------------
# Word / Excel
# --------------------------------------------------------------------------

def test_docx_cau_truc_va_dinh_dang(fixtures, tmp_path):
    md, stats = convert_file(fixtures["docx"], tmp_path)
    assert stats["source"] == "docx"
    assert "# Tài liệu Word mẫu" in md
    assert "## Mục con" in md
    assert "**chữ đậm**" in md
    assert "*chữ nghiêng*" in md
    assert "- Mục bullet thứ nhất" in md


def test_docx_bang_co_hang_tieu_de_that(fixtures, tmp_path):
    """Từng hỏng: bảng Word không đánh dấu Header Row nên markdownify đẻ ra hàng
    tiêu đề rỗng '|  |  |', đẩy hàng tiêu đề thật xuống thành dữ liệu."""
    md, _ = convert_file(fixtures["docx"], tmp_path)
    assert "| Cột A | Cột B | Cột C |" in md
    assert not re.search(r"^\|(\s*\|)+$", md, re.M), "còn hàng tiêu đề rỗng"


def test_xlsx(fixtures, tmp_path):
    md, stats = convert_file(fixtures["xlsx"], tmp_path)
    assert stats["source"] == "xlsx"
    assert "## DuLieu" in md
    assert "| Tháng | Doanh thu |" in md


def test_doc_doi_cu_bao_loi_ro_rang(tmp_path):
    """.doc nhị phân không phải ZIP/XML — phải báo cách xử lý, không đổ stack."""
    from mdconvert.office import LegacyDocError

    fake = tmp_path / "cu.doc"
    fake.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)  # chữ ký OLE2
    with pytest.raises(LegacyDocError, match="convert-to docx"):
        convert_file(fake, tmp_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_khong_de_mat_file_khi_trung_ten(fixtures, tmp_path):
    """Từng hỏng: 'sample.docx' và 'sample.xlsx' cùng ra 'sample.md', file sau
    đè mất file trước mà vẫn báo '2/2 thành công'."""
    from mdconvert.cli import plan_outputs

    plan = plan_outputs([fixtures["docx"], fixtures["xlsx"]], tmp_path)
    assert len(set(plan.values())) == 2, "hai nguồn khác nhau không được cùng một đích"


def test_khong_trung_ten_thi_giu_ten_sach(fixtures, tmp_path):
    from mdconvert.cli import plan_outputs

    plan = plan_outputs([fixtures["docx"]], tmp_path)
    assert plan[fixtures["docx"]].name == "sample.md"


def test_body_size_tinh_theo_so_ky_tu():
    """Cỡ thân bài phải tính theo số KÝ TỰ, không theo số dòng: một trang bìa có
    vài dòng tiêu đề to sẽ chiếm đa số dòng nhưng rất ít ký tự."""
    from mdconvert.model import Line, Span

    lines = [
        Line(spans=[Span(text="TIEU DE", x0=0, y0=0, x1=90, y1=20, size=24)]),
        Line(spans=[Span(text="TIEU DE 2", x0=0, y0=30, x1=90, y1=50, size=24)]),
        Line(spans=[Span(text="x" * 200, x0=0, y0=60, x1=90, y1=70, size=10)]),
    ]
    assert detect_body_size(lines) == 10.0
