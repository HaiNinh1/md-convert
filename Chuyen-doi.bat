@echo off
rem ---------------------------------------------------------------------------
rem  md-convert — keo tha file PDF / Word vao file nay de chuyen sang Markdown.
rem
rem  chcp 65001 la BAT BUOC: console Windows mac dinh dung bang ma cp1252, khong
rem  in duoc tieng Viet. Thieu dong nay thi ten file co dau se hien ra thanh rac.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal

set "DUAN=%~dp0"
set "RA=%~dp0out"

rem Tim Python: thu 'python' truoc, khong co thi dung Python Launcher 'py'.
set "PY=python"
where python >nul 2>&1 || set "PY=py"
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [LOI] Khong tim thay Python tren may.
    echo   Cai tai: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

rem PYTHONPATH de chay duoc ke ca khi chua 'pip install -e .'
set "PYTHONPATH=%DUAN%"

if "%~1"=="" goto :khong_co_file

echo.
echo   Dang chuyen doi...
echo.
%PY% -m mdconvert convert %* -o "%RA%"
echo.
echo   ----------------------------------------------------------
echo   Ket qua nam trong: %RA%
echo   ----------------------------------------------------------
echo.
choice /c yn /n /m "  Mo thu muc ket qua? (y/n) "
if errorlevel 2 goto :xong
start "" "%RA%"
goto :xong

:khong_co_file
echo.
echo   ==========================================================
echo    md-convert  —  chuyen PDF / Word / Excel sang Markdown
echo   ==========================================================
echo.
echo   Cach dung: keo tha file (hoac ca thu muc) vao file .bat nay.
echo.
echo   Hoac chay tu dong lenh:
echo     python -m mdconvert convert tai-lieu.pdf -o out
echo     python -m mdconvert convert thu-muc\ -r -o out
echo     python -m mdconvert watch hop-thu-den\ -o out
echo.
pause
exit /b 0

:xong
endlocal
