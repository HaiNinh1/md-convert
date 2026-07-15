"""Giao diện dòng lệnh cho md-convert."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

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


def convert_one(src: Path, out_dir: Path, args, dest: Path | None = None) -> bool:
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
        print(f"  ✗ {e}", file=sys.stderr)
        return False
    except UnsupportedFile as e:
        print(f"  ✗ {e}", file=sys.stderr)
        return False
    except TesseractMissing as e:
        print(f"  ✗ {src.name} là bản scan nên cần OCR, nhưng: {e}", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ lỗi khi xử lý {src.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return False

    if not md.strip():
        print(f"  ✗ {src.name}: không trích được nội dung nào", file=sys.stderr)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(md, encoding="utf-8")

    took = time.time() - started
    if stats.get("source") == "docx":
        detail = "Word"
        if stats.get("warnings"):
            detail += f", {stats['warnings']} cảnh báo"
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
    return True


def cmd_convert(args) -> int:
    inputs = _iter_inputs([Path(p) for p in args.inputs], args.recursive)
    if not inputs:
        print("Không tìm thấy file nào để chuyển.", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    plan = plan_outputs(inputs, out_dir)
    ok = sum(convert_one(src, out_dir, args, plan[src]) for src in inputs)
    failed = len(inputs) - ok
    print(f"\nXong: {ok}/{len(inputs)} file → {out_dir}")
    return 1 if failed and ok == 0 else 0


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


def _force_utf8() -> None:
    """Console Windows mặc định là cp1252, không in được tiếng Việt lẫn ký hiệu.

    Không ép UTF-8 thì chỉ cần một tên file có dấu là chương trình chết vì
    UnicodeEncodeError, dù việc chuyển đổi đã chạy xong xuôi.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
