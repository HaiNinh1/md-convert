"""Giao diện web cho md-convert.

Chạy một máy chủ nhỏ ở localhost rồi mở trình duyệt — không cần gõ lệnh gì.

Máy chủ CHỈ lắng nghe trên 127.0.0.1, không phải 0.0.0.0: nó nhận file tuỳ ý
rồi ghi ra đĩa tạm, mở ra mạng LAN là biếu không cho người khác. Toàn bộ vẫn
chạy offline, không gọi ra Internet.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

from .console import force_utf8
from .ocr import TesseractMissing, find_tesseract
from .office import LegacyDocError
from .router import SUPPORTED, UnsupportedFile, convert_file

MAX_UPLOAD_MB = 200

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


PAGE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>md-convert — Chuyển tài liệu sang Markdown</title>
<style>
  :root {
    --bg: #f6f7f9; --card: #fff; --ink: #1c2430; --muted: #6b7688;
    --line: #e3e7ee; --accent: #2f6fed; --ok: #157347; --err: #c8372d;
    --code-bg: #f2f4f7;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #161a20; --card: #1e242c; --ink: #e8ecf2; --muted: #97a1b0;
      --line: #2f3742; --accent: #5b91ff; --ok: #4ec27a; --err: #ff7a6e;
      --code-bg: #161a20;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.6 "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  .wrap { max-width: 940px; margin: 0 auto; padding: 28px 20px 60px; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0 0 22px; }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; padding: 18px; margin-bottom: 16px;
  }
  #drop {
    border: 2px dashed var(--line); border-radius: 12px; padding: 44px 20px;
    text-align: center; cursor: pointer; transition: .15s;
  }
  #drop:hover, #drop.over { border-color: var(--accent); background: rgba(47,111,237,.06); }
  #drop h2 { margin: 0 0 6px; font-size: 17px; font-weight: 600; }
  #drop p { margin: 0; color: var(--muted); font-size: 13.5px; }
  .files { list-style: none; padding: 0; margin: 14px 0 0; }
  .files li {
    display: flex; align-items: center; gap: 10px; padding: 9px 12px;
    border: 1px solid var(--line); border-radius: 8px; margin-bottom: 7px;
    font-size: 14px;
  }
  .files .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .files .sz { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .x { border: 0; background: 0; color: var(--muted); cursor: pointer; font-size: 17px; padding: 0 4px; }
  .x:hover { color: var(--err); }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
  button.go {
    background: var(--accent); color: #fff; border: 0; border-radius: 8px;
    padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer;
  }
  button.go:disabled { opacity: .5; cursor: default; }
  button.ghost {
    background: 0; color: var(--ink); border: 1px solid var(--line);
    border-radius: 8px; padding: 9px 16px; cursor: pointer; font-size: 14px;
  }
  select { padding: 8px; border-radius: 7px; border: 1px solid var(--line);
           background: var(--card); color: var(--ink); font-size: 14px; }
  label.opt { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
  .bar { height: 5px; background: var(--line); border-radius: 3px; overflow: hidden; display: none; margin-top: 14px; }
  .bar.on { display: block; }
  .bar i { display: block; height: 100%; width: 40%; background: var(--accent);
           animation: slide 1.1s ease-in-out infinite; }
  @keyframes slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
  .sum { display: flex; gap: 22px; padding: 12px 0; font-size: 14.5px; flex-wrap: wrap; }
  .sum b { font-variant-numeric: tabular-nums; }
  .ok-t { color: var(--ok); } .err-t { color: var(--err); }
  .res { border: 1px solid var(--line); border-radius: 9px; margin-bottom: 9px; overflow: hidden; }
  .res > summary {
    padding: 11px 13px; cursor: pointer; display: flex; align-items: center;
    gap: 9px; font-size: 14.5px; list-style: none;
  }
  .res > summary::-webkit-details-marker { display: none; }
  .res .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag { font-size: 12px; color: var(--muted); }
  pre {
    margin: 0; padding: 14px; background: var(--code-bg); border-top: 1px solid var(--line);
    overflow-x: auto; font: 12.5px/1.65 Consolas, "Cascadia Mono", monospace;
    max-height: 380px; white-space: pre-wrap; word-break: break-word;
  }
  .why { padding: 0 13px 13px; color: var(--err); font-size: 13.5px; }
  .note { font-size: 13px; color: var(--muted); margin-top: 18px; }
  .warn { background: rgba(200,55,45,.09); border: 1px solid var(--err);
          color: var(--err); border-radius: 8px; padding: 10px 13px;
          font-size: 13.5px; margin-bottom: 16px; }
  .dl { border: 0; background: 0; color: var(--accent); cursor: pointer;
        font-size: 13.5px; padding: 3px 7px; border-radius: 5px; }
  .dl:hover { background: rgba(47,111,237,.1); }
</style>
</head>
<body>
<div class="wrap">
  <h1>md-convert</h1>
  <p class="sub">Chuyển PDF, PDF scan, Word, Excel sang Markdown. Chạy offline hoàn toàn trên máy bạn.</p>

  {% if not tesseract %}
  <div class="warn">
    Chưa cài Tesseract nên <b>PDF scan sẽ không chuyển được</b>.
    Cài bằng lệnh: <code>winget install --id tesseract-ocr.tesseract</code>
  </div>
  {% endif %}

  <div class="card">
    <div id="drop">
      <h2>Kéo thả tài liệu vào đây</h2>
      <p>hoặc bấm để chọn file — PDF, Word (.docx), Excel (.xlsx)</p>
    </div>
    <input type="file" id="inp" multiple hidden
           accept=".pdf,.docx,.docm,.doc,.xlsx,.xlsm">
    <ul class="files" id="list"></ul>

    <div class="row">
      <button class="go" id="go" disabled>Chuyển đổi</button>
      <button class="ghost" id="clr" hidden>Xoá hết</button>
      <span style="flex:1"></span>
      <label class="opt">Ngôn ngữ OCR:
        <select id="lang">
          <option value="vie">Tiếng Việt</option>
          <option value="vie+eng">Tiếng Việt + Anh</option>
          <option value="eng">Tiếng Anh</option>
        </select>
      </label>
      <label class="opt"><input type="checkbox" id="force"> Ép OCR</label>
    </div>
    <div class="bar" id="bar"><i></i></div>
  </div>

  <div id="out"></div>
</div>

<script>
const $ = s => document.querySelector(s);
let files = [];

const drop = $("#drop"), inp = $("#inp");
drop.onclick = () => inp.click();
inp.onchange = e => add([...e.target.files]);
["dragenter","dragover"].forEach(k => drop.addEventListener(k, e => {
  e.preventDefault(); drop.classList.add("over");
}));
["dragleave","drop"].forEach(k => drop.addEventListener(k, e => {
  e.preventDefault(); drop.classList.remove("over");
}));
drop.addEventListener("drop", e => add([...e.dataTransfer.files]));

function add(fs) {
  for (const f of fs) if (!files.some(x => x.name === f.name && x.size === f.size)) files.push(f);
  render();
}
function kb(n) {
  return n < 1024 ? n + " B"
       : n < 1048576 ? (n/1024).toFixed(0) + " KB"
       : (n/1048576).toFixed(1) + " MB";
}
function render() {
  $("#list").innerHTML = files.map((f, i) =>
    `<li><span class="nm">${esc(f.name)}</span><span class="sz">${kb(f.size)}</span>
     <button class="x" onclick="rm(${i})" title="Bỏ file này">×</button></li>`).join("");
  $("#go").disabled = !files.length;
  $("#clr").hidden = !files.length;
}
function rm(i) { files.splice(i, 1); render(); }
$("#clr").onclick = () => { files = []; render(); $("#out").innerHTML = ""; };
function esc(s) {
  return s.replace(/[&<>"']/g, c =>
    ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
}

$("#go").onclick = async () => {
  if (!files.length) return;
  const fd = new FormData();
  files.forEach(f => fd.append("files", f));
  fd.append("lang", $("#lang").value);
  fd.append("force_ocr", $("#force").checked ? "1" : "0");

  $("#go").disabled = true;
  $("#go").textContent = "Đang chuyển...";
  $("#bar").classList.add("on");
  $("#out").innerHTML = "";

  try {
    const r = await fetch("/api/convert", { method: "POST", body: fd });
    if (!r.ok) throw new Error("Máy chủ trả về lỗi " + r.status);
    show(await r.json());
  } catch (e) {
    $("#out").innerHTML = `<div class="card"><b class="err-t">Lỗi:</b> ${esc(e.message)}</div>`;
  } finally {
    $("#go").disabled = false;
    $("#go").textContent = "Chuyển đổi";
    $("#bar").classList.remove("on");
  }
};

let lastOk = [];
function show(d) {
  lastOk = d.results.filter(r => r.ok);
  const bad = d.results.filter(r => !r.ok);
  let h = `<div class="card"><div class="sum">
    <span>Thành công: <b class="ok-t">${lastOk.length}/${d.results.length}</b></span>
    <span>Thất bại: <b class="${bad.length ? "err-t" : ""}">${bad.length}/${d.results.length}</b></span>
    <span style="flex:1"></span>`;
  if (lastOk.length) h += `<button class="ghost" onclick="zipAll()">Tải tất cả (.zip)</button>`;
  h += `</div></div>`;

  for (const r of d.results) {
    if (r.ok) {
      h += `<details class="res"><summary>
        <span class="ok-t">✓</span><span class="nm">${esc(r.out)}</span>
        <span class="tag">${esc(r.detail)}</span>
        <button class="dl" onclick="event.preventDefault();dl('${esc(r.out)}')">Tải về</button>
      </summary><pre>${esc(r.markdown)}</pre></details>`;
    } else {
      h += `<details class="res"><summary>
        <span class="err-t">✗</span><span class="nm">${esc(r.name)}</span>
        <span class="tag">không chuyển được</span>
      </summary><div class="why">${esc(r.error)}</div></details>`;
    }
  }
  $("#out").innerHTML = h;
}

function dl(name) {
  const r = lastOk.find(x => x.out === name);
  if (!r) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([r.markdown], { type: "text/markdown;charset=utf-8" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function zipAll() {
  const r = await fetch("/api/zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(lastOk.map(x => ({ name: x.out, markdown: x.markdown }))),
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = "markdown.zip";
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(PAGE, tesseract=bool(find_tesseract()))


@app.get("/favicon.ico")
def favicon():
    icon = Path(__file__).parent.parent / "assets" / "md-convert.ico"
    if not icon.exists():
        return ("", 204)  # không có icon thì im lặng, đừng để trình duyệt báo 404
    return send_file(icon, mimetype="image/vnd.microsoft.icon")


@app.post("/api/convert")
def api_convert():
    uploads = request.files.getlist("files")
    if not uploads:
        return jsonify({"results": []})

    lang = request.form.get("lang", "vie")
    force_ocr = request.form.get("force_ocr") == "1"

    results = []
    # Thư mục tạm bị xoá ngay khi xong: file người dùng tải lên không có lý do gì
    # để nằm lại trên đĩa.
    with tempfile.TemporaryDirectory(prefix="mdconvert-") as tmp:
        tmpdir = Path(tmp)
        for up in uploads:
            # Chỉ lấy phần tên, bỏ mọi thành phần đường dẫn: tên file là dữ liệu
            # người dùng gửi lên, có thể chứa "..\..\" để ghi đè file ngoài ý muốn.
            name = Path(up.filename or "khong-ten").name
            if Path(name).suffix.lower() not in SUPPORTED:
                results.append({
                    "ok": False, "name": name,
                    "error": f"Định dạng không hỗ trợ. Nhận: {', '.join(sorted(SUPPORTED))}",
                })
                continue

            src = tmpdir / name
            up.save(src)
            out_dir = tmpdir / "ra"
            out_dir.mkdir(exist_ok=True)

            try:
                kw: dict = {"extract_images": False}
                if src.suffix.lower() == ".pdf":
                    kw.update(ocr_lang=lang, dpi=300, force_ocr=force_ocr)
                md, stats = convert_file(src, out_dir, **kw)
            except LegacyDocError as e:
                results.append({"ok": False, "name": name, "error": str(e)})
                continue
            except TesseractMissing as e:
                results.append({
                    "ok": False, "name": name,
                    "error": f"Đây là bản scan nên cần OCR, nhưng: {e}",
                })
                continue
            except UnsupportedFile as e:
                results.append({"ok": False, "name": name, "error": str(e)})
                continue
            except Exception as e:  # noqa: BLE001
                results.append({
                    "ok": False, "name": name,
                    "error": _friendly(e, tmpdir, name),
                })
                continue

            if not md.strip():
                results.append({
                    "ok": False, "name": name,
                    "error": "Không trích được nội dung nào từ file này.",
                })
                continue

            results.append({
                "ok": True, "name": name, "out": f"{Path(name).stem}.md",
                "markdown": md, "detail": _describe(stats),
            })

    return jsonify({"results": results})


@app.post("/api/zip")
def api_zip():
    items = request.get_json(silent=True) or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for it in items:
            name = Path(str(it.get("name", "khong-ten.md"))).name
            z.writestr(name, str(it.get("markdown", "")))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="markdown.zip")


def _friendly(exc: Exception, tmpdir: Path, name: str) -> str:
    """Đổi lỗi kỹ thuật thành câu người dùng hiểu được.

    Thông báo thô của thư viện nhắc tới đường dẫn tạm trong AppData — nơi người
    dùng chưa từng đặt file vào và sẽ bị xoá ngay sau đó. Nêu ra chỉ khiến họ rối
    và tưởng file gốc của mình hỏng ở chỗ khác.
    """
    raw = str(exc)
    # Đường dẫn tạm không có ý nghĩa gì với người xem, thay bằng tên file thật.
    raw = raw.replace(str(tmpdir), "").replace(str(tmpdir).replace("\\", "\\\\"), "")

    kind = type(exc).__name__
    if kind == "FileDataError" or "cannot open" in raw.lower() or "Failed to open" in raw:
        return (
            f"Không mở được '{name}'. File có thể bị hỏng, chép dở, "
            f"hoặc không đúng định dạng như phần đuôi file gợi ý."
        )
    if "password" in raw.lower() or "encrypted" in raw.lower():
        return f"'{name}' đang được đặt mật khẩu. Hãy gỡ mật khẩu rồi thử lại."
    return f"{kind}: {raw}".strip()


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
    return ", ".join(bits)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import threading
    import webbrowser

    force_utf8()

    p = argparse.ArgumentParser(description="Giao diện web cho md-convert")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    args = p.parse_args(argv)

    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  md-convert đang chạy tại: {url}")
    print("  Nhấn Ctrl+C để dừng.\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # host cố định 127.0.0.1 — xem docstring đầu file.
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
