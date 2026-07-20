"""Sửa lỗi chính tả tiếng Việt sau OCR — an toàn cho tên riêng và mã số.

OCR hay đọc sai DẤU của tiếng Việt: "cấp" ra "câp", "tầng" ra "tang". Từ điển
hunspell vi_VN (chính là bộ vi_VN.dic/.aff mà OCR-Offline dùng) gợi ý được từ
đúng, nhưng nếu cứ lấy gợi ý đầu tiên như OCR-Offline thì rất dễ SỬA NHẦM tên
riêng và mã số — tài liệu hành chính đầy "Ngô Đại Dương", "HTH0351-11", "An
Thanh Sơn" sẽ bị bóp méo.

Nên ở đây chặt hơn một bậc: CHỈ nhận gợi ý nào bỏ-dấu-ra-giống-hệt từ gốc.
Tức là chỉ sửa sai về dấu, tuyệt đối không đổi sang một từ khác chữ. Nhờ vậy:
  - "câp"  -> "cấp"   (bỏ dấu cả hai đều là "cap")     -> SỬA
  - "thiê" -> giữ nguyên (gợi ý "thuê"/"thi" khác chữ) -> KHÔNG đụng
  - tên riêng lạ không có trong từ điển -> gợi ý khác xa -> KHÔNG đụng

Từ nào còn sai kiểu mất chữ/thừa chữ thì để người dùng tự sửa tay — giao diện
đã cho sửa trực tiếp.

spylls là hunspell viết thuần Python, cài bằng pip, chạy offline. Nếu chưa cài
thì mọi hàm ở đây lặng lẽ trả về nguyên văn (available() = False) để tính năng
còn lại không vỡ.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .runtime import resource_dir

# Trỏ tới cặp vi_VN.aff/vi_VN.dic (truyền tiền tố, không kèm đuôi). Ưu tiên bản
# đi kèm khi đóng gói, rồi bản nằm cạnh OCR-Offline.
VN_DICT_CANDIDATES = [
    resource_dir() / "vi_VN",
    Path(r"C:\Working\OCR\OCR-Offline\vi_VN"),
    Path(r"C:\Works\OCR2\OCR-Offline\vi_VN"),
    Path(__file__).parent.parent / "assets" / "vi_VN",
]

# Chỉ nhặt các cụm THUẦN chữ cái (Latin + tiếng Việt). Token có số hay dấu gạch
# (mã trạm HTH0351-11) không khớp nên không bao giờ bị chạm tới.
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(s: str) -> str:
    """Bỏ toàn bộ dấu tiếng Việt, đưa về chữ thường ASCII để so khớp 'cùng chữ'."""
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


@lru_cache(maxsize=1)
def _dictionary():
    try:
        from spylls.hunspell import Dictionary
    except ImportError:
        return None
    for prefix in VN_DICT_CANDIDATES:
        if prefix.with_suffix(".dic").exists() and prefix.with_suffix(".aff").exists():
            try:
                return Dictionary.from_files(str(prefix))
            except Exception:  # noqa: BLE001
                continue
    return None


def available() -> bool:
    """True nếu có đủ spylls và file từ điển để sửa chính tả."""
    return _dictionary() is not None


def _match_case(src: str, repl: str) -> str:
    """Chép lại kiểu hoa/thường của từ gốc sang từ thay thế."""
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


@lru_cache(maxsize=20000)
def _fix_word(word: str) -> str:
    d = _dictionary()
    if d is None or len(word) < 2 or word.isupper():
        return word
    if d.lookup(word):
        return word
    target = _fold(word)
    for sug in d.suggest(word):
        if " " in sug or "-" in sug:
            continue
        if _fold(sug) == target:
            return _match_case(word, sug)
    return word


def fix_text(text: str) -> str:
    """Sửa dấu cho mọi từ tiếng Việt trong văn bản. Không đụng số, mã, dấu câu.

    An toàn khi gọi lúc chưa cài spylls: khi đó trả về nguyên văn.
    """
    if not text or _dictionary() is None:
        return text
    return WORD_RE.sub(lambda m: _fix_word(m.group()), text)
