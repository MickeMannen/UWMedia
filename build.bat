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

echo Building UWMedia with Briefcase...
%PYTHON% -m briefcase build windows -a uwmedia-terminal
if errorlevel 1 exit /b %errorlevel%
%PYTHON% -m briefcase package windows -a uwmedia-terminal --adhoc-sign %*
if errorlevel 1 exit /b %errorlevel%

set "RELEASE_DIR=D:\syncthing\AppReleases"

if exist "%RELEASE_DIR%\" (
    if exist "dist" (
        echo Copying built package from dist to %RELEASE_DIR%...
        copy /Y "dist\*" "%RELEASE_DIR%\"
        echo Successfully copied package to %RELEASE_DIR%
    )
) else (
    echo Release directory %RELEASE_DIR% does not exist. Skipping copy.
)
