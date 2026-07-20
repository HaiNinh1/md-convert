@echo off
rem ---------------------------------------------------------------------------
rem  Dong goi md-convert thanh ung dung .exe tu chay (PyInstaller).
rem  Nhan dup vao file nay. Ket qua nam o: dist\md-convert\md-convert.exe
rem
rem  LUU Y: file .bat BAT BUOC dung xuong dong CRLF (kieu Windows).
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal
set "DUAN=%~dp0"

set "PY=python"
where python >nul 2>&1 || set "PY=py"
%PY% --version >nul 2>&1 || (
    echo.
    echo   [LOI] Khong tim thay Python. Cai tai https://www.python.org/downloads/
    pause & exit /b 1
)

echo.
echo   Kiem tra thu vien can thiet...
%PY% -c "import PyInstaller" 2>nul || %PY% -m pip install pyinstaller
%PY% -c "import flask, spylls, fitz, PIL" 2>nul || %PY% -m pip install -e "%DUAN%"

echo.
echo   Dang dong goi... (mat vai phut)
echo.
%PY% -m PyInstaller "%DUAN%md-convert.spec" --noconfirm --clean
if errorlevel 1 (
    echo.
    echo   [LOI] Dong goi that bai. Xem thong bao loi ben tren.
    pause & exit /b 1
)

rem --- Chep Tesseract vao sau khi build (tesseract.exe + DLL, bo cong cu huan luyen) ---
rem  Lam o day thay vi trong .spec de PyInstaller khong keo trung DLL ra goc (~150MB thua).
set "TESSSRC=C:\Program Files\Tesseract-OCR"
if not exist "%TESSSRC%\tesseract.exe" set "TESSSRC=C:\Program Files (x86)\Tesseract-OCR"
set "TESSDST=%DUAN%dist\md-convert\_internal\tesseract"
if exist "%TESSSRC%\tesseract.exe" (
    echo   Chep Tesseract offline vao ung dung...
    if not exist "%TESSDST%" mkdir "%TESSDST%"
    copy /Y "%TESSSRC%\tesseract.exe" "%TESSDST%\" >nul
    copy /Y "%TESSSRC%\*.dll" "%TESSDST%\" >nul
) else (
    echo   [Chu y] Khong thay Tesseract tren may. Ban dong goi se CHI chay online.
)

echo.
echo  ==============================================================
echo    XONG. Ung dung da dong goi tai:
echo    %DUAN%dist\md-convert\
echo    File chay:  md-convert.exe
echo  ==============================================================
echo.
echo   Ban co the chep ca thu muc "md-convert" nay cho nguoi dung khac.
echo   Muon doi khoa OCR online: dat file ocrspace_key.txt canh md-convert.exe
echo.
pause
endlocal
