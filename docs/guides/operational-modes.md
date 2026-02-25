# Druva Operational Modes Guide

## Overview

Druva provides two operational modes to simplify setup for different use cases:

- **Lite Mode**: Zero-configuration development mode
- **Standard Mode**: Full-featured production mode

This guide explains how to use each mode and when to choose one over the other.

## Quick Comparison

| Feature | Lite Mode | Standard Mode |
|---------|-----------|---------------|
| **Setup Time** | < 2 minutes | 10-15 minutes |
| **Configuration Required** | None (sensible defaults) | YAML + environment variables |
| **Services** | 1 (Druva only) | 2+ (Druva + optional cloud storage) |
| **Storage Backend** | Local filesystem only | File, SQLite, S3, GCS, Azure |
| **Default Host** | 127.0.0.1 (localhost only) | 0.0.0.0 (all interfaces) |
| **Logging** | DEBUG (text format) | INFO (JSON format) |
| **Cloud Storage** | Not available | S3, GCS, Azure integration |
| **Ideal For** | Development, testing, learning | Production, multi-server, cloud-native |

## Lite Mode

### Overview

Lite mode is designed for **development and testing** with zero configuration required. It provides the fastest path to getting started with Druva.

### Features

- **Zero Configuration**: Works out of the box with sensible defaults
- **Local Storage**: Uses `~/.local/share/druva/lite.druva` for data
- **Localhost Only**: Binds to `127.0.0.1:8683` for security
- **Debug Logging**: Verbose output for development
- **No Cloud Dependencies**: Everything runs locally

### When to Use Lite Mode

- Local development and testing
- Quick prototyping and experimentation
- Learning Druva's API and features
- Single-machine deployments
- CI/CD testing environments

### Getting Started

#### Option 1: Using the startup script (Recommended)

```bash
# Start in lite mode
./scripts/dev-start.sh lite

# Or simply (defaults to lite)
./scripts/dev-start.sh
```

#### Option 2: Using environment variable

```bash
# Set mode
export DRUVA_MODE=lite

# Start Druva
druva-mcp start

# Or using Python
python -m druva.cli start
```

#### Option 3: Using Python API

```python
from druva.modes import LiteMode

# Create and initialize lite mode
mode = LiteMode()
mode.initialize()

# Show banner
print(mode.get_banner())

# Get mode information
info = mode.get_info()
print(f"Storage: {info['storage_path']}")
print(f"Access URL: {info['access_url']}")
```

### Configuration

Lite mode uses the following defaults (can be overridden via `settings/lite.yaml`):

```yaml
mode: lite
storage:
  path: ~/.local/share/druva/lite.druva
  backend: file
  read_only: false

host: 127.0.0.1
port: 8683

logging:
  level: DEBUG
  format: text

cloud_storage:
  enabled: false
```

### Storage Location

By default, lite mode stores data in:

```
~/.local/share/druva/lite.druva
```

This location is automatically created on first startup.

### Accessing Druva

Once started, Druva MCP server is available at:

```
http://127.0.0.1:8683
```

### Example Workflow

```bash
# 1. Start Druva in lite mode
export DRUVA_MODE=lite
druva-mcp start

# 2. In another terminal, connect with Python
python << 'EOF'
from druva.core import Connection
from druva.storage.file import FileStorage

# Connect to lite mode storage
storage = FileStorage("~/.local/share/druva/lite.druva")
conn = Connection(storage)

# Use Druva
root = conn.get_root()
root["test"] = "Hello from lite mode!"
conn.commit()

print("Data stored successfully!")
conn.close()
EOF
```

## Standard Mode

### Overview

Standard mode is designed for **production deployments** with full configuration control and multiple storage backend options.

### Features

- **Configurable Storage**: File, SQLite, S3, GCS, Azure
- **All Interfaces**: Binds to `0.0.0.0` for external access
- **Production Logging**: INFO level with JSON format
- **Cloud Integration**: Built-in S3, GCS, Azure support
- **Backup Support**: Automated backups to cloud storage
- **Horizontal Scaling**: Suitable for multi-server deployments

### When to Use Standard Mode

- Production deployments
- Multi-server architectures
- Cloud-native applications
- High availability requirements
- Disaster recovery scenarios
- Large-scale data storage

### Getting Started

#### Option 1: Using the startup script

```bash
# Start in standard mode
./scripts/dev-start.sh standard
```

#### Option 2: Using environment variable

```bash
# Set mode
export DRUVA_MODE=standard

# Start Druva
druva-mcp start
```

#### Option 3: Using Python API

```python
from druva.modes import StandardMode

# Create and initialize standard mode
mode = StandardMode()
mode.initialize()

# Show banner
print(mode.get_banner())
```

### Configuration

Standard mode uses `settings/standard.yaml` for configuration:

```yaml
mode: standard
storage:
  path: /data/druva/production.druva
  backend: file  # Options: file, sqlite, s3, gcs, azure
  read_only: false

host: 0.0.0.0
port: 8683

logging:
  level: INFO
  format: json

cloud_storage:
  enabled: true
  provider: s3
  bucket: druva-production
  prefix: backups/
  schedule: "0 2 * * *"  # Daily at 2 AM
```

### Storage Backends

#### File Storage (Default)

```bash
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=file
export DRUVA_STORAGE_PATH=/data/druva/production.druva
druva-mcp start
```

#### SQLite Storage

```bash
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=sqlite
export DRUVA_STORAGE_PATH=/data/druva/production.db
druva-mcp start
```

#### Amazon S3 Storage

```bash
# Set AWS credentials
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_REGION=us-east-1

# Configure S3 storage
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=s3
export DRUVA_S3_BUCKET=druva-production
export DRUVA_S3_PREFIX=druva/

# Start Druva
druva-mcp start
```

#### Google Cloud Storage

```bash
# Set GCS credentials
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Configure GCS storage
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=gcs
export DRUVA_GCS_BUCKET=druva-production
export DRUVA_GCS_PREFIX=druva/

# Start Druva
druva-mcp start
```

#### Azure Blob Storage

```bash
# Set Azure credentials
export AZURE_STORAGE_CONNECTION_STRING="your-connection-string"

# Configure Azure storage
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=azure
export DRUVA_AZURE_CONTAINER=druva-production
export DRUVA_AZURE_PREFIX=druva/

# Start Druva
druva-mcp start
```

### Cloud Backup Configuration

Standard mode includes automated cloud backup support:

```yaml
cloud_storage:
  enabled: true
  provider: s3
  bucket: druva-backups
  prefix: backups/
  schedule: "0 2 * * *"  # Cron format: daily at 2 AM

  # Optional: Retention policy
  retention_days: 30

  # Optional: Compression
  compression: true
```

### Example Production Deployment

```bash
# 1. Configure environment
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=s3
export DRUVA_S3_BUCKET=my-druva-production
export AWS_REGION=us-west-2

# 2. Create data directory
sudo mkdir -p /data/druva
sudo chown $USER:$USER /data/druva

# 3. Start Druva
druva-mcp start

# 4. Verify health
druva-mcp health --probe
```

## Mode Management

### Detecting Current Mode

```python
from druva.modes import get_mode

# Auto-detect mode from environment
mode = get_mode()
print(f"Current mode: {mode.get_name()}")
print(f"Description: {mode.get_description()}")
```

### Listing All Modes

```python
from druva.modes import list_modes

for info in list_modes():
    print(f"{info['name']}: {info['description']}")
    print(f"  Config: {info['config_path']}")
    print(f"  Storage: {info['storage_path']}")
    print()
```

### Switching Modes

To switch between modes:

1. **Stop current instance**:

   ```bash
   druva-mcp stop
   ```

1. **Set new mode**:

   ```bash
   export DRUVA_MODE=standard  # or lite
   ```

1. **Start new instance**:

   ```bash
   druva-mcp start
   ```

## Migration Guide

### Lite → Standard Migration

When moving from development (lite) to production (standard):

#### Step 1: Export Data from Lite Mode

```python
from druva.core import Connection
from druva.storage.file import FileStorage
import json

# Connect to lite mode storage
storage = FileStorage("~/.local/share/druva/lite.druva")
conn = Connection(storage)

# Export root data
root = conn.get_root()
data = dict(root)

# Save to JSON
with open("/tmp/druva-lite-export.json", "w") as f:
    json.dump(data, f, indent=2)

conn.close()
print("Export complete: /tmp/druva-lite-export.json")
```

#### Step 2: Configure Standard Mode

Create `settings/production.yaml`:

```yaml
mode: standard
storage:
  backend: s3
  path: s3://my-druva-production/druva.druva

host: 0.0.0.0
port: 8683

cloud_storage:
  enabled: true
  provider: s3
  bucket: my-druva-production
```

#### Step 3: Import to Standard Mode

```python
from druva.core import Connection
from druva.modes import StandardMode
import json

# Initialize standard mode
mode = StandardMode()
mode.initialize()

# Import data
with open("/tmp/druva-lite-export.json", "r") as f:
    data = json.load(f)

# Get connection (configured via mode)
# Note: You'll need to implement storage-specific connection
# This is a simplified example
```

#### Step 4: Start in Standard Mode

```bash
export DRUVA_MODE=standard
druva-mcp start
```

## Troubleshooting

### Mode Not Detected

If mode detection doesn't work:

```bash
# Explicitly set mode
export DRUVA_MODE=lite

# Verify
python -c "from druva.modes import get_mode; print(get_mode().get_name())"
```

### Storage Directory Issues

Lite mode can't create storage directory:

```bash
# Create manually
mkdir -p ~/.local/share/druva

# Check permissions
ls -la ~/.local/share/
```

### Port Already in Use

```bash
# Check what's using the port
lsof -i :8683

# Use a different port
export DRUVA_PORT=8684
druva-mcp start
```

### Cloud Storage Connection Issues

For standard mode with cloud storage:

```bash
# Verify credentials
env | grep AWS  # For S3
env | grep GOOGLE  # For GCS
env | grep AZURE  # For Azure

# Test connectivity
python -c "
import boto3  # For S3
s3 = boto3.client('s3')
print(s3.list_buckets())
"
```

## Best Practices

### Development (Lite Mode)

- Use lite mode for all development work
- Keep data in `~/.local/share/druva/` for easy access
- Use debug logging to troubleshoot issues
- Don't expose port 8683 to external networks

### Production (Standard Mode)

- Always use standard mode for production
- Configure appropriate storage backend for your scale
- Enable automated cloud backups
- Use JSON logging for log aggregation
- Monitor health with `druva-mcp health --probe`
- Set up alerts for storage capacity and errors

### Security

- **Lite Mode**: Only binds to localhost, suitable for local development
- **Standard Mode**: Binds to all interfaces, use firewall rules
- **Cloud Storage**: Use IAM roles instead of access keys when possible
- **Backups**: Encrypt backups if storing sensitive data

## Performance Tuning

### Lite Mode Tuning

Lite mode is optimized for development, but you can adjust:

```yaml
# settings/lite.yaml
cache:
  size: 10000  # Increase for larger datasets

logging:
  level: INFO  # Reduce verbosity if needed
```

### Standard Mode Tuning

For production workloads:

```yaml
# settings/standard.yaml
cache:
  size: 100000  # Larger cache for better performance
  shrink_threshold: 2.0

# For high-throughput scenarios
storage:
  backend: sqlite  # Faster than file for concurrent access
```

## Additional Resources

- **Configuration Reference**: See `settings/lite.yaml` and `settings/standard.yaml`
- **API Documentation**: [Link to API docs]
- **Deployment Guide**: See `DEPLOYMENT.md`
- **Migration Scripts**: See `examples/mode_migration_demo.py`

## Getting Help

If you encounter issues:

1. Check mode: `python -c "from druva.modes import get_mode; print(get_mode().get_info())"`
1. Check logs: `tail -f ~/.oneiric_cache/druva.log`
1. Verify configuration: `python -c "from druva.core.config import DruvaSettings; print(DruvaSettings.load())"`
1. Check health: `druva-mcp health --probe`

## Summary

- **Use Lite Mode** for development, testing, and learning
- **Use Standard Mode** for production and multi-server deployments
- **Switch modes** by setting `DRUVA_MODE` environment variable
- **Migrate carefully** when moving from lite to standard
- **Monitor health** and logs in production deployments

The mode system is designed to make Druva accessible for beginners while providing the power and flexibility needed for production workloads.
