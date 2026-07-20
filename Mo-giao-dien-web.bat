@echo off
rem ---------------------------------------------------------------------------
rem  Mo giao dien web cua md-convert.
rem
rem  Nhan dup vao file nay -> may chu chay o localhost va trinh duyet tu mo.
rem
rem  LUU Y CHO NGUOI SUA FILE NAY: file .bat BAT BUOC dung xuong dong CRLF.
rem  Neu luu bang trinh soan thao ghi LF kieu Unix, cmd.exe se phan tich sai ca
rem  file va bao loi vo nghia kieu 'errorlevel' is not recognized.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal

set "DUAN=%~dp0"
set "PYTHONPATH=%DUAN%"

set "PY=python"
where python >nul 2>&1 || set "PY=py"
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [LOI] Khong tim thay Python tren may nay.
    echo   Cai tai: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

%PY% -c "import flask, spylls" 2>nul
if errorlevel 1 (
    echo.
    echo   Lan dau chay: dang cai thu vien can thiet...
    echo.
    %PY% -m pip install -e "%DUAN%"
    if errorlevel 1 (
        echo.
        echo   [LOI] Cai that bai. Xem thong bao loi ben tren.
        pause
        exit /b 1
    )
)

cls
echo.
echo  ==============================================================
echo    md-convert  -  giao dien web
echo  ==============================================================
echo.
echo   Trinh duyet se tu mo sau vai giay.
echo   Neu khong, hay vao:  http://127.0.0.1:5000
echo.
echo   DUNG DONG CUA SO NAY trong luc dang dung app.
echo   Xong viec thi nhan Ctrl+C hoac dong cua so nay.
echo.

%PY% -m mdconvert.web

echo.
echo   Da dung.
pause
endlocal
