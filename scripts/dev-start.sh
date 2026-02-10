#!/bin/bash
# Dhruva Development Startup Script
#
# This script provides easy startup of Dhruva in different operational modes.
# Mode is detected from the first argument or DHRUVA_MODE environment variable.
#
# Usage:
#   ./scripts/dev-start.sh [lite|standard]
#   DHRUVA_MODE=lite ./scripts/dev-start.sh
#   ./scripts/dev-start.sh          # defaults to lite mode

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default mode
MODE="${1:-${DHRUVA_MODE:-lite}}"

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to validate mode
validate_mode() {
    local mode="$1"
    if [[ "$mode" != "lite" && "$mode" != "standard" ]]; then
        print_error "Invalid mode: $mode"
        echo "Valid modes: lite, standard"
        exit 1
    fi
}

# Function to show mode banner
show_banner() {
    local mode="$1"

    if [[ "$mode" == "lite" ]]; then
        echo ""
        echo "╔═══════════════════════════════════════════════════════════════════╗"
        echo "║                                                                   ║"
        echo "║   🦀 Dhruva Lite Mode - Development & Testing                    ║"
        echo "║                                                                   ║"
        echo "║   ✓ Zero configuration required                                  ║"
        echo "║   ✓ Local storage in ~/.local/share/dhruva/                      ║"
        echo "║   ✓ Host: 127.0.0.1:8683                                         ║"
        echo "║   ✓ Ideal for development and testing                            ║"
        echo "║                                                                   ║"
        echo "╚═══════════════════════════════════════════════════════════════════╝"
        echo ""
    else
        echo ""
        echo "╔═══════════════════════════════════════════════════════════════════╗"
        echo "║                                                                   ║"
        echo "║   🦀 Dhruva Standard Mode - Production Ready                     ║"
        echo "║                                                                   ║"
        echo "║   ✓ Full configuration control                                   ║"
        echo "║   ✓ Configurable storage backends                                ║"
        echo "║   ✓ Host: 0.0.0.0:8683                                           ║"
        echo "║   ✓ Ideal for production deployments                             ║"
        echo "║                                                                   ║"
        echo "╚═══════════════════════════════════════════════════════════════════╝"
        echo ""
    fi
}

# Function to check prerequisites
check_prerequisites() {
    local mode="$1"

    print_info "Checking prerequisites..."

    # Check Python
    if ! command -v python &> /dev/null; then
        print_error "Python is not installed or not in PATH"
        exit 1
    fi

    # Check if dhruva is installed
    if ! python -c "import dhruva" 2>/dev/null; then
        print_error "Dhruva is not installed"
        echo "Install with: pip install -e \"$PROJECT_DIR\""
        exit 1
    fi

    # Check if dhruva-mcp CLI is available
    if ! command -v dhruva-mcp &> /dev/null; then
        print_warning "dhruva-mcp CLI not found, using python -m dhruva.cli"
    fi

    # Mode-specific checks
    if [[ "$mode" == "standard" ]]; then
        # Check if config file exists
        if [[ ! -f "$PROJECT_DIR/settings/standard.yaml" ]]; then
            print_warning "Standard mode config not found, will use defaults"
        fi
    fi

    print_success "Prerequisites check passed"
}

# Function to setup environment
setup_environment() {
    local mode="$1"

    print_info "Setting up $mode mode environment..."

    # Set mode environment variable
    export DHRUVA_MODE="$mode"

    # Create storage directory for lite mode
    if [[ "$mode" == "lite" ]]; then
        STORAGE_DIR="$HOME/.local/share/dhruva"
        if [[ ! -d "$STORAGE_DIR" ]]; then
            print_info "Creating storage directory: $STORAGE_DIR"
            mkdir -p "$STORAGE_DIR"
        fi
    fi

    print_success "Environment setup complete"
}

# Function to start Dhruva
start_dhruva() {
    local mode="$1"

    print_info "Starting Dhruva in $mode mode..."
    echo ""

    # Change to project directory
    cd "$PROJECT_DIR"

    # Start Dhruva MCP server
    if command -v dhruva-mcp &> /dev/null; then
        exec dhruva-mcp start
    else
        exec python -m dhruva.cli start
    fi
}

# Main execution
main() {
    # Validate mode
    validate_mode "$MODE"

    # Show banner
    show_banner "$MODE"

    # Check prerequisites
    check_prerequisites "$MODE"

    # Setup environment
    setup_environment "$MODE"

    # Start Dhruva
    start_dhruva "$MODE"
}

# Run main function
main "$@"
