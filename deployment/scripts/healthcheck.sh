#!/usr/bin/env bash
# dhruva 5.0 Health Check Script
# Used by orchestrators (Kubernetes, Docker, systemd) to check service health

set -euo pipefail

# Configuration
HOST="${DHRUVA_HOST:-localhost}"
PORT="${DHRUVA_PORT:-2972}"
TIMEOUT="${HEALTH_CHECK_TIMEOUT:-5}"
ATTEMPTS="${HEALTH_CHECK_ATTEMPTS:-3}"
DELAY="${HEALTH_CHECK_DELAY:-2}"

# Colors for output (disable in non-interactive mode)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_tcp_connection() {
    local host="$1"
    local port="$2"
    local timeout="$3"

    # Try different methods for TCP connection check
    if command -v nc &> /dev/null; then
        # Use netcat if available
        nc -z -w "$timeout" "$host" "$port" 2>/dev/null
        return $?
    elif command -v timeout &> /dev/null; then
        # Use timeout + bash /dev/tcp
        timeout "$timeout" bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null
        return $?
    elif command -v python3 &> /dev/null; then
        # Use Python socket
        python3 -c "import socket; s=socket.socket(); s.settimeout(${timeout}); s.connect(('${host}', ${port})); s.close()" 2>/dev/null
        return $?
    else
        log_error "No suitable tool found for TCP connection check"
        return 1
    fi
}

check_dhruva_protocol() {
    local host="$1"
    local port="$2"
    local timeout="$3"

    # Basic protocol check: try to connect and see if server responds
    if command -v python3 &> /dev/null; then
        python3 -c "
import socket
import sys
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(${timeout})
    s.connect(('${host}', ${port}))
    # Try to read a byte (server should respond)
    s.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null
        return $?
    fi

    return 0  # If we can't check protocol, just rely on TCP check
}

perform_health_check() {
    local attempt=1

    while [ $attempt -le $ATTEMPTS ]; do
        log_info "Health check attempt $attempt/$ATTEMPTS..."

        if check_tcp_connection "$HOST" "$PORT" "$TIMEOUT"; then
            log_info "TCP connection successful"

            if check_dhruva_protocol "$HOST" "$PORT" "$TIMEOUT"; then
                log_info "Duru server is healthy"
                return 0
            else
                log_warn "Protocol check failed"
            fi
        else
            log_warn "TCP connection failed"
        fi

        if [ $attempt -lt $ATTEMPTS ]; then
            log_info "Waiting ${DELAY}s before next attempt..."
            sleep "$DELAY"
        fi

        attempt=$((attempt + 1))
    done

    log_error "Health check failed after $ATTEMPTS attempts"
    return 1
}

show_usage() {
    cat << EOF
Usage: $0 [options]

Options:
    -h, --host HOST        dhruva server host (default: localhost)
    -p, --port PORT        dhruva server port (default: 2972)
    -t, --timeout SECONDS  Connection timeout (default: 5)
    -a, --attempts NUM     Number of attempts (default: 3)
    -d, --delay SECONDS    Delay between attempts (default: 2)
    --help                 Show this help message

Environment Variables:
    DHRUVA_HOST             Server host
    DHRUVA_PORT             Server port
    HEALTH_CHECK_TIMEOUT   Connection timeout
    HEALTH_CHECK_ATTEMPTS  Number of attempts
    HEALTH_CHECK_DELAY     Delay between attempts

Exit Codes:
    0                      Health check passed
    1                      Health check failed
    2                      Invalid arguments

Examples:
    # Check default localhost:2972
    $0

    # Check remote host
    $0 --host dhruva.example.com --port 2972

    # With custom timeout and attempts
    $0 --timeout 10 --attempts 5

EOF
}

main() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--host)
                HOST="$2"
                shift 2
                ;;
            -p|--port)
                PORT="$2"
                shift 2
                ;;
            -t|--timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            -a|--attempts)
                ATTEMPTS="$2"
                shift 2
                ;;
            -d|--delay)
                DELAY="$2"
                shift 2
                ;;
            --help)
                show_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 2
                ;;
        esac
    done

    # Validate inputs
    if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        log_error "Invalid port: $PORT (must be 1-65535)"
        exit 2
    fi

    if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || [ "$TIMEOUT" -lt 1 ]; then
        log_error "Invalid timeout: $TIMEOUT (must be positive integer)"
        exit 2
    fi

    if ! [[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || [ "$ATTEMPTS" -lt 1 ]; then
        log_error "Invalid attempts: $ATTEMPTS (must be positive integer)"
        exit 2
    fi

    # Perform health check
    perform_health_check
    exit $?
}

main "$@"
