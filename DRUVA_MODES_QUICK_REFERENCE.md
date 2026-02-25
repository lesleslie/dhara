# Druva Operational Modes - Quick Reference

## Quick Start

### Lite Mode (Development)

```bash
# Zero configuration startup
export DRUVA_MODE=lite
druva-mcp start

# Or use the startup script
./scripts/dev-start.sh lite
```

### Standard Mode (Production)

```bash
# Production startup
export DRUVA_MODE=standard
druva-mcp start

# With S3 storage
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=s3
export DRUVA_S3_BUCKET=my-bucket
druva-mcp start
```

## Command Reference

### Mode Selection

```bash
# Environment variable (recommended)
export DRUVA_MODE=lite          # or standard

# Startup script
./scripts/dev-start.sh lite
./scripts/dev-start.sh standard

# Python API
from druva.modes import LiteMode, StandardMode
mode = LiteMode()
mode.initialize()
```

### CLI Commands

```bash
# Start server
druva-mcp start

# Check status
druva-mcp status

# Health check
druva-mcp health --probe

# Stop server
druva-mcp stop
```

## Configuration Locations

### Lite Mode

- **Config**: `settings/lite.yaml`
- **Storage**: `~/.local/share/druva/lite.druva`
- **Host**: `127.0.0.1:8683`
- **Logging**: DEBUG, text format

### Standard Mode

- **Config**: `settings/standard.yaml`
- **Storage**: `/data/druva/production.druva` (default)
- **Host**: `0.0.0.0:8683`
- **Logging**: INFO, JSON format

## Storage Backends

| Backend | Lite Mode | Standard Mode | Configuration |
|---------|-----------|---------------|---------------|
| File | ✅ Default | ✅ | `DRUVA_STORAGE_BACKEND=file` |
| SQLite | ❌ | ✅ | `DRUVA_STORAGE_BACKEND=sqlite` |
| S3 | ❌ | ✅ | `DRUVA_STORAGE_BACKEND=s3` + AWS creds |
| GCS | ❌ | ✅ | `DRUVA_STORAGE_BACKEND=gcs` + GCS creds |
| Azure | ❌ | ✅ | `DRUVA_STORAGE_BACKEND=azure` + Azure creds |

## Environment Variables

### Mode Selection

```bash
DRUVA_MODE=lite|standard
```

### Storage Configuration

```bash
DRUVA_STORAGE_BACKEND=file|sqlite|s3|gcs|azure
DRUVA_STORAGE_PATH=/path/to/storage
```

### S3 Storage

```bash
DRUVA_S3_BUCKET=my-bucket
DRUVA_S3_PREFIX=druva/
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1
```

### GCS Storage

```bash
DRUVA_GCS_BUCKET=my-bucket
DRUVA_GCS_PREFIX=druva/
GOOGLE_APPLICATION_CREDENTIALS=/path/to/keyfile.json
```

### Azure Storage

```bash
DRUVA_AZURE_CONTAINER=my-container
DRUVA_AZURE_PREFIX=druva/
AZURE_STORAGE_CONNECTION_STRING=xxx
```

### Server Configuration

```bash
DRUVA_HOST=0.0.0.0
DRUVA_PORT=8683
```

## Python API

### Mode Management

```python
# Create specific mode
from druva.modes import LiteMode, StandardMode

lite = LiteMode()
lite.initialize()

standard = StandardMode()
standard.initialize()

# Auto-detect mode
from druva.modes import get_mode
mode = get_mode()
print(f"Running in {mode.get_name()} mode")

# List all modes
from druva.modes import list_modes
for info in list_modes():
    print(f"{info['name']}: {info['description']}")
```

### Direct Configuration

```python
from druva.core.config import DruvaSettings

# Load settings (auto-detects mode)
settings = DruvaSettings.load("druva")

# Check mode
print(f"Mode: {settings.mode}")
print(f"Storage: {settings.storage.path}")
print(f"Backend: {settings.storage.backend}")

# Get mode-specific config path
config_path = settings.get_mode_config_path()
print(f"Config: {config_path}")
```

## Troubleshooting

### Check Current Mode

```python
from druva.modes import get_mode
mode = get_mode()
print(mode.get_info())
```

### Check Configuration

```python
from druva.core.config import DruvaSettings
settings = DruvaSettings.load("druva")
print(settings.model_dump_json(indent=2))
```

### Validate Environment

```python
from druva.modes import LiteMode
mode = LiteMode()
try:
    mode.validate_environment()
    print("Environment OK")
except Exception as e:
    print(f"Environment error: {e}")
```

## Migration Steps

### Lite → Standard

```bash
# 1. Export data from lite mode
# (See documentation for export script)

# 2. Configure standard mode
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=s3
export DRUVA_S3_BUCKET=my-bucket

# 3. Import data to standard mode
# (See documentation for import script)

# 4. Start in standard mode
druva-mcp start
```

## File Locations

```
druva/
├── modes/
│   ├── base.py          # Base mode interface
│   ├── lite.py          # Lite mode implementation
│   └── standard.py      # Standard mode implementation
├── core/
│   └── config.py        # Configuration with mode support
├── settings/
│   ├── lite.yaml        # Lite mode config
│   ├── standard.yaml    # Standard mode config
│   └── druva.yaml      # Default config (backward compat)
├── scripts/
│   └── dev-start.sh     # Development startup script
└── docs/
    └── guides/
        └── operational-modes.md  # Full guide
```

## Quick Commands

```bash
# Start lite mode
export DRUVA_MODE=lite && druva-mcp start

# Start standard mode with S3
export DRUVA_MODE=standard && \
export DRUVA_STORAGE_BACKEND=s3 && \
export DRUVA_S3_BUCKET=my-bucket && \
druva-mcp start

# Check health
druva-mcp health --probe

# Show mode info (Python)
python -c "from druva.modes import get_mode; print(get_mode().get_info())"

# List modes (Python)
python -c "from druva.modes import list_modes; import pprint; pprint.pprint(list_modes())"
```

## Common Patterns

### Development Workflow

```bash
# 1. Start in lite mode
./scripts/dev-start.sh lite

# 2. Develop and test
# ... work ...

# 3. Stop when done
druva-mcp stop
```

### Production Deployment

```bash
# 1. Configure environment
export DRUVA_MODE=standard
export DRUVA_STORAGE_BACKEND=s3
export DRUVA_S3_BUCKET=prod-bucket

# 2. Start server
druva-mcp start

# 3. Monitor health
watch -n 5 'druva-mcp health --probe'
```

## Summary

- **Lite Mode**: `export DRUVA_MODE=lite` → Zero config dev mode
- **Standard Mode**: `export DRUVA_MODE=standard` → Full production mode
- **Startup Script**: `./scripts/dev-start.sh [lite|standard]`
- **Python API**: `from druva.modes import LiteMode, StandardMode`
- **Docs**: `docs/guides/operational-modes.md`
