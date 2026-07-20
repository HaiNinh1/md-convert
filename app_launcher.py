"""Điểm khởi động cho bản đóng gói .exe.

Chỉ gọi lại web.main(): mở máy chủ ở 127.0.0.1 rồi bật trình duyệt. Tách riêng
file này để PyInstaller có một kịch bản đầu vào rõ ràng, không phải trỏ vào
"-m mdconvert.web".
"""

from __future__ import annotations

import sys


def main() -> int:
    from mdconvert.web import main as web_main

    try:
        return web_main(["--port", "5000"])
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        # Bản đóng gói có cửa sổ console — in lỗi ra rồi chờ để người dùng đọc
        # được, thay vì cửa sổ chớp tắt biến mất.
        print("\n  [LỖI] Không khởi động được ứng dụng:")
        print(f"  {type(e).__name__}: {e}\n")
        try:
            input("  Nhấn Enter để đóng...")
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
