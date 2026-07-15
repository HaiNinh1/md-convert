"""Giao diện đồ hoạ cho md-convert.

Dùng tkinter vì nó nằm sẵn trong Python — không thêm một dependency nào, và app
chạy được ngay trên máy chỉ có Python trần.

Việc chuyển đổi PHẢI chạy ở luồng riêng: một file PDF scan mất vài giây mỗi
trang, làm thẳng trên luồng giao diện thì cửa sổ đứng hình và Windows báo
"Not Responding". Luồng nền đẩy tin nhắn qua queue, luồng giao diện đọc queue
bằng after() — tkinter không an toàn khi gọi từ luồng khác.
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .console import force_utf8
from .ocr import TesseractMissing, find_tesseract
from .office import LegacyDocError
from .router import SUPPORTED, UnsupportedFile, convert_file

APP_NAME = "md-convert"
LANGS = [
    ("Tiếng Việt", "vie"),
    ("Tiếng Việt + Anh", "vie+eng"),
    ("Tiếng Anh", "eng"),
]


class Worker(threading.Thread):
    """Chạy chuyển đổi ở luồng nền, báo tiến độ về qua queue."""

    def __init__(self, jobs: list[tuple[Path, Path]], opts: dict, out_q: queue.Queue):
        super().__init__(daemon=True)
        self.jobs = jobs
        self.opts = opts
        self.q = out_q
        self.cancel = threading.Event()

    def run(self) -> None:
        ok = 0
        for i, (src, dest) in enumerate(self.jobs, start=1):
            if self.cancel.is_set():
                self.q.put(("log", "Đã huỷ."))
                break
            self.q.put(("progress", (i - 1, len(self.jobs))))
            self.q.put(("log", f"→ {src.name}"))
            try:
                md, stats = self._convert(src, dest.parent)
            except LegacyDocError as e:
                self.q.put(("log", f"   ✗ {e}"))
                continue
            except (UnsupportedFile, TesseractMissing) as e:
                self.q.put(("log", f"   ✗ {e}"))
                continue
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", f"   ✗ Lỗi: {type(e).__name__}: {e}"))
                self.q.put(("trace", traceback.format_exc()))
                continue

            if not md.strip():
                self.q.put(("log", "   ✗ Không trích được nội dung nào"))
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(md, encoding="utf-8")
            ok += 1
            self.q.put(("log", f"   ✓ {dest.name}  ({_describe(stats)})"))

        self.q.put(("progress", (len(self.jobs), len(self.jobs))))
        self.q.put(("done", (ok, len(self.jobs))))

    def _convert(self, src: Path, out_dir: Path):
        kw: dict = {"extract_images": self.opts["images"]}
        if src.suffix.lower() == ".pdf":
            kw.update(
                ocr_lang=self.opts["lang"],
                dpi=self.opts["dpi"],
                force_ocr=self.opts["force_ocr"],
                on_page=lambda n, total, scanned: self.q.put(
                    ("log", f"   trang {n}/{total}{' [OCR]' if scanned else ''}")
                ),
            )
        return convert_file(src, out_dir, **kw)


def _describe(stats: dict) -> str:
    if stats.get("source") == "docx":
        return "Word"
    if stats.get("source") == "xlsx":
        return f"Excel, {stats.get('sheets', 0)} sheet"
    bits = [f"{stats.get('pages', 0)} trang"]
    if stats.get("ocr_pages"):
        bits.append(f"{stats['ocr_pages']} qua OCR")
    if stats.get("tables"):
        bits.append(f"{stats['tables']} bảng")
    if stats.get("images"):
        bits.append(f"{stats['images']} ảnh")
    return ", ".join(bits)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, initial: list[Path] | None = None):
        super().__init__(master, padding=12)
        self.master = master
        self.files: list[Path] = []
        self.q: queue.Queue = queue.Queue()
        self.worker: Worker | None = None

        master.title(APP_NAME)
        master.geometry("760x580")
        master.minsize(640, 480)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        self._build()
        if initial:
            self._add_paths(initial)
        self.after(80, self._drain)

    # ---------------------------------------------------------------- giao diện
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(5, weight=1)

        ttk.Label(
            self,
            text="Chuyển PDF, Word, Excel sang Markdown",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # --- Danh sách file ---
        box = ttk.LabelFrame(self, text=" Tài liệu cần chuyển ", padding=8)
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(box, selectmode=tk.EXTENDED, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=sb.set)

        btns = ttk.Frame(box)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Thêm file...", command=self._pick_files).pack(side="left")
        ttk.Button(btns, text="Thêm thư mục...", command=self._pick_folder).pack(
            side="left", padx=6
        )
        ttk.Button(btns, text="Bỏ mục đã chọn", command=self._remove).pack(side="left")
        ttk.Button(btns, text="Xoá hết", command=self._clear).pack(side="left", padx=6)

        # --- Nơi lưu ---
        out = ttk.LabelFrame(self, text=" Lưu kết quả vào ", padding=8)
        out.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        out.columnconfigure(0, weight=1)
        self.out_var = tk.StringVar(value=str(Path.home() / "Documents" / "Markdown"))
        ttk.Entry(out, textvariable=self.out_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(out, text="Chọn...", command=self._pick_out).grid(
            row=0, column=1, padx=(6, 0)
        )

        # --- Tuỳ chọn ---
        opt = ttk.LabelFrame(self, text=" Tuỳ chọn ", padding=8)
        opt.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(opt, text="Ngôn ngữ OCR:").grid(row=0, column=0, sticky="w")
        self.lang_var = tk.StringVar(value=LANGS[0][0])
        ttk.Combobox(
            opt, textvariable=self.lang_var, values=[n for n, _ in LANGS],
            state="readonly", width=16,
        ).grid(row=0, column=1, sticky="w", padx=(6, 16))

        self.images_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Tách ảnh ra thư mục riêng", variable=self.images_var).grid(
            row=0, column=2, sticky="w", padx=(0, 16)
        )
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt, text="Ép OCR (kể cả PDF có sẵn chữ)", variable=self.force_var
        ).grid(row=0, column=3, sticky="w")

        # --- Nút chạy ---
        run = ttk.Frame(self)
        run.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        run.columnconfigure(1, weight=1)
        self.go_btn = ttk.Button(run, text="Chuyển đổi", command=self._start)
        self.go_btn.grid(row=0, column=0)
        self.bar = ttk.Progressbar(run, mode="determinate")
        self.bar.grid(row=0, column=1, sticky="ew", padx=10)
        self.open_btn = ttk.Button(
            run, text="Mở thư mục kết quả", command=self._open_out, state="disabled"
        )
        self.open_btn.grid(row=0, column=2)

        # --- Nhật ký ---
        logf = ttk.LabelFrame(self, text=" Nhật ký ", padding=6)
        logf.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.log = tk.Text(logf, height=9, wrap="word", state="disabled",
                           font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self.log.config(yscrollcommand=lsb.set)

        self.status = ttk.Label(self, text=self._ocr_status(), foreground="#666")
        self.status.grid(row=6, column=0, sticky="w", pady=(6, 0))

    def _ocr_status(self) -> str:
        if find_tesseract():
            return "Sẵn sàng. PDF scan sẽ được OCR tự động."
        return (
            "Chưa cài Tesseract — PDF scan sẽ không chuyển được. "
            "Cài bằng: winget install --id tesseract-ocr.tesseract"
        )

    # ---------------------------------------------------------------- thao tác
    def _add_paths(self, paths: list[Path]) -> None:
        added = 0
        for p in paths:
            if p.is_dir():
                found = [
                    f for f in sorted(p.rglob("*"))
                    if f.is_file() and f.suffix.lower() in SUPPORTED
                ]
            elif p.is_file() and p.suffix.lower() in SUPPORTED:
                found = [p]
            else:
                continue
            for f in found:
                if f not in self.files:
                    self.files.append(f)
                    self.listbox.insert(tk.END, f"  {f.name}   —   {f.parent}")
                    added += 1
        if added:
            self._say(f"Đã thêm {added} file.")

    def _pick_files(self) -> None:
        picked = filedialog.askopenfilenames(
            title="Chọn tài liệu",
            filetypes=[
                ("Tài liệu hỗ trợ", "*.pdf *.docx *.docm *.doc *.xlsx *.xlsm"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx *.docm *.doc"),
                ("Excel", "*.xlsx *.xlsm"),
                ("Tất cả", "*.*"),
            ],
        )
        self._add_paths([Path(p) for p in picked])

    def _pick_folder(self) -> None:
        d = filedialog.askdirectory(title="Chọn thư mục (quét cả thư mục con)")
        if d:
            self._add_paths([Path(d)])

    def _pick_out(self) -> None:
        d = filedialog.askdirectory(title="Lưu kết quả vào đâu")
        if d:
            self.out_var.set(d)

    def _remove(self) -> None:
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.files[i]

    def _clear(self) -> None:
        self.listbox.delete(0, tk.END)
        self.files.clear()

    def _open_out(self) -> None:
        out = Path(self.out_var.get())
        if out.is_dir():
            import os

            os.startfile(out)  # noqa: S606

    # ---------------------------------------------------------------- chạy
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.cancel.set()
            self.go_btn.config(text="Đang dừng...", state="disabled")
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Chưa chọn tài liệu nào.")
            return

        out_dir = Path(self.out_var.get())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Không tạo được thư mục lưu:\n{e}")
            return

        from .cli import plan_outputs

        plan = plan_outputs(self.files, out_dir)
        jobs = [(f, plan[f]) for f in self.files]

        lang = dict((n, c) for n, c in LANGS)[self.lang_var.get()]
        opts = {
            "lang": lang,
            "dpi": 300,
            "images": self.images_var.get(),
            "force_ocr": self.force_var.get(),
        }

        self.log.config(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.config(state="disabled")
        self.bar.config(maximum=len(jobs), value=0)
        self.go_btn.config(text="Dừng")
        self.open_btn.config(state="disabled")

        self.worker = Worker(jobs, opts, self.q)
        self.worker.start()

    def _drain(self) -> None:
        """Đọc tin từ luồng nền. tkinter chỉ được đụng vào từ luồng giao diện."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._say(payload)
                elif kind == "trace":
                    self._say(payload)
                elif kind == "progress":
                    done, _total = payload
                    self.bar.config(value=done)
                elif kind == "done":
                    ok, total = payload
                    self.go_btn.config(text="Chuyển đổi", state="normal")
                    self.open_btn.config(state="normal" if ok else "disabled")
                    self._say(f"\nXong: {ok}/{total} file → {self.out_var.get()}")
                    if ok:
                        self.status.config(
                            text=f"Đã chuyển {ok}/{total} file.", foreground="#137333"
                        )
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _say(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")


def main(argv: list[str] | None = None) -> int:
    import sys

    force_utf8()
    args = argv if argv is not None else sys.argv[1:]
    initial = [Path(a) for a in args if Path(a).exists()]

    root = tk.Tk()
    try:
        # Giao diện nét trên màn hình có DPI cao, nếu không chữ sẽ mờ nhoè.
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass

    App(root, initial=initial)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
