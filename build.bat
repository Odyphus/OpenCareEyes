@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined PYTHON set "PYTHON=python"

echo [1/5] Installing OpenCareEyes and build dependencies...
%PYTHON% -m pip install -e ".[build]"
if errorlevel 1 goto :error

for /f "usebackq delims=" %%V in (`%PYTHON% -c "from importlib.metadata import version; print(version('opencareyes'))"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo ERROR: Could not read the project version from pyproject.toml.
    exit /b 1
)
echo       Version: %APP_VERSION%

echo [2/5] Checking application icon...
if not exist "assets\icons\opencareyes.ico" (
    %PYTHON% scripts\generate_icon.py
    if errorlevel 1 goto :error
)

echo [3/5] Building portable single-file executable...
%PYTHON% -m PyInstaller --noconfirm --clean opencareyes.spec
if errorlevel 1 goto :error
if not exist "dist\OpenCareEyes.exe" (
    echo ERROR: dist\OpenCareEyes.exe was not created.
    exit /b 1
)

echo [4/5] Building installer when Inno Setup 6 is available...
if /i "%~1"=="--exe-only" goto :checksum

set "ISCC="
for %%I in (ISCC.exe) do set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo       Inno Setup 6 was not found; installer build skipped.
    echo       Install Inno Setup and run build.bat again, or use --exe-only.
    goto :checksum
)

"%ISCC%" /DMyAppVersion=%APP_VERSION% installer.iss
if errorlevel 1 goto :error

:checksum
echo [5/5] Writing SHA-256 checksums...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$files = @('dist\OpenCareEyes.exe'); $installer = 'installer_output\OpenCareEyes_Setup_%APP_VERSION%.exe'; if (Test-Path $installer) { $files += $installer }; $lines = $files | ForEach-Object { $hash = (Get-FileHash -Algorithm SHA256 $_).Hash.ToLowerInvariant(); '{0}  {1}' -f $hash, (Split-Path -Leaf $_) }; [IO.File]::WriteAllLines((Join-Path $PWD 'SHA256SUMS.txt'), $lines, [Text.UTF8Encoding]::new($false))"
if errorlevel 1 goto :error

echo.
echo Build complete.
echo   Portable:  dist\OpenCareEyes.exe
if exist "installer_output\OpenCareEyes_Setup_%APP_VERSION%.exe" echo   Installer: installer_output\OpenCareEyes_Setup_%APP_VERSION%.exe
echo   Checksums: SHA256SUMS.txt
exit /b 0

:error
echo.
echo ERROR: Build failed.
exit /b 1
