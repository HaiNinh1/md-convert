"""Test giao diện web."""

from __future__ import annotations

import io
import zipfile

import pytest

from mdconvert.ocr import find_tesseract

needs_tesseract = pytest.mark.skipif(
    find_tesseract() is None, reason="chưa cài Tesseract"
)


@pytest.fixture
def client():
    from mdconvert.web import app

    app.config["TESTING"] = True
    return app.test_client()


def test_trang_chu(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode()
    assert "Kéo thả tài liệu" in html
    assert "/api/convert" in html


def test_convert_word_qua_web(client, fixtures):
    r = client.post(
        "/api/convert",
        data={
            "files": [(fixtures["docx"].open("rb"), "Hợp đồng.docx")],
            "lang": "vie",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    res = r.get_json()["results"]
    assert len(res) == 1 and res[0]["ok"]
    assert res[0]["out"] == "Hợp đồng.md"
    assert "**chữ đậm**" in res[0]["markdown"]


def test_convert_pdf_giu_dau_tieng_viet(client, fixtures):
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["pdf"].open("rb"), "Báo cáo.pdf")], "lang": "vie"},
        content_type="multipart/form-data",
    )
    md = r.get_json()["results"][0]["markdown"]
    assert "# Báo cáo Kỹ thuật Quý IV" in md
    assert "| Máy chủ | 12 triệu | Đã thanh toán |" in md


@needs_tesseract
def test_convert_pdf_scan_qua_web(client, fixtures):
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["scan"].open("rb"), "scan.pdf")], "lang": "vie"},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert res["ok"]
    assert "qua OCR" in res["detail"]
    assert "Báo cáo Kỹ thuật" in res["markdown"]


def test_file_hong_bao_loi_khong_lo_duong_dan_tam(client):
    """Thông báo lỗi không được nhắc tới thư mục tạm trong AppData — người dùng
    chưa từng đặt file ở đó và nó bị xoá ngay sau đó, nêu ra chỉ gây rối."""
    r = client.post(
        "/api/convert",
        data={"files": [(io.BytesIO(b"%PDF-1.4 khong phai pdf that"), "hong.pdf")]},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert not res["ok"]
    assert "hong.pdf" in res["error"]
    assert "AppData" not in res["error"]
    assert "Temp" not in res["error"]


def test_dinh_dang_khong_ho_tro(client):
    r = client.post(
        "/api/convert",
        data={"files": [(io.BytesIO(b"abc"), "ghi-chu.txt")]},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert not res["ok"]
    assert "không hỗ trợ" in res["error"]


def test_mot_file_hong_khong_lam_hong_ca_lo(client, fixtures):
    r = client.post(
        "/api/convert",
        data={
            "files": [
                (fixtures["docx"].open("rb"), "tot.docx"),
                (io.BytesIO(b"rac"), "hong.pdf"),
                (fixtures["pdf"].open("rb"), "tot2.pdf"),
            ]
        },
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"]
    assert len(res) == 3
    assert sum(1 for x in res if x["ok"]) == 2


def test_ten_file_khong_thoat_ra_ngoai_thu_muc_tam(client, fixtures):
    r"""Tên file là dữ liệu người dùng gửi lên. '..\..\evil.docx' phải bị cắt về
    'evil.docx', không được ghi ra ngoài thư mục tạm."""
    r = client.post(
        "/api/convert",
        data={"files": [(fixtures["docx"].open("rb"), "../../evil.docx")]},
        content_type="multipart/form-data",
    )
    res = r.get_json()["results"][0]
    assert res["ok"]
    assert res["out"] == "evil.md"
    assert ".." not in res["out"]


def test_zip(client, fixtures):
    r = client.post("/api/zip", json=[
        {"name": "Báo cáo.md", "markdown": "# Xin chào"},
        {"name": "Hợp đồng.md", "markdown": "# Điều khoản"},
    ])
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert set(z.namelist()) == {"Báo cáo.md", "Hợp đồng.md"}
    assert z.read("Báo cáo.md").decode() == "# Xin chào"
