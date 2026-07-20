"""Định vị tài nguyên đi kèm, chạy cả khi phát triển lẫn khi đã đóng gói (.exe).

PyInstaller giải nén tài nguyên vào một thư mục tạm và gán đường dẫn đó vào
sys._MEIPASS. Khi chạy từ mã nguồn thì không có biến đó, tài nguyên nằm ở gốc
dự án. Gói mọi khác biệt vào đây để các module khác chỉ việc hỏi đường dẫn.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True khi đang chạy từ bản đóng gói PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Thư mục chứa tài nguyên đi kèm (tessdata, từ điển, khoá mặc định)."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    """Thư mục chứa file .exe — nơi chủ máy có thể đặt cấu hình sửa được
    (ví dụ ocrspace_key.txt) mà không cần đóng gói lại."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
