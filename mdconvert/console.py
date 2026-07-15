"""Tiện ích console dùng chung cho mọi điểm khởi động.

Tách riêng ra vì đã có bài học: bản vá UTF-8 ban đầu nằm lọt trong cli.py, nên
khi thêm web.py — một điểm khởi động mới — nó không được áp dụng và máy chủ chết
ngay dòng print đầu tiên. Để ở đây thì mọi điểm khởi động dùng chung một bản.
"""

from __future__ import annotations

import sys


def force_utf8() -> None:
    """Ép luồng ra dùng UTF-8.

    Console Windows mặc định là cp1252, không in nổi tiếng Việt lẫn ký hiệu như
    → hay ✓. Không ép thì chỉ cần một chữ có dấu là chương trình chết vì
    UnicodeEncodeError, dù công việc thật đã chạy xong xuôi.

    Phải gọi ở ĐẦU mọi hàm main() — cli, web, gui.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # pythonw không có stdout thật; không có gì để ép thì thôi.
            pass
