"""Test đôn tiêu đề theo số mục cho nhánh Word.

Nhánh Word đọc thẳng Heading style mà Word ghi sẵn — đúng nguyên tắc, nhưng tài
liệu thật thường dùng style nửa vời. Đo trên một hồ sơ thầu thật: "3.1." và
"3.1.1." chỉ bôi đậm tay nên ra đoạn văn thường, còn "3.1.1.1." lại có Heading
style. 22 dòng lẽ ra là tiêu đề bị bỏ lỡ.
"""

from __future__ import annotations

import pytest

from mdconvert.office import promote_numbered_headings
from mdconvert.router import convert_file


def promote(md: str) -> str:
    return promote_numbered_headings(md)[0]


# --------------------------------------------------------------------------
# Cấp tiêu đề lấy từ số mục
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, expected",
    [
        ("3.1. Hiểu rõ mục đích gói thầu", "## 3.1. Hiểu rõ mục đích gói thầu"),
        ("3.1.1. Công tác khảo sát", "### 3.1.1. Công tác khảo sát"),
        ("3.1.1.1. Giới thiệu chung:", "#### 3.1.1.1. Giới thiệu chung:"),
        ("3.2.2.1.1. Tiêu chuẩn áp dụng:", "##### 3.2.2.1.1. Tiêu chuẩn áp dụng:"),
    ],
)
def test_cap_tieu_de_lay_tu_so_muc(line, expected):
    assert promote(line).strip() == expected


def test_danh_lai_cap_cho_tieu_de_word_da_dat():
    """Word đặt cấp không nhất quán: 4 cấp số ra H3, 5 cấp số ra H5. Số mục là
    tín hiệu không nhiễu nên lấy nó làm chuẩn cho cả những dòng đã là tiêu đề."""
    assert promote("### 3.1.1.1. Giới thiệu chung:").strip() == "#### 3.1.1.1. Giới thiệu chung:"


def test_tieu_de_tai_lieu_boi_dam_thanh_h1():
    md = "**GIẢI PHÁP VÀ PHƯƠNG PHÁP LUẬN**\n\nĐoạn văn thường.\n"
    assert "# GIẢI PHÁP VÀ PHƯƠNG PHÁP LUẬN" in promote(md)


def test_chu_dam_khong_bi_nham_la_muc_danh_sach():
    """Từng hỏng: loại dòng danh sách bằng s.startswith(("-", "*", ...)) nên
    "**Tiêu đề**" bị nuốt luôn, vì chữ đậm markdown cũng mở đầu bằng '*'. Dấu
    danh sách phải đi kèm khoảng trắng mới tính."""
    assert promote("**Tiêu đề tài liệu**").strip() == "# Tiêu đề tài liệu"


# --------------------------------------------------------------------------
# Các cái bẫy — KHÔNG được đôn lên tiêu đề
# --------------------------------------------------------------------------

def test_muc_danh_sach_mot_cap_khong_thanh_tieu_de():
    """Bẫy có thật trong tài liệu: "1. Mỗi đội khảo sát gồm 01 cán bộ." là mục
    danh sách. Yêu cầu số mục có ÍT NHẤT 2 cấp thì nó tự bị loại."""
    line = "1. Mỗi đội khảo sát gồm 01 cán bộ khảo sát"
    assert not promote(line).strip().startswith("#")


def test_doan_van_dai_mo_dau_bang_so_muc_khong_thanh_tieu_de():
    """Bẫy có thật: "3.3. Theo quy định tại mục 3.1. của hợp đồng, nhà thầu phải
    hoàn thành..." có 2 cấp số nhưng là câu văn, không phải tiêu đề."""
    line = ("3.3. Theo quy định tại mục 3.1. của hợp đồng, nhà thầu phải hoàn thành "
            "toàn bộ công tác khảo sát và bàn giao hồ sơ trước thời hạn đã nêu.")
    assert not promote(line).strip().startswith("#")


def test_dong_ket_thuc_bang_dau_cham_khong_thanh_tieu_de():
    assert not promote("3.1. Đây là một câu văn hoàn chỉnh.").strip().startswith("#")


def test_khong_dung_vao_bang():
    md = "| 3.1. Hạng mục | Giá |\n| --- | --- |\n"
    assert promote(md) == md


def test_khong_dung_vao_khoi_ma():
    md = "```\n3.1. day la code\n```\n"
    assert promote(md) == md


def test_khong_dung_vao_muc_danh_sach_da_co():
    md = "- 3.1. Mục con trong danh sách\n"
    assert promote(md) == md


# --------------------------------------------------------------------------
# Chạy thật qua file .docx
# --------------------------------------------------------------------------

def test_toan_bo_qua_file_docx(fixtures, tmp_path):
    md, stats = convert_file(fixtures["heading_docx"], tmp_path)
    assert stats["promoted_headings"] >= 5

    assert "# GIẢI PHÁP VÀ PHƯƠNG PHÁP LUẬN TỔNG QUÁT" in md
    assert "## 3.1. Hiểu rõ mục đích gói thầu" in md
    assert "### 3.1.1. Am hiểu về mục tiêu" in md
    assert "#### 3.1.1.1. Giới thiệu chung về dự án:" in md
    assert "##### 3.2.2.1.1. Các tiêu chuẩn áp dụng:" in md

    for trap in ("1. Mỗi đội khảo sát", "3.3. Theo quy định tại mục"):
        line = next(l for l in md.split("\n") if trap in l)
        assert not line.startswith("#"), f"bẫy bị đôn nhầm: {line[:50]}"
