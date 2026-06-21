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
exec "$PYTHON" pyinstaller/build.py --target all "$@"
