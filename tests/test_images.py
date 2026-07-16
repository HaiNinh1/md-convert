"""Test xử lý ảnh.

Ảnh từng làm hỏng hẳn file .md: mammoth mặc định nhúng base64 vào markdown, nên
tài liệu 195 ảnh cho ra file nặng 25-76 MB, mỗi dòng ảnh dài hàng trăm nghìn ký
tự — trình soạn thảo treo, không đọc nổi chữ.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from mdconvert.router import convert_file


@pytest.fixture
def client():
    from mdconvert.web import app

    app.config["TESTING"] = True
    return app.test_client()


# --------------------------------------------------------------------------
# Không bao giờ được nhúng base64
# --------------------------------------------------------------------------

def test_khong_bao_gio_nhung_base64_khi_kem_anh(fixtures, tmp_path):
    md, _ = convert_file(fixtures["img_docx"], tmp_path, extract_images=True)
    assert "base64" not in md
    assert "data:image" not in md


def test_khong_bao_gio_nhung_base64_khi_bo_anh(fixtures, tmp_path):
    """Từng hỏng: extract_images=False chỉ đơn giản là không đặt convert_image,
    mà mammoth mặc định lại là data_uri — tức nhúng base64. Cờ tên nói 'không
    tách ảnh' nhưng hành vi thật là nhúng inline, thứ tệ nhất."""
    md, _ = convert_file(fixtures["img_docx"], tmp_path, extract_images=False)
    assert "base64" not in md
    assert "data:image" not in md


def test_bo_anh_thi_khong_de_lai_rac(fixtures, tmp_path):
    """_drop_image chặn base64 nhưng để lại <img /> rỗng, markdownify biến thành
    '![]()'. Phải strip luôn thẻ img."""
    md, _ = convert_file(fixtures["img_docx"], tmp_path, extract_images=False)
    assert "![]()" not in md
    assert "![](" not in md
    assert "# Tài liệu có ảnh" in md  # nội dung chữ vẫn còn nguyên


def test_kem_anh_thi_tach_ra_file_va_link_dung(fixtures, tmp_path):
    md, _ = convert_file(fixtures["img_docx"], tmp_path, extract_images=True)
    assets = tmp_path / f"{fixtures['img_docx'].stem}_assets"
    files = sorted(p.name for p in assets.iterdir())
    assert len(files) == 3
    for name in files:
        assert f"({assets.name}/{name})" in md, "link trong markdown phải trỏ đúng file"


def test_markdown_phai_gon_khong_phinh_vi_anh(fixtures, tmp_path):
    """Chốt chặn theo kích thước: markdown chỉ chứa CHỮ, ảnh nằm ở file riêng.
    Tài liệu mẫu có 3 ảnh; nếu nhúng base64 thì md phồng lên vài nghìn ký tự."""
    md, _ = convert_file(fixtures["img_docx"], tmp_path, extract_images=True)
    assert len(md) < 600, f"markdown phình bất thường ({len(md)} ký tự) — nghi nhúng ảnh"


# --------------------------------------------------------------------------
# Nhánh web
# --------------------------------------------------------------------------

def test_web_kem_anh_khong_base64(client, fixtures):
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["img_docx"].open("rb"), "co_anh.docx")], "images": "1"},
        content_type="multipart/form-data",
    )
    d = r.get_json()
    res = d["results"][0]
    assert res["ok"]
    assert "base64" not in res["markdown"]
    assert res["assets"] == 3
    assert d["token"]


def test_web_bo_anh(client, fixtures):
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["img_docx"].open("rb"), "co_anh.docx")], "images": "0"},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert res["assets"] == 0
    assert "![](" not in res["markdown"]


def test_web_zip_chua_ca_markdown_lan_anh(client, fixtures):
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["img_docx"].open("rb"), "co_anh.docx")], "images": "1"},
        content_type="multipart/form-data",
    )
    token = r.get_json()["token"]

    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/zip/{token}").data))
    names = set(z.namelist())
    assert "co_anh.md" in names
    assert len([n for n in names if n.startswith("co_anh_assets/")]) == 3
    # Ảnh trong zip phải là PNG thật, không phải text base64.
    png = next(n for n in names if n.endswith(".png"))
    assert z.read(png).startswith(b"\x89PNG")


def test_web_zip_token_sai_thi_bao_404(client):
    assert client.get("/api/zip/token-bay-dat").status_code == 404
