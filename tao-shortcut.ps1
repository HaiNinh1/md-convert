# Tao shortcut mo thang giao dien md-convert bang mot cu click.
#
# Vi sao phai lam shortcut thay vi mot file .pyw cho don gian: Python tren nhieu
# may Windows duoc cai ma khong dang ky file association, nen double-click .pyw
# khong chay gi ca. Shortcut tro thang vao pythonw.exe thi luon chay, khong phu
# thuoc vao association.
#
# Dung pythonw.exe chu khong phai python.exe de khong hien cua so console den
# sau lung app.
#
# Chay:  powershell -ExecutionPolicy Bypass -File tao-shortcut.ps1

$ErrorActionPreference = "Stop"
$duan = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Tim pythonw.exe ---
$pythonw = $null
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($python) {
    $thu = Join-Path (Split-Path -Parent $python) "pythonw.exe"
    if (Test-Path $thu) { $pythonw = $thu }
}
if (-not $pythonw) {
    foreach ($p in @(
        "C:\Program Files\Python313\pythonw.exe",
        "C:\Program Files\Python312\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
    )) { if (Test-Path $p) { $pythonw = $p; break } }
}
if (-not $pythonw) {
    Write-Host "  [LOI] Khong tim thay pythonw.exe. Cai Python tai python.org roi chay lai." -ForegroundColor Red
    exit 1
}

$icon = Join-Path $duan "assets\md-convert.ico"
$dich = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "md-convert.lnk"),
    (Join-Path $duan "md-convert.lnk")
)

$shell = New-Object -ComObject WScript.Shell
foreach ($d in $dich) {
    $sc = $shell.CreateShortcut($d)
    $sc.TargetPath       = $pythonw
    $sc.Arguments        = "-m mdconvert.gui"
    $sc.WorkingDirectory = $duan
    $sc.IconLocation     = "$icon,0"
    $sc.Description      = "Chuyen PDF, Word, Excel sang Markdown"
    $sc.Save()
    Write-Host "  Da tao: $d" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Xong. Nhan dup vao bieu tuong 'md-convert' tren Desktop de mo app." -ForegroundColor Cyan
