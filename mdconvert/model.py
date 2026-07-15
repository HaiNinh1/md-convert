"""Mô hình dữ liệu chung cho mọi nguồn đầu vào.

Điểm mấu chốt của cả dự án: PDF có text layer và PDF scan (qua OCR) đều được
quy về cùng một cấu trúc Span/Line. Nhờ vậy tầng phân tích layout chỉ cần viết
và bảo trì một lần duy nhất, không phải tách đôi theo loại đầu vào.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MONO_HINTS = ("mono", "courier", "consol", "menlo", "hack", "inconsolata")
BOLD_HINTS = ("bold", "black", "heavy", "semib", "demib")
ITALIC_HINTS = ("italic", "oblique")


@dataclass
class Span:
    """Một mẩu chữ liền mạch cùng kiểu định dạng, kèm toạ độ trên trang."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    font: str = ""
    bold: bool = False
    italic: bool = False
    mono: bool = False

    @property
    def style_key(self) -> tuple[bool, bool, bool]:
        return (self.bold, self.italic, self.mono)

    @classmethod
    def from_font_name(cls, font: str, **kw) -> "Span":
        """Suy ra kiểu chữ từ tên font khi nguồn không cung cấp cờ định dạng."""
        low = font.lower()
        kw.setdefault("bold", any(h in low for h in BOLD_HINTS))
        kw.setdefault("italic", any(h in low for h in ITALIC_HINTS))
        kw.setdefault("mono", any(h in low for h in MONO_HINTS))
        return cls(font=font, **kw)


@dataclass
class Line:
    """Một dòng chữ: nhiều span nằm cùng một cao độ y."""

    spans: list[Span] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def x0(self) -> float:
        return min(s.x0 for s in self.spans)

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.spans)

    @property
    def y0(self) -> float:
        return min(s.y0 for s in self.spans)

    @property
    def y1(self) -> float:
        return max(s.y1 for s in self.spans)

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def size(self) -> float:
        """Cỡ chữ đại diện: cỡ chiếm nhiều ký tự nhất trong dòng.

        Tính theo số ký tự chứ không theo số span, để một span ngắn cỡ lạ
        (ví dụ số chú thích) không kéo lệch cỡ của cả dòng.
        """
        if not self.spans:
            return 0.0
        weight: dict[float, int] = {}
        for s in self.spans:
            n = len(s.text.strip())
            if n:
                weight[round(s.size, 1)] = weight.get(round(s.size, 1), 0) + n
        if not weight:
            return round(self.spans[0].size, 1)
        return max(weight.items(), key=lambda kv: kv[1])[0]

    @property
    def all_bold(self) -> bool:
        real = [s for s in self.spans if s.text.strip()]
        return bool(real) and all(s.bold for s in real)

    @property
    def all_mono(self) -> bool:
        real = [s for s in self.spans if s.text.strip()]
        return bool(real) and all(s.mono for s in real)


@dataclass
class Block:
    """Một khối nội dung đã được nhận dạng, sẵn sàng đổ ra markdown."""

    kind: str  # heading | para | list | table | code | image | rule | pagebreak
    level: int = 0  # heading: 1..6
    spans: list[Span] = field(default_factory=list)  # heading | para
    items: list["ListItem"] = field(default_factory=list)  # list
    rows: list[list[str]] = field(default_factory=list)  # table
    text: str = ""  # code | image (đường dẫn)


@dataclass
class ListItem:
    level: int
    ordered: bool
    spans: list[Span] = field(default_factory=list)
    marker: str = ""


@dataclass
class TableMarker:
    """Chỗ đặt của một bảng trong luồng đọc, để bảng nằm đúng vị trí giữa các đoạn."""

    y0: float
    x0: float
    rows: list[list[str]]


@dataclass
class ImageMarker:
    y0: float
    x0: float
    path: str
