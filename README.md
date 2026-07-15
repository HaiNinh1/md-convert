# md-convert

Chuyển **PDF, PDF scan, Word, Excel** sang **Markdown**. Chạy offline 100%, không gọi API trả phí nào.

Không dùng AI để "hiểu" tài liệu. Cấu trúc được suy ra bằng **luật và thống kê hình học** từ toạ độ, cỡ chữ và font. Chỉ bản scan mới cần OCR — và OCR đó cũng chạy local, miễn phí.

## Cài đặt

```bash
pip install -e .

# Chỉ cần nếu phải xử lý PDF scan:
winget install --id tesseract-ocr.tesseract
```

`pip install -e .` là cách cài đúng, đừng dùng `pip install -r requirements.txt`. Lý do: không cài như package thì `python -m mdconvert` **chỉ chạy được khi bạn đang đứng trong thư mục dự án**, ra ngoài là báo `No module named mdconvert`. Cờ `-e` giữ liên kết tới mã nguồn nên sửa code là có hiệu lực ngay, không phải cài lại.

## Dùng

**Cách dễ nhất — kéo thả:** kéo file PDF/Word (hoặc cả thư mục) thả vào `Chuyen-doi.bat`. Kết quả ra thư mục `out` ngay cạnh.

**Dòng lệnh** (chạy được từ bất kỳ thư mục nào sau khi `pip install -e .`):

```bash
# Một file
python -m mdconvert convert bao-cao.pdf -o out

# Cả thư mục, kể cả thư mục con
python -m mdconvert convert tai-lieu/ -r -o out

# Thả file vào thư mục là tự chuyển
python -m mdconvert watch hop-thu-den/ -o out
```

> Lệnh `md-convert` gọi thẳng sẽ báo *command not found*, vì pip đặt nó vào
> `%APPDATA%\Python\Python313\Scripts` — thư mục không nằm trong PATH. Dùng
> `python -m mdconvert` hoặc `Chuyen-doi.bat` là xong, khỏi phải sửa PATH.

Các cờ hay dùng:

| Cờ | Ý nghĩa |
|---|---|
| `-o, --out` | thư mục xuất (mặc định `out`) |
| `-r, --recursive` | quét cả thư mục con |
| `--lang vie+eng` | ngôn ngữ OCR; mặc định `vie`. Dùng `vie+eng` cho tài liệu lẫn tiếng Anh |
| `--dpi 400` | tăng độ phân giải OCR cho bản scan mờ (mặc định 300) |
| `--force-ocr` | ép OCR kể cả khi PDF có sẵn lớp text |
| `--no-images` | không tách ảnh ra thư mục assets |
| `--keep-headers` | giữ lại header/footer lặp lại giữa các trang |
| `-v, --verbose` | in tiến độ từng trang |

## Hoạt động thế nào

```
                    ┌─ có lớp text? ─┐
   PDF ─────────────┤                ├── PyMuPDF: text + toạ độ + font
                    └─ không ────────┴── Tesseract OCR ──┐
                                                          │
                            cả hai đều cho ra Span/Line ──┤
                                                          ▼
                                            ┌─────────────────────────┐
   DOCX ── mammoth ── HTML ── markdownify ──┤  Tầng phân tích layout  │
                                            │  (luật, không AI)       │
   XLSX ── openpyxl ────────────────────────┤                         │
                                            └───────────┬─────────────┘
                                                        ▼
                                                   Markdown
```

**Tự động nhận biết PDF scan**: đếm ký tự `page.get_text()` trả về. Dưới 50 ký tự/trang thì coi là scan và chuyển sang OCR. Quyết định theo từng trang, nên file lẫn lộn trang số và trang scan vẫn xử lý đúng.

**Điểm mấu chốt**: cả hai nhánh đều quy về cùng kiểu `Span`/`Line` (`model.py`). Nhờ vậy tầng phân tích layout chỉ viết một lần, không phải tách đôi theo nguồn.

### Tầng phân tích layout (`layout.py`) — trái tim của dự án

| Nhận ra | Bằng cách nào |
|---|---|
| Cỡ chữ thân bài | Cỡ chiếm nhiều **ký tự** nhất (không phải nhiều dòng — trang bìa toàn tiêu đề sẽ đánh lừa) |
| Tiêu đề | Gom các cỡ lớn hơn thân bài ≥8% thành cụm, xếp hạng giảm dần → `#`..`######` |
| Tiêu đề chỉ in đậm | Dòng in đậm, ngắn, đứng riêng, không kết câu — nhiều tài liệu VN đánh tiêu đề kiểu này |
| Cấp tiêu đề | Ưu tiên cách **đánh số**: "2.1" chắc chắn sâu hơn "2" một cấp, không cần đo cỡ chữ |
| Đoạn văn | Khoảng cách dọc vượt giãn dòng thường (đo bằng **mode**, chỉ trên dòng cùng cỡ thân bài) |
| Danh sách | Regex ký hiệu + cấp lồng nhau lấy từ toạ độ x |
| Bảng (PDF số) | `find_tables()` của PyMuPDF — dựa trên đường kẻ thật |
| Bảng (scan) | Các mốc x thẳng cột qua ≥3 dòng liên tiếp |
| Cột | Dải trắng dọc ở khoảng giữa trang |
| Header/footer | Nội dung lặp lại ở đầu/cuối trên ≥60% số trang |

### Word thì dễ hơn PDF nhiều

`.docx` là file ZIP chứa XML, trong đó Word **ghi thẳng** `<w:pStyle w:val="Heading1"/>`, `<w:b/>`, `<w:tbl>`. Không phải đoán gì cả — chỉ việc đọc. Đó là lý do nhánh Word không đi qua tầng layout.

`.doc` đời cũ (Word 97-2003) là định dạng nhị phân OLE2, không phải ZIP. Chương trình phát hiện bằng chữ ký file và báo lệnh LibreOffice để convert, thay vì đổ stack trace.

## Những cái bẫy đã gặp (và đã có test khoá)

Ghi lại để người sau đừng "dọn dẹp" mấy con số này rồi làm hỏng:

- **Model của OCR-Offline không đọc được tiếng Việt.** `latin_PP-OCRv3_rec_infer.onnx` đi kèm `latin_dict.txt` chỉ có 186 ký tự và **thiếu 53/74 ký tự riêng của tiếng Việt**. Nó là model Latin châu Âu (é, ö, ä). "Báo cáo Kỹ thuật" ra "Bao cao Ky thuat" — không phải đoán sai, mà là ký tự đó không tồn tại trong vốn từ đầu ra. Vì thế dự án dùng Tesseract chứ không phải RapidOCR.

- **Chiều cao khung OCR không đo được cỡ chữ.** Nó đo vệt mực: dòng không có chữ thò lên/thụt xuống thì khung lùn. Đo thật: cùng 10pt mà chênh 1.46×, còn tiêu đề 15pt cho chiều cao **bằng** thân bài. Phải dùng **bề rộng trung bình mỗi ký tự** (nhiễu chỉ 1.05×).

- **Đo cỡ chữ phải tính trên cả dòng, không lọc từng từ.** Tiếng Việt đơn âm, từ chỉ 2-3 ký tự, nên lọc "từ ≥4 ký tự" làm cả dòng chỉ còn 1 từ lọt lưới → nhiễu tới mức thân bài vọt lên thành tiêu đề.

- **Thiếu cờ `--dpi`, Tesseract âm thầm vứt bảng.** Không biết độ phân giải, nó đoán sai rồi bỏ luôn vùng bảng có đường kẻ: 81 từ thay vì 100, không một cảnh báo. Gán `img.info["dpi"]` vô dụng vì pytesseract không truyền tiếp.

- **Font Times New Roman phá text extraction.** Đây là font chuẩn của văn bản hành chính VN, và PyMuPDF trích từ nó ra: dấu cách thường → **U+00A0 NBSP**, dấu trừ thường → **U+00AD SOFT HYPHEN**. Mắt thường không thấy gì bất thường. NBSP phá grep và copy-paste; soft hyphen làm cả danh sách bị đọc thành đoạn văn.

- **`HEADING_MAX_SHARE` đừng siết.** Từng để 0.12 và tài liệu 1 trang hỏng ngay: tiêu đề 15pt chiếm 12.3% ký tự (bình thường với văn bản ngắn) nên bị loại rồi tụt xuống thành danh sách. Tài liệu càng ngắn, tiêu đề càng chiếm tỉ lệ cao.

- **Ngưỡng tách đoạn phải đo trên dòng cùng cỡ thân bài.** Gộp cả khoảng cách trước tiêu đề và giữa ô bảng vào thì trung vị bị kéo lên, ngưỡng cao đến mức không đoạn nào tách được.

- **`Chuyen-doi.bat` bắt buộc dùng xuống dòng CRLF.** Đa số trình soạn thảo và công cụ sinh file mặc định ghi LF kiểu Unix; cmd.exe gặp LF thuần là phân tích sai cả file và báo những lỗi vô nghĩa như `'errorlevel' is not recognized`. Sửa file .bat xong nhớ kiểm tra lại xuống dòng.

- **Tesseract trả về từng TỪ, không phải từng vùng chữ.** Tầng dò bảng coi mỗi span là một ô, nên phải gộp từ thành ô theo khoảng hở ngang trước — không thì dòng văn 14 từ thành hàng bảng 14 ô.

## Giới hạn đã biết

- **Tiêu đề 12pt trên bản scan**: chỉ cách thân bài 11pt khoảng 1.07×, trong khi nhiễu ước lượng của OCR là 1.05×. Quá sát, có thể bị bỏ sót. Tiêu đề cách thân bài từ 15pt trở lên (1.36×) thì chắc chắn nhận ra.
- **OCR không nhận biết chữ đậm/nghiêng**, nên bản scan mất định dạng inline. PDF số thì giữ đủ.
- **Tesseract còn nhầm dấu gần giống nhau**: "triển"→"triền", "Bảng chi"→"Báng chỉ". Khoảng 95% ký tự đúng trên bản scan sạch. Tăng `--dpi 400` giúp được với bản mờ.
- **Công thức toán, sơ đồ, chữ viết tay** không xử lý.
- **Giấy phép AGPL v3 lan sang mọi dự án dùng lại code này**, vì PyMuPDF là AGPL. Xem mục [Giấy phép](#giấy-phép) ở cuối để biết hệ quả cụ thể.

## Test

```bash
python -m pytest tests/ -q
```

Mỗi test ứng với một lỗi **đã thật sự xảy ra** khi dựng dự án, không phải lỗi giả định. File mẫu được sinh tự động ở lần chạy đầu. Test cần OCR sẽ tự bỏ qua nếu chưa cài Tesseract.

## Giấy phép

**AGPL-3.0-or-later** — xem file [LICENSE](LICENSE).

Dự án bắt buộc phải mang giấy phép này vì nó dùng **PyMuPDF**, vốn là AGPL v3, và
AGPL có tính lan truyền. Hệ quả cụ thể:

- Dùng cho cá nhân hoặc nội bộ công ty: thoải mái, không ràng buộc gì.
- Phân phối lại, hoặc chạy nó thành dịch vụ cho người khác dùng qua mạng: phải
  công khai mã nguồn (kể cả phần bạn sửa) dưới AGPL v3.

Nếu cần giấy phép dễ thở hơn (ví dụ MIT, để bán hoặc nhúng vào sản phẩm đóng),
phải thay PyMuPDF bằng `pdfplumber` + `pypdfium2` (MIT/BSD) và viết lại
`mdconvert/pdf.py`. Đánh đổi: khả năng dò bảng yếu hơn và chạy chậm hơn.
