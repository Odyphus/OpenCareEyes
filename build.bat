@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined PYTHON set "PYTHON=python"
set "EXE_ONLY=0"
if /i "%~1"=="--exe-only" set "EXE_ONLY=1"
set "BUILT_INSTALLER=0"
set "BUILT_WINGET=0"

echo [1/6] Installing OpenCareEyes and build dependencies...
"%PYTHON%" -m pip install -e ".[build]"
if errorlevel 1 goto :error

if not exist "build" mkdir "build"
"%PYTHON%" -c "from importlib.metadata import version; print(version('opencareyes'))" > "build\project-version.txt"
if errorlevel 1 goto :error
set /p APP_VERSION=<"build\project-version.txt"
if not defined APP_VERSION (
    echo ERROR: Could not read the project version from pyproject.toml.
    exit /b 1
)
echo       Version: %APP_VERSION%
set "INSTALLER_ARTIFACT=installer_output\OpenCareEyes_Setup_%APP_VERSION%.exe"
set "WINGET_ARCHIVE=OpenCareEyes_WinGet_%APP_VERSION%.zip"

if "%EXE_ONLY%"=="0" (
    if exist "%INSTALLER_ARTIFACT%" del /q "%INSTALLER_ARTIFACT%"
    if exist "%WINGET_ARCHIVE%" del /q "%WINGET_ARCHIVE%"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$target = [IO.Path]::GetFullPath((Join-Path $PWD 'winget_output')); $root = [IO.Path]::GetFullPath($PWD); if (-not $target.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe WinGet output path' }; if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }"
    if errorlevel 1 goto :error
)

echo [2/6] Generating the multi-size application icon...
"%PYTHON%" scripts\generate_icon.py
if errorlevel 1 goto :error

echo [3/6] Building portable single-file executable...
"%PYTHON%" -m PyInstaller --noconfirm --clean opencareyes.spec
if errorlevel 1 goto :error
if not exist "dist\OpenCareEyes.exe" (
    echo ERROR: dist\OpenCareEyes.exe was not created.
    exit /b 1
)
"%PYTHON%" -m PyInstaller.utils.cliutils.archive_viewer -l "dist\OpenCareEyes.exe" > "build\archive-list.txt"
if errorlevel 1 goto :error
findstr /i /c:"direct_url.json" "build\archive-list.txt" >nul
if not errorlevel 1 (
    echo ERROR: The executable contains editable-install metadata with a local build path.
    exit /b 1
)

echo [4/6] Building installer when Inno Setup 6 is available...
if "%EXE_ONLY%"=="1" goto :checksum

set "ISCC="
for %%I in (ISCC.exe) do set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo       Inno Setup 6 was not found; installer build skipped.
    echo       Install Inno Setup and run build.bat again, or use --exe-only.
    goto :checksum
)

"%ISCC%" /DMyAppVersion=%APP_VERSION% installer.iss
if errorlevel 1 goto :error
if not exist "%INSTALLER_ARTIFACT%" (
    echo ERROR: %INSTALLER_ARTIFACT% was not created.
    exit /b 1
)
set "BUILT_INSTALLER=1"

:checksum
echo [5/6] Generating version-pinned WinGet manifests when an installer exists...
if "%BUILT_INSTALLER%"=="1" (
    "%PYTHON%" scripts\generate_winget_manifest.py "%INSTALLER_ARTIFACT%" --version "%APP_VERSION%"
    if errorlevel 1 goto :error
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'winget_output\manifests' -DestinationPath '%WINGET_ARCHIVE%' -Force"
    if errorlevel 1 goto :error
    set "BUILT_WINGET=1"
) else (
    echo       No installer was produced in this run; WinGet generation skipped.
)

echo [6/6] Writing SHA-256 checksums...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$files = @('dist\OpenCareEyes.exe', 'THIRD_PARTY_NOTICES.md'); if ('%BUILT_INSTALLER%' -eq '1') { $files += '%INSTALLER_ARTIFACT%' }; if ('%BUILT_WINGET%' -eq '1') { $files += '%WINGET_ARCHIVE%' }; $lines = $files | ForEach-Object { $hash = (Get-FileHash -Algorithm SHA256 $_).Hash.ToLowerInvariant(); '{0}  {1}' -f $hash, (Split-Path -Leaf $_) }; [IO.File]::WriteAllLines((Join-Path $PWD 'SHA256SUMS.txt'), $lines, [Text.UTF8Encoding]::new($false))"
if errorlevel 1 goto :error

echo.
echo Build complete.
echo   Portable:  dist\OpenCareEyes.exe
if "%BUILT_INSTALLER%"=="1" echo   Installer: %INSTALLER_ARTIFACT%
if "%BUILT_WINGET%"=="1" echo   WinGet:    %WINGET_ARCHIVE%
echo   Checksums: SHA256SUMS.txt
exit /b 0

:error
echo.
echo ERROR: Build failed.
exit /b 1
