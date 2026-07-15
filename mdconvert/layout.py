"""Tầng phân tích layout: từ toạ độ và cỡ chữ suy ra cấu trúc tài liệu.

Toàn bộ file này là luật và thống kê, không có mô hình AI nào. Nguyên tắc chung:
cỡ chữ thân bài là cỡ phổ biến nhất, mọi thứ to hơn đáng kể là tiêu đề, và các
quan hệ còn lại (đoạn, danh sách, cột) suy ra từ khoảng cách hình học.
"""

from __future__ import annotations

import re
import statistics

from .model import Block, ImageMarker, Line, ListItem, Span, TableMarker

# Ký tự gạch đầu dòng phải liệt kê rộng tay. Lý do: font nhúng trong PDF hay map
# glyph sai — gõ dấu trừ ASCII thường trong Word với font Times New Roman, PyMuPDF
# trích ra lại thành U+00AD SOFT HYPHEN. Thiếu một mã là cả danh sách bị đọc
# thành đoạn văn dính liền.
BULLET_CHARS = (
    "•▪◦‣∙·▸►◆■□o*+"
    "-"  # hyphen-minus
    "­"  # soft hyphen — Times New Roman trong PDF hay ra mã này
    "‐‑‒–—―"  # các loại gạch ngang
    "−"  # dấu trừ toán học
)
BULLET_RE = re.compile(rf"^\s*([{re.escape(BULLET_CHARS)}])\s+(.*)$", re.DOTALL)
ORDERED_RE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.*)$", re.DOTALL)
ALPHA_RE = re.compile(r"^\s*([a-zA-Z])[.)]\s+(.*)$", re.DOTALL)
SENTENCE_END = re.compile(r"[.!?:;]\s*$")

# Tiêu đề phải to hơn thân bài ít nhất 8% mới tính, để nhiễu cỡ chữ trong PDF
# (thường lệch 0.1–0.3pt giữa các span cùng cấp) không bị hiểu nhầm thành cấp mới.
HEADING_RATIO = 1.08
# Hai cỡ chữ lệch nhau dưới ngưỡng này coi như cùng một cấp tiêu đề.
SIZE_TOLERANCE = 0.6
# Chốt chặn cho trường hợp nhận nhầm cỡ thân bài: nếu một cỡ chữ chiếm quá nhiều
# ký tự của tài liệu thì đó là thân bài in to chứ không phải tiêu đề.
#
# Đừng siết con số này. Từng để 0.12 và tài liệu 1 trang bị hỏng: tiêu đề 15pt
# chiếm 12.3% số ký tự — hoàn toàn bình thường với văn bản ngắn — nên bị loại
# khỏi danh sách tiêu đề rồi rơi xuống thành danh sách đánh số. Tài liệu càng
# ngắn thì tiêu đề càng chiếm tỉ lệ cao, nên ngưỡng phải rộng. 0.35 vẫn đủ chặn
# ca thật sự hỏng (thân bài nhận nhầm thường chiếm 60-70%).
HEADING_MAX_SHARE = 0.35
MAX_HEADING_LEN = 120


def detect_body_size(lines: list[Line]) -> float:
    """Cỡ chữ thân bài = cỡ chiếm nhiều ký tự nhất toàn tài liệu."""
    weight: dict[float, int] = {}
    for ln in lines:
        for s in ln.spans:
            n = len(s.text.strip())
            if n:
                key = round(s.size * 2) / 2  # gom về bội số 0.5pt
                weight[key] = weight.get(key, 0) + n
    if not weight:
        return 10.0
    return max(weight.items(), key=lambda kv: kv[1])[0]


HEADING_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S")


def refine_heading_levels(blocks: list[Block]) -> list[Block]:
    """Chỉnh lại cấp tiêu đề theo cách đánh số, khi tài liệu có đánh số.

    Cỡ chữ là tín hiệu nhiễu — nhất là với OCR, nơi hai tiêu đề cùng 15pt có thể
    bị đo lệch nhau 10% và rơi vào hai cấp khác nhau. Còn cách đánh số thì tuyệt
    đối chính xác: "2.1" chắc chắn sâu hơn "2" đúng một cấp, không cần đo đạc gì.

    Chỉ áp cho các dòng ĐÃ được nhận là tiêu đề, nếu không mọi mục danh sách
    "1. abc" cũng sẽ bị biến thành tiêu đề.
    """
    headings = [b for b in blocks if b.kind == "heading"]
    if not headings:
        return blocks

    numbered = []
    for b in headings:
        m = HEADING_NUM_RE.match("".join(s.text for s in b.spans).strip())
        if m:
            numbered.append((b, m.group(1).count(".") + 1))
    if not numbered:
        return blocks

    # Theo quy ước thường gặp, tiêu đề tài liệu là H1 còn "1." là H2. Chỉ cộng
    # thêm cấp khi thật sự có một tiêu đề không đánh số nằm ở cấp 1 (tên tài liệu).
    has_title = any(
        b.level == 1 and not HEADING_NUM_RE.match("".join(s.text for s in b.spans).strip())
        for b in headings
    )
    offset = 1 if has_title else 0

    for b, depth in numbered:
        b.level = max(1, min(6, depth + offset))
    return blocks


def build_heading_map(
    lines: list[Line], body_size: float, rel_tolerance: float = 0.0
) -> dict[float, int]:
    """Xếp các cỡ chữ lớn hơn thân bài thành cấp tiêu đề h1..h6.

    rel_tolerance nới dung sai gom cụm theo tỉ lệ cỡ chữ. PDF số có cỡ chữ chính
    xác tuyệt đối nên để 0; ước lượng từ OCR lệch cỡ 8-10% nên cần nới, không thì
    hai tiêu đề cùng cấp bị tách thành hai cấp khác nhau.
    """
    weight: dict[float, int] = {}
    total = 0
    for ln in lines:
        for s in ln.spans:
            n = len(s.text.strip())
            if n:
                key = round(s.size * 2) / 2
                weight[key] = weight.get(key, 0) + n
                total += n
    if not total:
        return {}

    candidates = [
        size
        for size, n in weight.items()
        if size >= body_size * HEADING_RATIO and n / total <= HEADING_MAX_SHARE
    ]
    if not candidates:
        return {}

    # Gom các cỡ sát nhau thành một cụm để 16.0pt và 16.2pt không thành hai cấp.
    clusters: list[list[float]] = []
    for size in sorted(candidates, reverse=True):
        if clusters:
            prev = clusters[-1][-1]
            tol = max(SIZE_TOLERANCE, prev * rel_tolerance)
            if abs(prev - size) <= tol:
                clusters[-1].append(size)
                continue
        clusters.append([size])

    mapping: dict[float, int] = {}
    for level, cluster in enumerate(clusters[:6], start=1):
        for size in cluster:
            mapping[size] = level
    return mapping


def _looks_like_heading(ln: Line, body_size: float) -> bool:
    """Dòng in đậm đứng riêng, ngắn, không kết câu — tiêu đề không tăng cỡ chữ.

    Nhiều tài liệu Việt Nam đánh tiêu đề chỉ bằng in đậm, giữ nguyên cỡ chữ,
    nên chỉ dựa vào cỡ sẽ bỏ sót hoàn toàn.
    """
    txt = ln.text.strip()
    if not txt or len(txt) > MAX_HEADING_LEN:
        return False
    if not ln.all_bold:
        return False
    if SENTENCE_END.search(txt) and not txt.endswith(":"):
        return False
    if ln.size < body_size * 0.95:
        return False
    return True


def split_columns(lines: list[Line], page_width: float) -> list[list[Line]]:
    """Tách trang 2 cột. Trả về các nhóm dòng theo đúng thứ tự đọc.

    Nếu không thấy dải trắng dọc rõ ràng ở giữa trang thì coi như 1 cột.
    """
    if len(lines) < 10 or page_width <= 0:
        return [lines]

    bin_w = 4.0
    nbins = max(1, int(page_width / bin_w) + 1)
    covered = [False] * nbins
    for ln in lines:
        a = max(0, int(ln.x0 / bin_w))
        b = min(nbins - 1, int(ln.x1 / bin_w))
        for i in range(a, b + 1):
            covered[i] = True

    # Chỉ xét dải trắng nằm trong khoảng giữa trang (30%–70%).
    lo, hi = int(nbins * 0.30), int(nbins * 0.70)
    best_run: tuple[int, int] | None = None
    run_start: int | None = None
    for i in range(lo, hi + 1):
        if not covered[i]:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                if best_run is None or (i - run_start) > (best_run[1] - best_run[0]):
                    best_run = (run_start, i)
                run_start = None
    if run_start is not None and (
        best_run is None or (hi + 1 - run_start) > (best_run[1] - best_run[0])
    ):
        best_run = (run_start, hi + 1)

    if best_run is None:
        return [lines]
    gap_w = (best_run[1] - best_run[0]) * bin_w
    if gap_w < page_width * 0.05:
        return [lines]

    split_x = (best_run[0] + best_run[1]) / 2 * bin_w
    left = [ln for ln in lines if ln.x1 <= split_x]
    right = [ln for ln in lines if ln.x0 >= split_x]
    # Dòng nào bắc ngang dải trắng (tiêu đề chạy suốt trang) thì không phải 2 cột.
    if len(left) + len(right) < len(lines) * 0.9:
        return [lines]
    if min(len(left), len(right)) < len(lines) * 0.25:
        return [lines]
    return [left, right]


def _match_list(text: str) -> tuple[bool, str, str] | None:
    """Trả về (có_thứ_tự, ký_hiệu, phần_còn_lại) nếu dòng mở đầu bằng dấu liệt kê."""
    m = ORDERED_RE.match(text)
    if m:
        return (True, m.group(1), m.group(2))
    m = BULLET_RE.match(text)
    if m:
        return (False, m.group(1), m.group(2))
    m = ALPHA_RE.match(text)
    if m:
        return (True, m.group(1), m.group(2))
    return None


def _indent_levels(xs: list[float], tol: float = 12.0) -> dict[float, int]:
    """Gom các mốc thụt lề thành cấp lồng nhau 0,1,2..."""
    levels: dict[float, int] = {}
    if not xs:
        return levels
    anchors: list[float] = []
    for x in sorted(set(xs)):
        if not anchors or x - anchors[-1] > tol:
            anchors.append(x)
    for x in xs:
        best = min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))
        levels[x] = best
    return levels


def _strip_marker(spans: list[Span], marker: str) -> list[Span]:
    """Bỏ ký hiệu liệt kê khỏi đầu dòng, giữ nguyên định dạng phần còn lại."""
    out: list[Span] = []
    removed = False
    for s in spans:
        if removed:
            out.append(s)
            continue
        stripped = s.text.lstrip()
        prefix = marker
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :]
            rest = re.sub(r"^[.)]?\s*", "", rest, count=1)
            removed = True
            if rest:
                out.append(Span(**{**s.__dict__, "text": rest}))
        else:
            out.append(s)
            if s.text.strip():
                removed = True  # marker không nằm ở span đầu, thôi bỏ qua
    return out or spans


def _gap_thresholds(lines: list[Line], body_size: float) -> tuple[float, float]:
    """Tìm ngưỡng khoảng cách dọc để phân biệt "xuống dòng" và "xuống đoạn".

    Chỉ đo giữa các dòng CÙNG cỡ thân bài và nằm liền nhau. Nếu gộp cả khoảng
    cách trước tiêu đề hay giữa các ô bảng vào, trung vị bị kéo lên và ngưỡng
    tách đoạn cao đến mức không đoạn nào tách được nữa.

    Lấy mode chứ không lấy trung vị: giãn dòng bên trong một đoạn là con số lặp
    lại nhiều nhất trong tài liệu, còn trung vị vẫn bị kéo lệch khi tài liệu có
    nhiều đoạn ngắn.
    """
    body_lines = [
        ln for ln in lines if abs(round(ln.size * 2) / 2 - body_size) <= SIZE_TOLERANCE
    ]
    gaps: list[float] = []
    for a, b in zip(body_lines, body_lines[1:]):
        g = b.y0 - a.y1
        if 0 <= g < body_size * 3:
            gaps.append(g)

    if not gaps:
        typical = body_size * 0.25
    else:
        buckets: dict[float, int] = {}
        for g in gaps:
            buckets[round(g * 2) / 2] = buckets.get(round(g * 2) / 2, 0) + 1
        value, count = max(buckets.items(), key=lambda kv: (kv[1], -kv[0]))
        if count >= 3:
            typical = value
        else:
            # Quá ít mẫu để mode có nghĩa: lấy tứ phân vị dưới, vì khoảng cách
            # nhỏ nhất gần như luôn là giãn dòng trong đoạn.
            ordered = sorted(gaps)
            typical = ordered[len(ordered) // 4]

    # Xuống đoạn phải rộng hơn giãn dòng ít nhất nửa cỡ chữ mới tính.
    para_gap = typical + max(body_size * 0.5, 2.0)
    return typical, para_gap


def group_blocks(
    elements: list,
    body_size: float,
    heading_map: dict[float, int],
) -> list[Block]:
    """Ghép các dòng đã sắp xếp thành khối: tiêu đề, đoạn, danh sách, bảng, ảnh."""
    elements = sorted(
        elements,
        key=lambda e: (round(e.y0, 1), e.x0),
    )

    text_lines = [e for e in elements if isinstance(e, Line)]
    typical_gap, para_gap = _gap_thresholds(text_lines, body_size)

    list_xs = [
        e.x0 for e in text_lines if _match_list(e.text.strip()) is not None
    ]
    indent_map = _indent_levels(list_xs)

    blocks: list[Block] = []
    para_spans: list[Span] = []
    pending_list: list[ListItem] = []
    prev: Line | None = None

    def flush_para() -> None:
        nonlocal para_spans
        if para_spans:
            blocks.append(Block(kind="para", spans=para_spans))
            para_spans = []

    def flush_list() -> None:
        nonlocal pending_list
        if pending_list:
            blocks.append(Block(kind="list", items=pending_list))
            pending_list = []

    for el in elements:
        if isinstance(el, TableMarker):
            flush_para()
            flush_list()
            blocks.append(Block(kind="table", rows=el.rows))
            prev = None
            continue
        if isinstance(el, ImageMarker):
            flush_para()
            flush_list()
            blocks.append(Block(kind="image", text=el.path))
            prev = None
            continue

        ln: Line = el
        txt = ln.text.strip()
        if not txt:
            continue

        size_key = round(ln.size * 2) / 2
        level = heading_map.get(size_key)

        # Tiêu đề theo cỡ chữ
        if level and len(txt) <= MAX_HEADING_LEN:
            flush_para()
            flush_list()
            blocks.append(Block(kind="heading", level=level, spans=ln.spans))
            prev = ln
            continue

        # Danh sách
        m = _match_list(txt)
        if m:
            ordered, marker, _rest = m
            flush_para()
            pending_list.append(
                ListItem(
                    level=indent_map.get(ln.x0, 0),
                    ordered=ordered,
                    spans=_strip_marker(ln.spans, marker),
                    marker=marker,
                )
            )
            prev = ln
            continue

        # Dòng nối tiếp của mục danh sách trước đó (thụt lề sâu hơn, không có dấu)
        if pending_list and prev is not None:
            gap = ln.y0 - prev.y1
            if gap <= para_gap and ln.x0 > prev.x0 - 2:
                pending_list[-1].spans.append(
                    Span(
                        text=" " + txt,
                        x0=ln.x0,
                        y0=ln.y0,
                        x1=ln.x1,
                        y1=ln.y1,
                        size=ln.size,
                    )
                )
                prev = ln
                continue
        flush_list()

        # Khối mã: cả dòng dùng font monospace
        if ln.all_mono:
            flush_para()
            if blocks and blocks[-1].kind == "code":
                blocks[-1].text += "\n" + txt
            else:
                blocks.append(Block(kind="code", text=txt))
            prev = ln
            continue

        # Tiêu đề chỉ in đậm, không tăng cỡ chữ
        if _looks_like_heading(ln, body_size):
            gap_before = (ln.y0 - prev.y1) if prev else para_gap + 1
            if gap_before >= typical_gap:
                flush_para()
                blocks.append(Block(kind="heading", level=3, spans=ln.spans))
                prev = ln
                continue

        # Đoạn văn: khoảng cách dọc quyết định xuống đoạn mới hay nối dòng
        if prev is not None and para_spans:
            gap = ln.y0 - prev.y1
            if gap > para_gap:
                flush_para()
            else:
                para_spans.append(
                    Span(text=" ", x0=prev.x1, y0=prev.y0, x1=prev.x1, y1=prev.y1, size=ln.size)
                )
        para_spans.extend(ln.spans)
        prev = ln

    flush_para()
    flush_list()
    return blocks


def tables_from_lines(
    lines: list[Line], min_rows: int = 3
) -> tuple[list[TableMarker], list[Line]]:
    """Dò bảng cho nhánh OCR bằng cách tìm các cột x thẳng hàng qua nhiều dòng.

    Trả về (bảng_tìm_được, các_dòng_còn_lại). Phải trả luôn phần còn lại vì dòng
    nào đã bị bảng nuốt thì không được đổ ra lần nữa dưới dạng đoạn văn, nếu không
    nội dung sẽ xuất hiện hai lần trong file markdown.

    Nhánh PDF số đã có find_tables() của PyMuPDF dựa trên đường kẻ thật, chính xác
    hơn nhiều. Hàm này chỉ dùng cho ảnh scan, nơi không có đường kẻ nào để bám vào,
    nên đặt ngưỡng thận trọng: thà bỏ sót bảng còn hơn biến đoạn văn thành bảng.
    """
    ordered = sorted(lines, key=lambda l: l.y0)
    candidates: list[tuple[Line, list[Span]]] = []
    for ln in ordered:
        cells = [s for s in ln.spans if s.text.strip()]
        if len(cells) >= 2:
            candidates.append((ln, sorted(cells, key=lambda s: s.x0)))

    if len(candidates) < min_rows:
        return [], lines

    runs: list[list[tuple[Line, list[Span]]]] = []
    current: list[tuple[Line, list[Span]]] = []
    for item in candidates:
        if not current:
            current = [item]
            continue
        if abs(len(item[1]) - len(current[-1][1])) <= 1 and _cols_align(
            current[-1][1], item[1]
        ):
            current.append(item)
        else:
            if len(current) >= min_rows:
                runs.append(current)
            current = [item]
    if len(current) >= min_rows:
        runs.append(current)

    out: list[TableMarker] = []
    consumed: set[int] = set()
    for run in runs:
        ncols = max(len(cells) for _ln, cells in run)
        table_rows = []
        for ln, cells in run:
            values = [s.text.strip() for s in cells]
            values += [""] * (ncols - len(values))
            table_rows.append(values)
            consumed.add(id(ln))
        first_cells = run[0][1]
        out.append(
            TableMarker(y0=first_cells[0].y0, x0=first_cells[0].x0, rows=table_rows)
        )

    remaining = [ln for ln in lines if id(ln) not in consumed]
    return out, remaining


def _cols_align(a: list[Span], b: list[Span], tol: float = 14.0) -> bool:
    """Hai dòng có coi là cùng một bảng không: mốc x của các ô phải trùng nhau."""
    hits = 0
    for sa in a:
        if any(abs(sa.x0 - sb.x0) <= tol for sb in b):
            hits += 1
    return hits >= max(2, int(len(a) * 0.6))
