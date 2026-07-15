"""md-convert — chuyển PDF / PDF scan / Word / Excel sang Markdown.

Chạy offline hoàn toàn, không gọi API trả phí nào.
"""

__version__ = "0.1.0"

from .router import UnsupportedFile, convert_file  # noqa: F401
