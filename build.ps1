# Set script to stop on error
$ErrorActionPreference = "Stop"

# Navigate to the project root directory
$DIR = $PSScriptRoot
Set-Location -Path $DIR

# Determine Python executable
if (Test-Path ".venv\Scripts\python.exe") {
    $PYTHON = ".venv\Scripts\python.exe"
} elseif (Test-Path "venv\Scripts\python.exe") {
    $PYTHON = "venv\Scripts\python.exe"
} else {
    $PYTHON = "python"
}

$pyVersion = & $PYTHON --version 2>&1
Write-Host "Using Python: $pyVersion from $PYTHON"

# Build and package the UWMedia Terminal app (GUI + CLI in one) with Briefcase.
Write-Host "Building UWMedia with Briefcase..."
& $PYTHON -m briefcase build windows -a uwmedia-terminal
& $PYTHON -m briefcase package windows -a uwmedia-terminal --adhoc-sign $args

# Copy the packaged installer to the releases folder if it exists
$RELEASE_DIR = "D:\syncthing\AppReleases"

if (Test-Path -Path $RELEASE_DIR) {
    if (Test-Path -Path "dist") {
        $distFiles = Get-ChildItem -Path "dist" -File
        if ($distFiles.Count -gt 0) {
            Write-Host "Copying built package from dist to $RELEASE_DIR..."
            Copy-Item -Path "dist\*" -Destination "$RELEASE_DIR\" -Force
            Write-Host "Successfully copied package to $RELEASE_DIR"
        }
    }
} else {
    Write-Host "Release directory $RELEASE_DIR does not exist. Skipping copy."
}
