@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   OpenCareEyes Build Script
echo ============================================
echo.

:: Step 1: Install build dependencies
echo [1/4] Installing build dependencies...
pip install pyinstaller pillow -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo      Done.
echo.

:: Step 2: Install app dependencies
echo [2/4] Installing app dependencies...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: Failed to install app dependencies.
    pause
    exit /b 1
)
echo      Done.
echo.

:: Step 3: Generate icon
echo [3/4] Generating application icon...
python scripts\generate_icon.py
if errorlevel 1 (
    echo ERROR: Failed to generate icon.
    pause
    exit /b 1
)
echo      Done.
echo.

:: Step 4: Build with PyInstaller (single-file mode)
echo [4/4] Building single-file executable...
pyinstaller opencareyes.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)
echo      Done.
echo.

echo ============================================
echo   Build complete!
echo ============================================
echo.
echo   Output: dist\OpenCareEyes.exe
echo.
echo   Double-click OpenCareEyes.exe to run!
echo.
pause
