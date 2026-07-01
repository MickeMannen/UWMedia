#!/bin/bash

# Colorful output markers
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}         UWMedia Test Suite Execution Runner        ${NC}"
echo -e "${CYAN}====================================================${NC}"

# Navigate to the root directory if we are inside tests/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

# Automatically activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Print Selection Menu
echo -e "\nSelect a test suite to run:"
echo -e "  ${YELLOW}1)${NC} Run ALL tests (Unit tests + Pre-release tests)"
echo -e "  ${YELLOW}2)${NC} Run CLI Argument Unit Tests (Color, Legacy, Convert, Render Log, Video Log)"
echo -e "  ${YELLOW}3)${NC} Run Parser & Utility Unit Tests (Garmin, UDDF, Subsurface, Metadata, HUD)"
echo -e "  ${YELLOW}4)${NC} Run Pre-release Validation Suite (release_test.py)"
echo -e "  ${YELLOW}5)${NC} Exit"

while true; do
    echo -n "Choose a test suite to run [1-5]: "
    read -r choice
    
    # Strip any trailing carriage return (\r or ^M) that IDEs like PyCharm send
    choice=$(echo "$choice" | tr -d '\r')

    case "$choice" in
        1)
            echo -e "\n${GREEN}[*] Running all tests in the codebase...${NC}"
            PYTHONPATH=. pytest -v
            break
            ;;
        2)
            echo -e "\n${GREEN}[*] Running CLI argument unit tests...${NC}"
            PYTHONPATH=. pytest \
                tests/test_color.py \
                tests/test_color_legacy.py \
                tests/test_convert.py \
                tests/test_render_log.py \
                tests/test_render_video_log.py -v
            break
            ;;
        3)
            echo -e "\n${GREEN}[*] Running parser and utility unit tests...${NC}"
            PYTHONPATH=. pytest \
                tests/test_garmin.py \
                tests/test_uddf.py \
                tests/test_subsurface.py \
                tests/test_metadata.py \
                tests/test_hud_manager.py \
                tests/test_hud_renderer.py \
                tests/test_hud_rules.py \
                tests/test_models.py -v
            break
            ;;
        4)
            echo -e "\n${GREEN}[*] Running pre-release validation tests...${NC}"
            PYTHONPATH=. pytest tests/release_test.py -v
            break
            ;;
        5)
            echo -e "${YELLOW}Exiting runner.${NC}"
            break
            ;;
        *)
            echo -e "${RED}Invalid selection '$choice'. Please choose a number between 1 and 5.${NC}"
            ;;
    esac
done
