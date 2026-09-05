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

# Build and package the UWMedia app (GUI + CLI in one) with Briefcase.
# --adhoc-sign produces an unsigned .app/.dmg - fine for personal use and
# GitHub Releases, but macOS Gatekeeper will flag it as from an unidentified
# developer (right-click > Open on first launch) since there's no paid
# Apple Developer ID configured.
echo "Building UWMedia with Briefcase..."
"$PYTHON" -m briefcase build macOS
"$PYTHON" -m briefcase package macOS --adhoc-sign "$@"

# Copy the packaged app/installer to the releases folder if it exists
RELEASE_DIR="/Users/mikael/syncthing/AppReleases"

if [ -d "$RELEASE_DIR" ]; then
    if [ -d "dist" ] && [ "$(ls -A dist 2>/dev/null)" ]; then
        echo "Copying built package from dist to $RELEASE_DIR..."
        cp -f dist/* "$RELEASE_DIR/"
        echo "Successfully copied package to $RELEASE_DIR"
    fi
else
    echo "Release directory $RELEASE_DIR does not exist. Skipping copy."
fi
