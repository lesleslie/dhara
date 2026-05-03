#!/usr/bin/env bash
# dhara 5.0 Deployment Script
# Supports native Python, buildpack, and Kubernetes deployment

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERSION="${DHARA_VERSION:-5.0.0}"
REGISTRY="${DOCKER_REGISTRY:-ghcr.io}"
NAMESPACE="${KUBERNETES_NAMESPACE:-default}"
BUILDPACK_BUILDER="${BUILDPACK_BUILDER:-paketobuildpacks/builder:base}"

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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed. Please install Python 3.13+ first."
        exit 1
    fi
    local python_version=$(python3 --version | awk '{print $2}')
    log_info "Python is available: ${python_version}"
}

check_pip() {
    if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
        log_error "pip is not installed. Please install pip first."
        exit 1
    fi
    log_info "pip is available: $(pip --version 2>&1 || pip3 --version 2>&1)"
}

check_pack() {
    if ! command -v pack &> /dev/null; then
        log_error "pack CLI is not installed. Please install pack first."
        log_info "Install: https://buildpacks.io/docs/install-pack/"
        exit 1
    fi
    log_info "pack CLI is available: $(pack version)"
}

check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed. Please install kubectl first."
        exit 1
    fi
    log_info "kubectl is available: $(kubectl version --client --short 2>&1)"
}


# Native installation
install_native() {
    log_step "Installing dhara natively..."

    check_python
    check_pip

    cd "${PROJECT_ROOT}"

    # Install in editable mode for development
    if [ "${DEV:-false}" = "true" ]; then
        log_info "Installing in development mode..."
        pip install -e ".[dev]"
    else
        log_info "Installing in production mode..."
        pip install .
    fi

    log_info "dhara installed successfully"
    log_info "Run: dhara mcp --help"
}

install_from_wheel() {
    log_step "Building and installing from wheel..."

    check_python
    check_pip

    cd "${PROJECT_ROOT}"

    # Build wheel
    log_info "Building wheel package..."
    python3 -m pip install --upgrade build
    python3 -m build

    # Install wheel
    local wheel=$(ls dist/dhara-${VERSION}-*.whl 2>/dev/null | head -1)
    if [ -z "${wheel}" ]; then
        log_error "Failed to build wheel"
        exit 1
    fi

    log_info "Installing wheel: ${wheel}"
    pip install "${wheel}"

    log_info "dhara installed from wheel successfully"
}

run_server() {
    log_step "Starting dhara server..."

    check_python

    cd "${PROJECT_ROOT}"

    # Set defaults
    local host="${DHARA_HOST:-127.0.0.1}"
    local port="${DHARA_PORT:-2972}"
    local config="${DHARA_CONFIG:-deployment/config/production.yaml}"

    # Check if config exists
    if [ ! -f "${config}" ]; then
        log_warn "Config file not found: ${config}"
        log_info "Using default configuration"
        config=""
    fi

    log_info "Starting dhara server on ${host}:${port}..."

    # Start server
    if [ -n "${config}" ]; then
        DHARA_HOST="${host}" DHARA_PORT="${port}" DHARA_CONFIG="${config}" python3 -m dhara.mcp
    else
        DHARA_HOST="${host}" DHARA_PORT="${port}" python3 -m dhara.mcp
    fi
}

# Buildpack deployment
build_buildpack() {
    log_step "Building with Cloud Native Buildpacks..."

    check_pack

    cd "${PROJECT_ROOT}"

    local image_name="${REGISTRY}/dhara:${VERSION}"

    log_info "Building image: ${image_name}"
    log_info "Builder: ${BUILDPACK_BUILDER}"

    pack build "${image_name}" \
        --builder "${BUILDPACK_BUILDER}" \
        --env BP_PYTHON_VERSION="3.13" \
        --env BP_LIVE_RELOAD_ENABLED="false"

    # Tag as latest
    docker tag "${image_name}" "${REGISTRY}/dhara:latest"

    log_info "Buildpack image built successfully"
    log_info "Image: ${image_name}"
}

push_buildpack() {
    log_step "Pushing buildpack image..."

    local image_name="${REGISTRY}/dhara:${VERSION}"

    if ! docker images "${image_name}" --format "{{.Repository}}:{{.Tag}}" | grep -q "${image_name}"; then
        log_error "Image not found: ${image_name}"
        log_info "Run: $0 buildpack first"
        exit 1
    fi

    docker push "${image_name}"
    docker push "${REGISTRY}/dhara:latest"

    log_info "Image pushed successfully"
}

deploy_buildpack_local() {
    log_step "Deploying buildpack image locally..."

    local image_name="${REGISTRY}/dhara:${VERSION}"

    if ! docker images "${image_name}" --format "{{.Repository}}:{{.Tag}}" | grep -q "${image_name}"; then
        log_error "Image not found: ${image_name}"
        log_info "Run: $0 buildpack first"
        exit 1
    fi

    # Stop existing container
    if docker ps -a --format '{{.Names}}' | grep -q '^dhara-server$'; then
        log_info "Stopping existing container..."
        docker stop dhara-server 2>/dev/null || true
        docker rm dhara-server 2>/dev/null || true
    fi

    # Start new container
    log_info "Starting container from buildpack image..."
    docker run -d \
        --name dhara-server \
        --restart unless-stopped \
        -p 2972:2972 \
        -v dhara-data:/data \
        -e PORT=2972 \
        "${image_name}"

    log_info "dhara server started from buildpack image"
    log_info "Logs: docker logs -f dhara-server"
}


# Kubernetes deployment
deploy_kubernetes() {
    log_step "Deploying to Kubernetes..."

    check_kubectl

    local image_name="${REGISTRY}/dhara:${VERSION}"

    # Create namespace
    if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
        log_info "Creating namespace: ${NAMESPACE}"
        kubectl create namespace "${NAMESPACE}"
    fi

    # Create ConfigMap
    log_info "Creating ConfigMap..."
    kubectl create configmap dhara-config \
        --from-file="${PROJECT_ROOT}/deployment/config/production.yaml" \
        --namespace="${NAMESPACE}" \
        --dry-run=client -o yaml | kubectl apply -f -

    # Update deployment with image
    log_info "Applying deployment..."
    cat "${PROJECT_ROOT}/deployment/kubernetes/deployment.yaml" | \
        sed "s|IMAGE_PLACEHOLDER|${image_name}|g" | \
        envsubst | kubectl apply -f -

    # Apply service
    log_info "Applying service..."
    envsubst < "${PROJECT_ROOT}/deployment/kubernetes/service.yaml" | kubectl apply -f -

    # Wait for rollout
    log_info "Waiting for rollout..."
    kubectl rollout status deployment/dhara-server --namespace="${NAMESPACE}" --timeout=120s

    log_info "Deployed to Kubernetes successfully"
    log_info "Status: kubectl get pods -n ${NAMESPACE}"
    log_info "Logs: kubectl logs -f deployment/dhara-server -n ${NAMESPACE}"
}

# Development server
run_dev_server() {
    log_step "Starting development server..."

    check_python

    cd "${PROJECT_ROOT}"

    # Install in dev mode if not already
    if ! pip show dhara &> /dev/null; then
        log_info "Installing dhara in development mode..."
        pip install -e ".[dev]"
    fi

    # Run dev server
    log_info "Starting dev server with auto-reload..."
    DHARA_HOST="127.0.0.1" DHARA_PORT="2972" DHARA_CONFIG="deployment/config/development.yaml" python3 -m dhara.mcp
}

show_usage() {
    cat << EOF
Usage: $0 <command> [options]

Native Installation Commands:
    install              Install dhara natively with pip
    wheel                Build and install from wheel
    run                  Run dhara server natively
    dev                  Run development server with auto-reload

Buildpack Commands:
    buildpack            Build with Cloud Native Buildpacks
    push-buildpack       Push buildpack image to registry
    local-buildpack      Deploy buildpack image locally

Cloud Deployment Commands:
    kubernetes|k8s       Deploy to Kubernetes

Environment Variables:
    DHARA_VERSION        Version tag (default: 5.0.0)
    DHARA_HOST           Server host (default: 127.0.0.1)
    DHARA_PORT           Server port (default: 2972)
    DHARA_CONFIG         Config file path
    DOCKER_REGISTRY      Container registry (default: ghcr.io)
    KUBERNETES_NAMESPACE K8s namespace (default: default)
    BUILDPACK_BUILDER    Buildpack builder (default: paketobuildpacks/builder:base)
    DEV                  Enable dev mode (true/false)

Examples:
    # Install natively
    $0 install

    # Run development server
    $0 dev

    # Build with buildpacks and deploy locally
    $0 buildpack && $0 local-buildpack

    # Deploy to Kubernetes
    $0 buildpack && $0 kubernetes

EOF
}

main() {
    if [ $# -eq 0 ]; then
        show_usage
        exit 1
    fi

    local command="$1"
    shift

    case "${command}" in
        install)
            install_native
            ;;
        wheel)
            install_from_wheel
            ;;
        run)
            run_server "$@"
            ;;
        dev)
            run_dev_server
            ;;
        buildpack|build)
            build_buildpack
            ;;
        push-buildpack)
            push_buildpack
            ;;
        local-buildpack)
            deploy_buildpack_local
            ;;
        kubernetes|k8s)
            deploy_kubernetes
            ;;
        -h|--help|help)
            show_usage
            ;;
        *)
            log_error "Unknown command: ${command}"
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
