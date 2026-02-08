# dhruva 5.0 Deployment Guide

This guide covers deploying dhruva 5.0 using native Python installation and Cloud Native Buildpacks.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Native Installation](#native-installation)
- [Buildpack Deployment](#buildpack-deployment)
- [Cloud Platform Deployment](#cloud-platform-deployment)
- [Configuration](#configuration)
- [Health Checks](#health-checks)
- [Monitoring](#monitoring)
- [Backup and Restore](#backup-and-restore)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### For Native Installation
- Python 3.13 or later
- pip (Python package installer)
- Virtual environment (recommended)

### For Buildpack Deployment
- [pack CLI](https://buildpacks.io/docs/install-pack/) (for local builds)
- Docker daemon (for running buildpack images)
- Container registry (for production deployment)

### For Kubernetes Deployment
- kubectl configured for your cluster
- Container registry access

## Native Installation

### Development Installation

Install dhruva in editable mode for development:

```bash
# Clone repository
git clone https://github.com/lesleslie/dhruva.git
cd dhruva

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
./deployment/scripts/deploy.sh install

# Or manually:
pip install -e ".[dev]"
```

### Production Installation

Install dhruva from wheel or directly:

```bash
# Build and install from wheel
./deployment/scripts/deploy.sh wheel

# Or install directly from PyPI (when published)
pip install dhruva
```

### Running the Server

Start the dhruva server:

```bash
# Using deployment script
./deployment/scripts/deploy.sh run

# Or directly
python -m dhruva.cli.server --host=127.0.0.1 --port=2972

# With custom configuration
python -m dhruva.cli.server --config=deployment/config/production.yaml
```

### Development Server

Run with auto-reload for development:

```bash
./deployment/scripts/deploy.sh dev

# Or manually
python -m dhruva.cli.server --reload --config=deployment/config/development.yaml
```

## Buildpack Deployment

Cloud Native Buildpacks automatically detect your Python application and create an OCI-compliant image without requiring a Dockerfile.

### Building with Buildpacks

```bash
# Build image using pack CLI
./deployment/scripts/deploy.sh buildpack

# Or manually with pack
pack build ghcr.io/lesleslie/dhruva:5.0.0 \
    --builder paketobuildpacks/builder:base \
    --env BP_PYTHON_VERSION=3.13
```

### Configuration Files

The following files control buildpack behavior:

- **`project.toml`** - Paketo buildpack configuration
- **`Procfile`** - Process declaration (Heroku-style)
- **`buildpacks.yaml`** - Buildpack specification (optional)
- **`requirements.txt`** - Auto-generated from setup.py
- **`setup.py`** - Python package metadata

### Running Buildpack Images Locally

```bash
# Deploy locally from buildpack image
./deployment/scripts/deploy.sh local-buildpack

# Or manually with Docker
docker run -d \
    --name dhruva-server \
    -p 2972:2972 \
    -v dhruva-data:/data \
    -e PORT=2972 \
    ghcr.io/lesleslie/dhruva:5.0.0
```

### Pushing to Registry

```bash
# Push buildpack image to registry
./deployment/scripts/deploy.sh push-buildpack

# Or manually
docker push ghcr.io/lesleslie/dhruva:5.0.0
```

## Cloud Platform Deployment

### Kubernetes Deployment

Deploy buildpack-built images to Kubernetes:

```bash
# Build and push image
./deployment/scripts/deploy.sh buildpack
./deployment/scripts/deploy.sh push-buildpack

# Deploy to Kubernetes
./deployment/scripts/deploy.sh kubernetes
```

**Manual Kubernetes Deployment:**

```bash
# Create namespace
kubectl create namespace dhruva

# Create ConfigMap
kubectl create configmap dhruva-config \
    --from-file=deployment/config/production.yaml \
    --namespace=dhruva

# Apply deployment
envsubst < deployment/kubernetes/deployment.yaml | kubectl apply -f -

# Apply service
envsubst < deployment/kubernetes/service.yaml | kubectl apply -f -

# Check status
kubectl get pods -n dhruva
kubectl logs -f deployment/dhruva-server -n dhruva
```

### Google Cloud Run

```bash
# Build with Cloud Native Buildpacks
pack build ghcr.io/lesleslie/dhruva:5.0.0 \
    --builder=gcr.io/buildpacks/builder:v1

# Push to registry
docker push ghcr.io/lesleslie/dhruva:5.0.0

# Deploy to Cloud Run
gcloud run deploy dhruva-server \
    --image=ghcr.io/lesleslie/dhruva:5.0.0 \
    --platform=managed \
    --region=us-central1 \
    --allow-unauthenticated \
    --port=2972 \
    --set-env-vars PORT=2972
```

### AWS App Runner

```bash
# Build and push to ECR
pack build <your-ecr-repo>:5.0.0 \
    --builder=paketobuildpacks/builder:base

# Deploy via AWS Console or CLI
aws apprunner start-deployment \
    --service-arn <your-service-arn> \
    --image-identifier <your-ecr-repo>:5.0.0
```

## Configuration

### Configuration File

dhruva uses Oneiric for type-safe configuration management. Example `deployment/config/production.yaml`:

```yaml
storage:
  backend: file
  path: /data/dhruva.dhruva

cache:
  size: 100000
  shrink_threshold: 2.0

connection:
  cache_size: 100000

server:
  host: 0.0.0.0
  port: 2972

serialization:
  default: msgspec
  max_size: 104857600  # 100MB

logging:
  level: INFO
  format: json

security:
  sign_objects: false
```

### Environment Variables

Override configuration with environment variables:

```bash
# Server configuration
export DHRUVA_HOST=0.0.0.0
export DHRUVA_PORT=2972
export DHRUVA_CONFIG=/path/to/config.yaml

# Storage configuration
export DHRUVA_STORAGE_BACKEND=file
export DHRUVA_STORAGE_PATH=/data/dhruva.dhruva

# Serialization
export DHRUVA_SERIALIZER=msgspec
export DHRUVA_MAX_SIZE=104857600

# Security
export DHRUVA_SIGN_OBJECTS=true
export DHRUVA_SECRET_KEY=your-secret-key
```

### Loading Configuration

Use `dhruva.config.loader.load_config()`:

```python
from dhruva.config.loader import load_config

# Load from file
config = load_config("config/production.yaml")

# Load from dict
config = load_config({"storage": {"backend": "file"}})

# Auto-detect format
config = load_config("config.yaml")  # Detects YAML/JSON
```

## Health Checks

### Health Check Script

```bash
# Run health check
./deployment/scripts/healthcheck.sh --host=localhost --port=2972
```

### Kubernetes Probes

The Kubernetes deployment includes:
- **Liveness Probe**: Checks if server is running
- **Readiness Probe**: Checks if server can accept connections
- **Startup Probe**: Checks if server started successfully

```yaml
livenessProbe:
  tcpSocket:
    port: 2972
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  tcpSocket:
    port: 2972
  initialDelaySeconds: 5
  periodSeconds: 5
```

### Custom Health Checks

Create custom health checks using `dhruva.observability.health`:

```python
from dhruva.observability.health import HealthChecker

checker = HealthChecker(connection)
health_status = checker.check_health()

if health_status["status"] == "healthy":
    print("System is healthy")
else:
    print(f"System is {health_status['status']}")
```

## Monitoring

### Structured Logging

dhruva uses structured logging with context:

```python
from dhruva.logging.logger import get_connection_logger, log_operation

logger = get_connection_logger("conn-123")

with log_operation("commit", transaction_id="tx-456"):
    connection.commit()
```

### Prometheus Metrics (Future)

Integration with Prometheus metrics will be available in Phase 8 (Observability).

### Application Logs

View application logs:

```bash
# Native installation
# Logs go to stdout/stderr or configured file

# Buildpack/Docker
docker logs -f dhruva-server

# Kubernetes
kubectl logs -f deployment/dhruva-server -n dhruva
```

## Backup and Restore

### Backup Strategy

```bash
# File storage backup
cp /data/dhruva.dhruva /backup/dhruva-$(date +%Y%m%d).dhruva

# Or using Python
python -c "
from dhruva.storage.file import FileStorage
from shutil import copy2
import datetime

backup_path = f'/backup/dhruva-{datetime.datetime.now():%Y%m%d}.dhruva'
copy2('/data/dhruva.dhruva', backup_path)
print(f'Backed up to {backup_path}')
"
```

### Automated Backups

Use cron for automated backups:

```bash
# Add to crontab (crontab -e)
0 2 * * * cp /data/dhruva.dhruva /backup/dhruva-$(date +\%Y\%m\%d).dhruva
```

### Restore from Backup

```bash
# Stop server
./deployment/scripts/deploy.sh stop

# Restore backup
cp /backup/dhruva-20250107.dhruva /data/dhruva.dhruva

# Start server
./deployment/scripts/deploy.sh run
```

## Security

### Serialization Security

By default, dhruva uses **msgspec** for secure serialization. Pickle is only used when explicitly configured.

**Recommendations:**
- Use msgspec serializer in production (default)
- Avoid pickle for untrusted data sources
- Set size limits on deserialization
- Enable object signing for sensitive data

### Object Signing

Enable HMAC signing for additional security:

```yaml
security:
  sign_objects: true
  secret_key_env: DHRUVA_SECRET_KEY
```

```bash
export DHRUVA_SECRET_KEY=$(openssl rand -hex 32)
```

### Network Security

- Use TLS/SSL for client-server connections
- Bind to specific interfaces (not 0.0.0.0) when possible
- Use firewalls to restrict access
- Implement authentication in client applications

### Container Security (Buildpack Images)

Buildpack images are secure by default:
- Non-root user execution
- Read-only root filesystem
- Minimal attack surface
- Automatic security updates via base image updates

## Troubleshooting

### Common Issues

**Issue:** Server won't start
```bash
# Check port availability
netstat -tuln | grep 2972
lsof -i :2972

# Check configuration
python -c "from dhruva.config.loader import load_config; print(load_config('deployment/config/production.yaml'))"
```

**Issue:** High memory usage
```bash
# Check cache size
python -c "
from dhruva.connection import Connection
from dhruva.storage.file import FileStorage
conn = Connection(FileStorage('/data/dhruva.dhruva'))
print(f'Cache size: {len(conn.get_cache())}')
"

# Reduce cache size in config
cache:
  size: 50000  # Reduce from 100000
```

**Issue:** Slow performance
```bash
# Check serialization method
python -c "
from dhruva.serialize.factory import get_serializer
s = get_serializer('msgspec')
print(f'Serializer: {type(s).__name__}')
"

# Benchmark serializers
pytest benchmarks/test_serializers.py --benchmark-only
```

### Debug Mode

Enable debug logging:

```bash
export DHRUVA_LOG_LEVEL=DEBUG
python -m dhruva.cli.server --reload
```

### Health Check Failures

```bash
# Manual health check
./deployment/scripts/healthcheck.sh --verbose

# Check server logs
kubectl logs deployment/dhruva-server -n dhruva --tail=100
```

## Additional Resources

- **Configuration Reference:** See `deployment/config/production.yaml`
- **API Documentation:** [Link to API docs]
- **Performance Benchmarks:** Run `pytest benchmarks/ --benchmark-only`
- **Buildpacks Documentation:** https://buildpacks.io/
- **Paketo Buildpacks:** https://paketo.io/

## Quick Start

```bash
# Native installation (quickest)
git clone https://github.com/lesleslie/dhruva.git
cd dhruva
pip install -e .
python -m dhruva.cli.server

# Buildpack deployment
./deployment/scripts/deploy.sh buildpack
./deployment/scripts/deploy.sh local-buildpack

# Kubernetes deployment
./deployment/scripts/deploy.sh buildpack
./deployment/scripts/deploy.sh kubernetes
```

For more information, see the [main README](README.md) or open an issue on GitHub.
