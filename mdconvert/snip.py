"""Công cụ "chọn vùng → ra chữ" — bám sát trải nghiệm của OCR-Offline.

Người dùng tải ảnh hoặc PDF lên, xem trang, kéo chuột khoanh một hay nhiều vùng,
bấm nút là ra chữ của từng vùng để copy. Khác OCR-Offline ở một điểm cốt lõi:
OCR chạy Ở SERVER bằng Tesseract (vie.traineddata) chứ không phải tesseract.js
trong trình duyệt — nhờ vậy đọc đúng dấu tiếng Việt, tái dùng đúng engine mà
nhánh chuyển-sang-Markdown đang dùng, không phải nhồi thêm ~15MB WASM vào app.

Luồng:
  1. POST /api/snip/upload  — nhận file, render mọi trang ra PNG, giữ trong bộ
     nhớ tạm theo token, trả về số trang + kích thước từng trang.
  2. GET  /api/snip/page/<token>/<i>  — trả PNG của trang để trình duyệt vẽ lên
     canvas.
  3. POST /api/snip/ocr  — nhận toạ độ các vùng (theo pixel của chính ảnh PNG),
     cắt vùng, OCR, trả chữ từng vùng.

Toạ độ vùng gửi lên nằm ĐÚNG hệ pixel của ảnh PNG đã render, nên server chỉ việc
crop thẳng — không có khâu quy đổi thang nào để lệch.
"""

from __future__ import annotations

import io
from collections import OrderedDict
from pathlib import Path

from flask import Blueprint, jsonify, render_template_string, request, send_file

from .ocr import TesseractMissing, find_tesseract, get_engine, ocr_image_text

# DPI render trang. 200 đủ nét để OCR vùng chữ nhỏ mà ảnh không quá nặng; canvas
# hiển thị thu nhỏ theo bề ngang khung nên toạ độ vẫn quy về đúng pixel này.
RENDER_DPI = 200
# Chặn PDF quá dày làm phình bộ nhớ — đây là công cụ chạy một mình trên máy.
MAX_PAGES = 300

snip_bp = Blueprint("snip", __name__)

# token -> {"pages": [png_bytes, ...], "dims": [(w, h), ...]}. Chỉ giữ vài lô gần
# nhất, y như _STORE ở web.py: một người dùng, không cần nhớ lâu.
_SNIP: "OrderedDict[str, dict]" = OrderedDict()
_SNIP_MAX = 3


def _remember(entry: dict) -> str:
    import secrets

    token = secrets.token_urlsafe(12)
    _SNIP[token] = entry
    while len(_SNIP) > _SNIP_MAX:
        _SNIP.popitem(last=False)
    return token


def _render_pdf(data: bytes) -> dict:
    import fitz  # PyMuPDF

    pages: list[bytes] = []
    dims: list[tuple[int, int]] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n = min(doc.page_count, MAX_PAGES)
        for i in range(n):
            pix = doc.load_page(i).get_pixmap(dpi=RENDER_DPI, alpha=False)
            pages.append(pix.tobytes("png"))
            dims.append((pix.width, pix.height))
    finally:
        doc.close()
    return {"pages": pages, "dims": dims}


def _render_image(data: bytes) -> dict:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"pages": [buf.getvalue()], "dims": [(img.width, img.height)]}


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


@snip_bp.get("/snip")
def snip_page():
    from .online_ocr import available as online_available

    return render_template_string(
        SNIP_PAGE,
        tesseract=bool(find_tesseract()),
        online=online_available(),
    )


@snip_bp.post("/api/snip/upload")
def snip_upload():
    up = request.files.get("file")
    if up is None or not (up.filename or "").strip():
        return jsonify({"error": "Chưa chọn file nào."}), 400

    name = Path(up.filename).name
    ext = Path(name).suffix.lower()
    data = up.read()
    if not data:
        return jsonify({"error": "File rỗng."}), 400

    try:
        if ext == ".pdf":
            entry = _render_pdf(data)
        elif ext in IMAGE_EXTS:
            entry = _render_image(data)
        else:
            return jsonify({
                "error": "Chỉ nhận ảnh (PNG, JPG, TIFF, WEBP...) hoặc PDF."
            }), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Không mở được file: {e}"}), 400

    if not entry["pages"]:
        return jsonify({"error": "File không có trang nào để hiển thị."}), 400

    token = _remember(entry)
    return jsonify({
        "token": token,
        "name": name,
        "pages": len(entry["pages"]),
        "dims": [{"w": w, "h": h} for (w, h) in entry["dims"]],
    })


@snip_bp.get("/api/snip/page/<token>/<int:idx>")
def snip_page_image(token: str, idx: int):
    entry = _SNIP.get(token)
    if not entry or idx < 0 or idx >= len(entry["pages"]):
        return ("Trang đã hết hạn, hãy tải lại file.", 404)
    return send_file(io.BytesIO(entry["pages"][idx]), mimetype="image/png")


@snip_bp.post("/api/snip/ocr")
def snip_ocr():
    body = request.get_json(silent=True) or {}
    token = body.get("token")
    page = int(body.get("page", 0))
    regions = body.get("regions") or []
    lang = body.get("lang", "vie")
    fix_spell = bool(body.get("fix_spell"))
    use_online = body.get("engine") == "online"
    try:
        psm = int(body.get("psm", 6))
    except (TypeError, ValueError):
        psm = 6

    entry = _SNIP.get(token)
    if not entry or page < 0 or page >= len(entry["pages"]):
        return jsonify({"error": "Kết quả đã hết hạn, hãy tải lại file."}), 404

    online_key = None
    if use_online:
        from .online_ocr import get_api_key

        online_key = get_api_key()
        if not online_key:
            return jsonify({
                "error": "Chưa cấu hình khoá OCR online. Đặt biến OCRSPACE_API_KEY "
                         "hoặc tạo file ocrspace_key.txt ở thư mục dự án."
            }), 400
        engine = None
    else:
        try:
            engine = get_engine(lang)
        except TesseractMissing as e:
            return jsonify({"error": str(e)}), 400

    from PIL import Image

    base = Image.open(io.BytesIO(entry["pages"][page]))
    base.load()
    W, H = base.size

    out = []
    for r in regions:
        try:
            x = max(0, int(round(r["x"])))
            y = max(0, int(round(r["y"])))
            w = int(round(r["w"]))
            h = int(round(r["h"]))
        except (KeyError, TypeError, ValueError):
            out.append({"text": "", "error": "Vùng không hợp lệ."})
            continue
        x1 = min(W, x + w)
        y1 = min(H, y + h)
        if x1 - x < 3 or y1 - y < 3:
            out.append({"text": "", "error": "Vùng quá nhỏ."})
            continue
        crop = base.crop((x, y, x1, y1))
        try:
            if use_online:
                from .online_ocr import ocr_image_text_online
                text = ocr_image_text_online(crop, api_key=online_key)
            else:
                text = ocr_image_text(engine, crop, psm=psm, dpi=RENDER_DPI)
        except Exception as e:  # noqa: BLE001
            out.append({"text": "", "error": f"Lỗi OCR: {e}"})
            continue
        # OCR online đã đọc đúng dấu; sửa chính tả chỉ có ích cho bản Tesseract.
        if fix_spell and not use_online and "vie" in lang:
            from .spellfix import fix_text
            text = fix_text(text)
        out.append({"text": text})

    return jsonify({"regions": out})


SNIP_PAGE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chọn vùng → ra chữ — md-convert</title>
<style>
:root { --primary: #4F46E5; --bg: #F9FAFB; --border: #E5E7EB; --text: #1F2937; --subtext: #6B7280; --orange: #F59E0B; --green: #10B981; }
body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 16px; }
.card { background: white; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.drop-zone { border: 2px dashed #A5B4FC; border-radius: 12px; padding: 32px; text-align: center; background: #F5F7FF; }
.drop-zone.dragover { border-color: var(--primary); background: #EEF2FF; }
.icon-upload { width: 48px; height: 48px; margin: 0 auto 12px; opacity: 0.6; }
.btn { background: var(--primary); color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; }
.btn:disabled { background: #9CA3AF; cursor: not-allowed; }
.btn-orange { background: var(--orange); }
.btn-green { background: var(--green); }
.btn-outline { background: white; color: var(--text); border: 1px solid var(--border); }
.btn-sm { padding: 6px 12px; font-size: 14px; }
#fileInput { display: none; }
h3 { margin: 0 0 16px 0; display: flex; align-items: center; gap: 8px; font-size: 18px; }
.badge { background: #EEF2FF; color: var(--primary); width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 14px; }
.label { font-weight: 600; margin: 16px 0 8px; display: block; }
select { width: 100%; padding: 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 15px; background: white; box-sizing: border-box; }
.help-text { font-size: 13px; color: var(--subtext); margin-top: 4px; }
#fname { margin: 16px 0 0; font-weight: 500; color: var(--primary); }
.topbar { display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.topbar a { color: var(--primary); text-decoration:none; font-weight:600; font-size:14px; }
.warn { background:#FEF2F2; border:1px solid #FECACA; color:#991B1B; border-radius:10px; padding:12px 14px; margin-bottom:16px; font-size:14px; }
.config-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:768px){ .config-row{ grid-template-columns:1fr; } }
.preview-wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) {.preview-wrap { grid-template-columns: 1fr; } }
.preview-box { border: 1px solid var(--border); border-radius: 8px; padding: 12px; background: #FAFAFA; }
.preview-header { display: flex; justify-content: space-between; align-items: center; margin: 0 0 8px 0; gap:8px; flex-wrap:wrap; }
.preview-header h4 { margin: 0; font-size: 14px; color: var(--subtext); }
.page-nav { display: flex; gap: 4px; align-items: center; }
.page-nav input { width: 50px; padding: 4px; border: 1px solid var(--border); border-radius: 4px; text-align: center; font-size: 13px; }
#pageCanvas { width: 100%; border-radius: 4px; background: white; cursor: crosshair; touch-action: none; display:block; }
#cropOverlay { position: absolute; border: 2px dashed #4F46E5; background: rgba(79,70,229,0.1); display: none; pointer-events: none; }
#cropContainer { position: absolute; top: 0; left: 0; pointer-events: none; }
.region-block { border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:10px; background:white; }
.region-block .rh { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.region-block .dot { width:14px;height:14px;border-radius:4px; }
.region-block textarea { width:100%; box-sizing:border-box; border:1px solid var(--border); border-radius:6px; padding:8px; font-size:14px; line-height:1.5; resize:vertical; min-height:44px; font-family:inherit; }
.muted { color:var(--subtext); font-size:13px; }
.btn-group { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
.hidden { display:none; }
.spin { display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;border-radius:50%;animation:sp .7s linear infinite; }
@keyframes sp { to { transform:rotate(360deg); } }
</style>
</head>
<body>

<div class="topbar">
  <a href="/convert">Chuyển tài liệu sang Markdown →</a>
  <span class="muted">·</span>
  <b>Chọn vùng → ra chữ</b>
</div>

{% if not tesseract %}
<div class="warn">
  Chưa cài Tesseract nên <b>không nhận chữ được</b>.
  Cài bằng lệnh: <code>winget install --id tesseract-ocr.tesseract</code>
</div>
{% endif %}

<div class="card">
  <div class="drop-zone" id="dropZone">
    <svg class="icon-upload" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
      <polyline points="17 8 12 3 7 8"></polyline>
      <line x1="12" y1="3" x2="12" y2="15"></line>
    </svg>
    <div style="font-weight: 600; margin-bottom: 4px;">Kéo thả ảnh hoặc PDF vào đây</div>
    <div style="color: var(--subtext); margin-bottom: 16px;">hoặc</div>
    <button class="btn" type="button" id="pickFile">Chọn file từ máy</button>
    <input type="file" id="fileInput" accept=".pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif">
    <div id="fname"></div>
  </div>
</div>

<div class="card">
  <h3><span class="badge">2</span> Cấu hình nhận dạng</h3>
  <div class="config-row">
    <div>
      <label class="label">Ngôn ngữ</label>
      <select id="lang">
        <option value="vie" selected>Tiếng Việt</option>
        <option value="vie+eng">Tiếng Việt + Anh</option>
        <option value="eng">Tiếng Anh</option>
      </select>
    </div>
    <div>
      <label class="label">Kiểu vùng chọn</label>
      <select id="psm">
        <option value="7">Một dòng chữ (PSM 7)</option>
        <option value="6" selected>Một khối chữ nhiều dòng (PSM 6)</option>
        <option value="3">Tự động (PSM 3)</option>
        <option value="11">Chữ thưa thớt (PSM 11)</option>
      </select>
    </div>
  </div>
  <label class="label">Bộ nhận dạng</label>
  <select id="engine">
    <option value="online"{% if online %} selected{% else %} disabled{% endif %}>Online chính xác cao — OCR.space{% if not online %} (chưa cấu hình khoá){% endif %}</option>
    <option value="local"{% if not online %} selected{% endif %}>Máy này — Tesseract (offline, miễn phí, có thể sai dấu)</option>
  </select>
  <div class="help-text">{% if online %}Đang dùng <b>Online</b> — đọc đúng dấu tiếng Việt hơn hẳn (cần mạng). Chuyển sang "Máy này" nếu mất mạng.{% else %}Để bật bản chính xác cao: đặt biến OCRSPACE_API_KEY hoặc tạo file <b>ocrspace_key.txt</b> ở thư mục dự án (lấy khoá miễn phí tại ocr.space/ocrapi).{% endif %}</div>
  <div class="help-text">Chọn "Một dòng chữ" khi vùng bạn khoanh chỉ có đúng một dòng — kết quả gọn hơn.</div>
  <label style="display:inline-flex;align-items:center;gap:8px;margin-top:14px;font-size:14px;cursor:pointer">
    <input type="checkbox" id="spell" style="width:18px;height:18px">
    Tự động sửa chính tả tiếng Việt (chỉ sửa sai dấu, không đụng tên riêng/mã số)
  </label>
</div>

<div class="card hidden" id="workCard">
  <div class="preview-wrap">
    <div class="preview-box">
      <div class="preview-header">
        <h4>Trang — click &amp; kéo chuột để khoanh vùng</h4>
        <div class="page-nav">
          <button class="btn btn-outline btn-sm" id="prevPage" type="button">◀</button>
          <input type="number" id="pageInput" min="1" value="1">
          <span style="font-size:13px">/<span id="totalPages">0</span></span>
          <button class="btn btn-outline btn-sm" id="nextPage" type="button">▶</button>
        </div>
      </div>
      <div style="position: relative;">
        <canvas id="pageCanvas"></canvas>
        <div id="cropOverlay"></div>
        <div id="cropContainer"></div>
      </div>
      <div class="btn-group">
        <button class="btn btn-sm" id="runOcr" type="button">Nhận chữ vùng đã chọn</button>
        <button class="btn btn-outline btn-sm" id="clearRegions" type="button">Xoá vùng trang này</button>
        <span class="muted" style="align-self:center">Đã khoanh: <b id="regionCount">0</b> vùng</span>
      </div>
    </div>
    <div class="preview-box">
      <div class="preview-header">
        <h4>Chữ nhận được</h4>
        <button class="btn btn-outline btn-sm hidden" id="copyAll" type="button">Copy tất cả</button>
      </div>
      <div id="results"><div class="muted">Khoanh một vùng rồi bấm "Nhận chữ vùng đã chọn".</div></div>
    </div>
  </div>
</div>

<script>
const REGION_COLORS = ['#4F46E5', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899'];
const $ = s => document.getElementById(s);
let token = null, numPages = 0, dims = [];
let currentPage = 0;               // 0-based
let regionsByPage = {};            // pageIdx -> [{x,y,w,h}]  (pixel của ảnh gốc)
let resultsByPage = {};            // pageIdx -> [{text} | {error}]
let isDrawing = false, startX = 0, startY = 0;
const pageImg = new Image();

const dropZone = $('dropZone'), fileInput = $('fileInput'), pageCanvas = $('pageCanvas');
const cropOverlay = $('cropOverlay'), cropContainer = $('cropContainer');
const ctx = pageCanvas.getContext('2d');

$('pickFile').onclick = () => fileInput.click();
dropZone.ondragover = e => { e.preventDefault(); dropZone.classList.add('dragover'); };
dropZone.ondragleave = () => dropZone.classList.remove('dragover');
dropZone.ondrop = e => { e.preventDefault(); dropZone.classList.remove('dragover'); if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]); };
fileInput.onchange = e => { if (e.target.files.length) upload(e.target.files[0]); };

async function upload(file) {
  $('fname').textContent = 'Đang tải và render "' + file.name + '"...';
  const fd = new FormData(); fd.append('file', file);
  let d;
  try {
    const r = await fetch('/api/snip/upload', { method: 'POST', body: fd });
    d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Lỗi ' + r.status));
  } catch (e) { $('fname').textContent = '✗ ' + e.message; return; }
  token = d.token; numPages = d.pages; dims = d.dims;
  regionsByPage = {}; resultsByPage = {};
  $('fname').innerHTML = '✓ ' + d.name + ' — ' + numPages + ' trang';
  $('totalPages').textContent = numPages;
  $('pageInput').max = numPages;
  $('workCard').classList.remove('hidden');
  loadPage(0);
}

function loadPage(idx) {
  if (idx < 0 || idx >= numPages) return;
  currentPage = idx;
  $('pageInput').value = idx + 1;
  pageImg.onload = () => {
    pageCanvas.width = pageImg.naturalWidth;
    pageCanvas.height = pageImg.naturalHeight;
    ctx.drawImage(pageImg, 0, 0);
    renderRegions();
    renderResults();
  };
  pageImg.src = '/api/snip/page/' + token + '/' + idx + '?t=' + Date.now();
}

$('prevPage').onclick = () => loadPage(currentPage - 1);
$('nextPage').onclick = () => loadPage(currentPage + 1);
$('pageInput').onchange = () => { const p = parseInt($('pageInput').value) - 1; if (p >= 0 && p < numPages) loadPage(p); };

// Toạ độ con trỏ quy về pixel thật của canvas (= pixel ảnh), không phụ thuộc
// việc canvas đang bị CSS thu nhỏ theo bề ngang khung.
function getPointerPos(e) {
  const rect = pageCanvas.getBoundingClientRect();
  return {
    x: (e.clientX - rect.left) * (pageCanvas.width / rect.width),
    y: (e.clientY - rect.top) * (pageCanvas.height / rect.height)
  };
}

pageCanvas.onpointerdown = e => {
  e.preventDefault(); isDrawing = true;
  const p = getPointerPos(e); startX = p.x; startY = p.y;
  pageCanvas.setPointerCapture(e.pointerId);
};
pageCanvas.onpointermove = e => {
  if (!isDrawing) return;
  e.preventDefault();
  const p = getPointerPos(e);
  const rect = pageCanvas.getBoundingClientRect();
  const sx = rect.width / pageCanvas.width, sy = rect.height / pageCanvas.height;
  cropOverlay.style.display = 'block';
  cropOverlay.style.left = Math.min(startX, p.x) * sx + 'px';
  cropOverlay.style.top = Math.min(startY, p.y) * sy + 'px';
  cropOverlay.style.width = Math.abs(p.x - startX) * sx + 'px';
  cropOverlay.style.height = Math.abs(p.y - startY) * sy + 'px';
};
pageCanvas.onpointerup = e => {
  if (!isDrawing) return;
  isDrawing = false;
  cropOverlay.style.display = 'none';
  const p = getPointerPos(e);
  const area = { x: Math.min(startX, p.x), y: Math.min(startY, p.y), w: Math.abs(p.x - startX), h: Math.abs(p.y - startY) };
  pageCanvas.releasePointerCapture(e.pointerId);
  if (area.w > 8 && area.h > 8) {
    (regionsByPage[currentPage] = regionsByPage[currentPage] || []).push(area);
    renderRegions();
  }
};

function renderRegions() {
  const rect = pageCanvas.getBoundingClientRect();
  const sx = rect.width / pageCanvas.width, sy = rect.height / pageCanvas.height;
  cropContainer.innerHTML = '';
  cropContainer.style.width = rect.width + 'px';
  cropContainer.style.height = rect.height + 'px';
  const areas = regionsByPage[currentPage] || [];
  areas.forEach((a, i) => {
    const color = REGION_COLORS[i % REGION_COLORS.length];
    const div = document.createElement('div');
    div.style.cssText = `position:absolute;border:2px solid ${color};background:${color}20;left:${a.x*sx}px;top:${a.y*sy}px;width:${a.w*sx}px;height:${a.h*sy}px;pointer-events:auto;`;
    const label = document.createElement('span');
    label.style.cssText = `background:${color};color:white;padding:1px 6px;font-size:11px;border-radius:4px;position:absolute;left:0;top:0;`;
    label.textContent = i + 1;
    div.appendChild(label);
    const close = document.createElement('span');
    close.style.cssText = `background:#EF4444;color:white;width:16px;height:16px;font-size:12px;font-weight:bold;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;position:absolute;right:-8px;top:-8px;cursor:pointer;`;
    close.innerHTML = '&times;';
    close.onclick = ev => { ev.stopPropagation(); areas.splice(i, 1); renderRegions(); };
    div.appendChild(close);
    cropContainer.appendChild(div);
  });
  $('regionCount').textContent = areas.length;
}
window.addEventListener('resize', () => { if (token) renderRegions(); });

$('clearRegions').onclick = () => { regionsByPage[currentPage] = []; renderRegions(); };

$('runOcr').onclick = async () => {
  const areas = regionsByPage[currentPage] || [];
  if (!areas.length) { alert('Hãy khoanh ít nhất một vùng trên trang.'); return; }
  const btn = $('runOcr');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Đang nhận chữ...';
  try {
    const r = await fetch('/api/snip/ocr', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, page: currentPage, regions: areas, lang: $('lang').value, psm: $('psm').value, fix_spell: $('spell').checked, engine: $('engine').value })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Lỗi ' + r.status));
    resultsByPage[currentPage] = d.regions;
    renderResults();
  } catch (e) { alert(e.message); }
  finally { btn.disabled = false; btn.textContent = 'Nhận chữ vùng đã chọn'; }
};

function renderResults() {
  const box = $('results');
  const res = resultsByPage[currentPage];
  if (!res || !res.length) {
    box.innerHTML = '<div class="muted">Khoanh một vùng rồi bấm "Nhận chữ vùng đã chọn".</div>';
    $('copyAll').classList.add('hidden');
    return;
  }
  box.innerHTML = '';
  res.forEach((item, i) => {
    const color = REGION_COLORS[i % REGION_COLORS.length];
    const block = document.createElement('div');
    block.className = 'region-block';
    const head = document.createElement('div'); head.className = 'rh';
    head.innerHTML = `<span class="dot" style="background:${color}"></span><b>Vùng ${i+1}</b>`;
    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn btn-outline btn-sm'; copyBtn.style.marginLeft = 'auto'; copyBtn.textContent = 'Copy';
    const ta = document.createElement('textarea');
    ta.value = item.error ? '' : (item.text || '');
    ta.rows = Math.min(8, Math.max(2, (ta.value.match(/\\n/g) || []).length + 1));
    if (item.error) { ta.placeholder = item.error; ta.style.borderColor = '#FECACA'; }
    copyBtn.onclick = () => { ta.select(); navigator.clipboard && navigator.clipboard.writeText(ta.value); copyBtn.textContent = 'Đã copy ✓'; setTimeout(() => copyBtn.textContent = 'Copy', 1200); };
    head.appendChild(copyBtn);
    block.appendChild(head); block.appendChild(ta);
    box.appendChild(block);
  });
  $('copyAll').classList.remove('hidden');
}

$('copyAll').onclick = () => {
  const res = resultsByPage[currentPage] || [];
  const all = res.map((r, i) => '[Vùng ' + (i+1) + ']\\n' + (r.text || '')).join('\\n\\n');
  navigator.clipboard && navigator.clipboard.writeText(all);
  $('copyAll').textContent = 'Đã copy ✓'; setTimeout(() => $('copyAll').textContent = 'Copy tất cả', 1200);
};
</script>
</body>
</html>"""
