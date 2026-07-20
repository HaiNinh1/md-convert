# -*- mode: python ; coding: utf-8 -*-
"""Cấu hình đóng gói md-convert thành .exe tự chạy (PyInstaller, one-folder).

Gói kèm: mã nguồn (biên dịch .pyc, ẩn), Flask/PyMuPDF/Pillow/spylls, Tesseract
(tesseract.exe + DLL) + vie.traineddata cho OCR offline, từ điển tiếng Việt, và
khoá OCR online nếu có sẵn.

Dựng bằng:  pyinstaller md-convert.spec --noconfirm
Kết quả  :  dist/md-convert/md-convert.exe
"""

import glob
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT = Path(SPECPATH)


def _first_existing(paths, what):
    for p in paths:
        if Path(p).exists():
            return Path(p)
    raise SystemExit(f"[md-convert.spec] Không tìm thấy {what}. Đã thử: {paths}")


# --- Tesseract để gói kèm (chạy offline khi mất mạng) ---
TESS = _first_existing(
    [r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"],
    "thư mục Tesseract-OCR",
).joinpath("tesseract.exe").parent

# --- tessdata có vie.traineddata ---
VIE_DIR = _first_existing(
    [
        r"C:\Working\OCR\OCR-Offline\tessdata\vie.traineddata",
        str(TESS / "tessdata" / "vie.traineddata"),
    ],
    "vie.traineddata",
).parent

# --- Từ điển tiếng Việt (sửa chính tả offline) ---
VN_DIC = _first_existing(
    [r"C:\Working\OCR\OCR-Offline\vi_VN.dic"], "vi_VN.dic"
).parent

datas = []

# CHÚ Ý: KHÔNG đưa tesseract.exe/DLL vào datas ở đây. PyInstaller sẽ phân tích
# chúng và kéo các DLL khổng lồ (libtesseract 97MB, libicu 30MB...) ra gốc
# _internal, TRÙNG với bản trong tesseract/ -> phình ~150MB vô ích. Thay vào đó
# Dong-goi-app.bat chép nguyên Tesseract vào _internal/tesseract/ SAU khi build.

# chỉ kèm vie.traineddata cho nhẹ (bản online mới là bản chính xác cao)
datas.append((str(VIE_DIR / "vie.traineddata"), "tessdata"))

# từ điển tiếng Việt
datas.append((str(VN_DIC / "vi_VN.dic"), "."))
datas.append((str(VN_DIC / "vi_VN.aff"), "."))

# khoá OCR online, nếu chủ máy đã đặt sẵn -> đi kèm trong bản đóng gói
_key = PROJECT / "ocrspace_key.txt"
if _key.exists():
    datas.append((str(_key), "."))

# gom trọn spylls (có dữ liệu nội bộ) để chắc chắn chạy sau khi đóng gói
_sp_datas, _sp_bins, _sp_hidden = collect_all("spylls")
datas += _sp_datas

hiddenimports = list(_sp_hidden) + [
    "mdconvert.web",
    "mdconvert.snip",
    "mdconvert.online_ocr",
    "mdconvert.spellfix",
]

_ICON = PROJECT / "assets" / "md-convert.ico"

a = Analysis(
    ["app_launcher.py"],
    pathex=[str(PROJECT)],
    binaries=list(_sp_bins),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.testing", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="md-convert",
    console=True,
    icon=str(_ICON) if _ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="md-convert",
)
