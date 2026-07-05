# Set script to stop on error
$ErrorActionPreference = "Stop"

# Navigate to the project root directory
$DIR = $PSScriptRoot
Set-Location -Path $DIR

# Determine Python executable
if (Test-Path ".venv\Scripts\python.exe") {
    $PYTHON = ".venv\Scripts\python.exe"
} elif (Test-Path "venv\Scripts\python.exe") {
    $PYTHON = "venv\Scripts\python.exe"
} else {
    $PYTHON = "python"
}

$pyVersion = & $PYTHON --version 2>&1
Write-Host "Using Python: $pyVersion from $PYTHON"

# Run the build script for all targets
Write-Host "Building all apps using PyInstaller..."
& $PYTHON pyinstaller/build.py --target all $args

# Copy created PyInstaller executables to releases folder if directory exists
$RELEASE_DIR = "D:\syncthing\AppReleases"

if (Test-Path -Path $RELEASE_DIR) {
    if (Test-Path -Path "pyinstaller\dist") {
        $distFiles = Get-ChildItem -Path "pyinstaller\dist" -File
        if ($distFiles.Count -gt 0) {
            Write-Host "Copying built executables from pyinstaller\dist to $RELEASE_DIR..."
            Copy-Item -Path "pyinstaller\dist\*" -Destination "$RELEASE_DIR\" -Force
            Write-Host "Successfully copied executables to $RELEASE_DIR"
        }
    }
} else {
    Write-Host "Release directory $RELEASE_DIR does not exist. Skipping copy."
}
