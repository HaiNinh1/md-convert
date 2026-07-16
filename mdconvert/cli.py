"""Giao diện dòng lệnh cho md-convert."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from .console import force_utf8
from .ocr import TesseractMissing
from .office import LegacyDocError
from .router import SUPPORTED, UnsupportedFile, convert_file


def _iter_inputs(paths: list[Path], recursive: bool) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            out.extend(
                f for f in sorted(it) if f.is_file() and f.suffix.lower() in SUPPORTED
            )
        elif p.is_file():
            out.append(p)
        else:
            print(f"  bỏ qua (không tồn tại): {p}", file=sys.stderr)
    return out


def plan_outputs(inputs: list[Path], out_dir: Path) -> dict[Path, Path]:
    """Chọn tên file .md cho cả lô, tránh hai nguồn khác nhau đè lên nhau.

    'hopdong.pdf' và 'hopdong.docx' cùng ra 'hopdong.md' thì file sau xoá mất
    file trước mà không báo gì. Chỉ khi trùng mới thêm đuôi để phân biệt, để
    trường hợp thường gặp vẫn giữ được tên sạch.
    """
    counts = Counter(p.stem.lower() for p in inputs)
    mapping: dict[Path, Path] = {}
    for p in inputs:
        if counts[p.stem.lower()] > 1:
            mapping[p] = out_dir / f"{p.stem}-{p.suffix.lstrip('.').lower()}.md"
        else:
            mapping[p] = out_dir / f"{p.stem}.md"
    return mapping


def convert_one(src: Path, out_dir: Path, args, dest: Path | None = None) -> str | None:
    """Chuyển một file. Trả về None nếu thành công, hoặc lý do hỏng nếu thất bại."""
    started = time.time()
    dest = dest or out_dir / f"{src.stem}.md"
    print(f"→ {src.name}")

    def on_page(n: int, total: int, scanned: bool) -> None:
        if args.verbose:
            tag = "OCR" if scanned else "text"
            print(f"    trang {n}/{total} [{tag}]")

    try:
        kw: dict = {"extract_images": not args.no_images}
        if src.suffix.lower() == ".pdf":
            kw.update(
                ocr_lang=args.lang,
                dpi=args.dpi,
                force_ocr=args.force_ocr,
                keep_headers=args.keep_headers,
                on_page=on_page,
            )
        md, stats = convert_file(src, out_dir, **kw)
    except LegacyDocError as e:
        print(f"  ✗ {e}")
        return "định dạng .doc đời cũ, cần chuyển sang .docx trước"
    except UnsupportedFile as e:
        print(f"  ✗ {e}")
        return "định dạng không hỗ trợ"
    except TesseractMissing as e:
        print(f"  ✗ Là bản scan nên cần OCR, nhưng: {e}")
        return "là PDF scan nhưng chưa cài Tesseract"
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ Lỗi: {type(e).__name__}: {e}")
        return f"{type(e).__name__}: {e}"

    if not md.strip():
        print("  ✗ Không trích được nội dung nào")
        return "file rỗng hoặc không đọc được nội dung"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(md, encoding="utf-8")

    took = time.time() - started
    if stats.get("source") == "docx":
        detail = "Word"
        if stats.get("converted_from") == ".doc":
            detail += f" (.doc, chuyển qua {stats.get('converted_by', '?')})"
        if stats.get("promoted_headings"):
            detail += f", bù {stats['promoted_headings']} tiêu đề"
    elif stats.get("source") == "xlsx":
        detail = f"Excel, {stats.get('sheets', 0)} sheet"
    else:
        bits = [f"{stats.get('pages', 0)} trang"]
        if stats.get("ocr_pages"):
            bits.append(f"{stats['ocr_pages']} qua OCR")
        if stats.get("tables"):
            bits.append(f"{stats['tables']} bảng")
        if stats.get("images"):
            bits.append(f"{stats['images']} ảnh")
        if stats.get("columns") == "multi":
            bits.append("2 cột")
        detail = ", ".join(bits)

    print(f"  ✓ {dest.name}  ({detail}, {took:.1f}s)")
    return None


def cmd_convert(args) -> int:
    inputs = _iter_inputs([Path(p) for p in args.inputs], args.recursive)
    if not inputs:
        print("Không tìm thấy file nào để chuyển.", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    plan = plan_outputs(inputs, out_dir)
    print(f"Tìm thấy {len(inputs)} file. Bắt đầu chuyển đổi...\n")

    failures: list[tuple[Path, str]] = []
    for src in inputs:
        reason = convert_one(src, out_dir, args, plan[src])
        if reason:
            failures.append((src, reason))

    ok = len(inputs) - len(failures)
    print("\n" + "=" * 62)
    print(f"  Thành công : {ok}/{len(inputs)} file")
    print(f"  Thất bại   : {len(failures)}/{len(inputs)} file")
    print(f"  Kết quả    : {out_dir.resolve()}")
    print("=" * 62)

    # Liệt kê rõ file nào hỏng và vì sao. Chỉ báo "8/10" thì người dùng phải tự
    # cuộn ngược lên tìm giữa hàng trăm dòng log của một thư mục lớn.
    if failures:
        print("\nCÁC FILE KHÔNG CHUYỂN ĐƯỢC:\n")
        for src, reason in failures:
            print(f"  ✗ {src.name}")
            print(f"      lý do: {reason}")
            print(f"      nằm ở: {src.parent}")
        print()
    return 1 if failures and ok == 0 else 0


def cmd_watch(args) -> int:
    from .watch import watch_folder

    return watch_folder(Path(args.folder), Path(args.out), args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="md-convert",
        description="Chuyển PDF / PDF scan / Word / Excel sang Markdown. Offline, không dùng API trả phí.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--out", default="out", help="thư mục xuất (mặc định: out)")
    common.add_argument("--lang", default="vi", help="ngôn ngữ OCR (mặc định: vi)")
    common.add_argument("--dpi", type=int, default=300, help="độ phân giải khi OCR (mặc định: 300)")
    common.add_argument("--force-ocr", action="store_true", help="ép OCR kể cả khi PDF có sẵn text")
    common.add_argument("--no-images", action="store_true", help="không tách ảnh ra thư mục assets")
    common.add_argument("--keep-headers", action="store_true", help="giữ lại header/footer lặp lại")
    common.add_argument("-v", "--verbose", action="store_true", help="in tiến độ từng trang")

    c = sub.add_parser("convert", parents=[common], help="chuyển file hoặc cả thư mục")
    c.add_argument("inputs", nargs="+", help="file hoặc thư mục đầu vào")
    c.add_argument("-r", "--recursive", action="store_true", help="quét cả thư mục con")
    c.set_defaults(func=cmd_convert)

    w = sub.add_parser("watch", parents=[common], help="theo dõi thư mục, thả file vào là tự chuyển")
    w.add_argument("folder", help="thư mục cần theo dõi")
    w.set_defaults(func=cmd_watch)

    return p


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
