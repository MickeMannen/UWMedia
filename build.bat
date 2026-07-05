@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Using Python:
%PYTHON% --version
echo from %PYTHON%

echo Building all apps using PyInstaller...
%PYTHON% pyinstaller\build.py --target all %*
if errorlevel 1 exit /b %errorlevel%

set "RELEASE_DIR=D:\syncthing\AppReleases"

if exist "%RELEASE_DIR%\" (
    if exist "pyinstaller\dist" (
        echo Copying built executables from pyinstaller\dist to %RELEASE_DIR%...
        copy /Y "pyinstaller\dist\*" "%RELEASE_DIR%\"
        echo Successfully copied executables to %RELEASE_DIR%
    )
) else (
    echo Release directory %RELEASE_DIR% does not exist. Skipping copy.
)
