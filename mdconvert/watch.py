"""Chế độ tự động: theo dõi thư mục, thả file vào là tự chuyển sang markdown."""

from __future__ import annotations

import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .router import SUPPORTED

# Khi copy file vào thư mục, hệ điều hành báo "đã tạo file" ngay từ byte đầu tiên,
# trong khi file còn đang chép dở. Đọc lúc đó sẽ ra PDF hỏng. Vì vậy phải đợi
# kích thước file ngừng thay đổi rồi mới xử lý.
SETTLE_CHECKS = 3
SETTLE_INTERVAL = 0.5
SETTLE_TIMEOUT = 60.0


def wait_until_stable(path: Path) -> bool:
    last = -1
    stable = 0
    deadline = time.time() + SETTLE_TIMEOUT
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last and size > 0:
            stable += 1
            if stable >= SETTLE_CHECKS:
                return True
        else:
            stable = 0
            last = size
        time.sleep(SETTLE_INTERVAL)
    return False


class Handler(FileSystemEventHandler):
    def __init__(self, out_dir: Path, args):
        self.out_dir = out_dir
        self.args = args
        self.seen: dict[str, float] = {}

    def _handle(self, raw_path: str) -> None:
        src = Path(raw_path)
        if src.suffix.lower() not in SUPPORTED:
            return
        # Bỏ qua chính các file mình vừa ghi ra, tránh vòng lặp vô hạn.
        try:
            if self.out_dir.resolve() in src.resolve().parents:
                return
        except OSError:
            return

        now = time.time()
        if now - self.seen.get(str(src), 0) < 2.0:
            return  # watchdog hay bắn trùng event cho cùng một thao tác
        self.seen[str(src)] = now

        if not wait_until_stable(src):
            print(f"  ✗ {src.name}: file chưa chép xong sau {SETTLE_TIMEOUT:.0f}s, bỏ qua")
            return

        from .cli import convert_one

        convert_one(src, self.out_dir, self.args)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def watch_folder(folder: Path, out_dir: Path, args) -> int:
    if not folder.is_dir():
        print(f"Không phải thư mục: {folder}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(Handler(out_dir, args), str(folder), recursive=False)
    observer.start()
    print(f"Đang theo dõi {folder}")
    print(f"Kết quả ra    {out_dir}")
    print("Thả file PDF/Word/Excel vào là tự chuyển. Ctrl+C để dừng.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        observer.stop()
        observer.join()
    return 0
