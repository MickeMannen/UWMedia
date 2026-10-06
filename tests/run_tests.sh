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

# Usage: tests/run_tests.sh [1-5] - with a choice, run it without the menu
# (for scripts and background runs); without one, ask (Enter = 1).
# Markers (pyproject.toml): plain `pytest` skips `render` and `release`; a
# later -m replaces that default.
choice_arg="$1"

# Print Selection Menu (only when asking)
if [ -z "$choice_arg" ]; then
    echo -e "\nSelect a test suite to run:"
    echo -e "  ${YELLOW}1)${NC} Fast: everything except media renders and release tests (default, ~1.5 min)"
    echo -e "  ${YELLOW}2)${NC} Full: fast + media render tests (~17 min, needs test_data/)"
    echo -e "  ${YELLOW}3)${NC} Release: pre-release validation on the full 4K media (release_test.py, ~5 min)"
    echo -e "  ${YELLOW}4)${NC} Everything: full + release (~22 min) - run this before a release"
    echo -e "  ${YELLOW}5)${NC} Exit"
fi

status=0
while true; do
    if [ -n "$choice_arg" ]; then
        choice="$choice_arg"
    else
        echo -n "Choose a test suite to run [1-5, Enter = 1]: "
        # No terminal to answer (e.g. started in the background): stop instead
        # of asking forever.
        read -r choice || { echo -e "\n${RED}No input; pass a choice: tests/run_tests.sh 1${NC}"; exit 2; }
        [ -z "$choice" ] && choice=1
    fi

    # Strip any trailing carriage return (\r or ^M) that IDEs like PyCharm send
    choice=$(echo "$choice" | tr -d '\r')

    case "$choice" in
        1)
            echo -e "\n${GREEN}[*] Running the fast suite...${NC}"
            pytest -v
            status=$?
            break
            ;;
        2)
            echo -e "\n${GREEN}[*] Running the full suite (with media renders)...${NC}"
            pytest -v -m "not release"
            status=$?
            break
            ;;
        3)
            echo -e "\n${GREEN}[*] Running pre-release validation tests...${NC}"
            pytest -v -m release
            status=$?
            break
            ;;
        4)
            echo -e "\n${GREEN}[*] Running every test...${NC}"
            pytest -v -m ""
            status=$?
            break
            ;;
        5)
            echo -e "${YELLOW}Exiting runner.${NC}"
            break
            ;;
        *)
            echo -e "${RED}Invalid selection '$choice'. Please choose a number between 1 and 5.${NC}"
            # An invalid argument would otherwise loop forever
            [ -n "$choice_arg" ] && exit 2
            ;;
    esac
done

# pytest's result, so callers can tell a failing run from a passing one
exit $status
