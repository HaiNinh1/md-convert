@echo off
rem ---------------------------------------------------------------------------
rem  md-convert — chuyen PDF / Word / Excel sang Markdown.
rem
rem  Cach dung:
rem    - Keo tha file hoac thu muc vao file .bat nay
rem    - Hoac nhan dup, roi dan duong dan thu muc vao
rem
rem  LUU Y CHO NGUOI SUA FILE NAY: file .bat BAT BUOC dung xuong dong CRLF.
rem  Neu luu bang trinh soan thao ghi LF kieu Unix, cmd.exe se phan tich sai ca
rem  file va bao loi vo nghia kieu 'errorlevel' is not recognized.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal

set "DUAN=%~dp0"
set "RA=%DUAN%out"
set "PYTHONPATH=%DUAN%"

rem --- Tim Python ---
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

cls
echo.
echo  ==============================================================
echo    md-convert  -  chuyen PDF / Word / Excel sang Markdown
echo  ==============================================================
echo.

rem --- Co file keo tha vao thi chuyen luon ---
if not "%~1"=="" goto :chay_voi_tham_so

rem --- Khong co thi hoi duong dan ---
echo   Keo tha file/thu muc vao file .bat nay, hoac dan duong dan vao day.
echo   Vi du:  D:\Tai lieu\Hop dong
echo.
set "NGUON="
set /p "NGUON=  Duong dan: "
if not defined NGUON goto :khong_nhap
rem Bo dau nhay kep neu nguoi dung dan duong dan co san nhay
set NGUON=%NGUON:"=%
if not exist "%NGUON%" (
    echo.
    echo   [LOI] Khong tim thay: %NGUON%
    echo.
    pause
    exit /b 1
)
echo.
%PY% -m mdconvert convert "%NGUON%" -r -o "%RA%"
goto :ket_thuc

:chay_voi_tham_so
%PY% -m mdconvert convert %* -r -o "%RA%"
goto :ket_thuc

:khong_nhap
echo.
echo   Chua nhap gi ca.
echo.
pause
exit /b 0

:ket_thuc
echo.
choice /c yn /n /m "  Mo thu muc ket qua? (y/n) "
if not errorlevel 2 start "" "%RA%"
echo.
endlocal
