#!/bin/bash
# Set script to exit on error
set -e

# Determine the absolute directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Navigate to the project root directory
cd "$DIR"

# Determine Python executable
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
else
    PYTHON="python3"
fi

echo "Using Python: $($PYTHON --version 2>&1) from $PYTHON"

# Run the build script for all targets
echo "Building all apps using PyInstaller..."
"$PYTHON" pyinstaller/build.py --target all "$@"

# Copy created PyInstaller onefile executables to releases folder if directory exists
RELEASE_DIR="/Users/mikael/syncthing/AppReleases"

if [ -d "$RELEASE_DIR" ]; then
    if [ -d "pyinstaller/dist" ] && [ "$(ls -A pyinstaller/dist 2>/dev/null)" ]; then
        echo "Copying built executables from pyinstaller/dist to $RELEASE_DIR..."
        cp -f pyinstaller/dist/* "$RELEASE_DIR/"
        echo "Successfully copied executables to $RELEASE_DIR"
    fi
else
    echo "Release directory $RELEASE_DIR does not exist. Skipping copy."
fi
