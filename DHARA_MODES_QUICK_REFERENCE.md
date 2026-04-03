# Dhara Operational Modes - Quick Reference

## Quick Start

### Lite Mode (Development)

```bash
# Zero configuration startup
export DHARA_MODE=lite
dhara-mcp start

# Or use the startup script
./scripts/dev-start.sh lite
```

### Standard Mode (Production)

```bash
# Production startup
export DHARA_MODE=standard
dhara-mcp start

# With S3 storage
export DHARA_MODE=standard
export DHARA_STORAGE_BACKEND=s3
export DHARA_S3_BUCKET=my-bucket
dhara-mcp start
```

## Command Reference

### Mode Selection

```bash
# Environment variable (recommended)
export DHARA_MODE=lite          # or standard

# Startup script
./scripts/dev-start.sh lite
./scripts/dev-start.sh standard

# Python API
from dhara.modes import LiteMode, StandardMode
mode = LiteMode()
mode.initialize()
```

### CLI Commands

```bash
# Start server
dhara-mcp start

# Check status
dhara-mcp status

# Health check
dhara-mcp health --probe

# Stop server
dhara-mcp stop
```

## Configuration Locations

### Lite Mode

- **Config**: `settings/lite.yaml`
- **Storage**: `~/.local/share/dhara/lite.dhara`
- **Host**: `127.0.0.1:8683`
- **Logging**: DEBUG, text format

### Standard Mode

- **Config**: `settings/standard.yaml`
- **Storage**: `/data/dhara/production.dhara` (default)
- **Host**: `0.0.0.0:8683`
- **Logging**: INFO, JSON format

## Storage Backends

| Backend | Lite Mode | Standard Mode | Configuration |
|---------|-----------|---------------|---------------|
| File | ✅ Default | ✅ | `DHARA_STORAGE_BACKEND=file` |
| SQLite | ❌ | ✅ | `DHARA_STORAGE_BACKEND=sqlite` |
| S3 | ❌ | ✅ | `DHARA_STORAGE_BACKEND=s3` + AWS creds |
| GCS | ❌ | ✅ | `DHARA_STORAGE_BACKEND=gcs` + GCS creds |
| Azure | ❌ | ✅ | `DHARA_STORAGE_BACKEND=azure` + Azure creds |

## Environment Variables

### Mode Selection

```bash
DHARA_MODE=lite|standard
```

### Storage Configuration

```bash
DHARA_STORAGE_BACKEND=file|sqlite|s3|gcs|azure
DHARA_STORAGE_PATH=/path/to/storage
```

### S3 Storage

```bash
DHARA_S3_BUCKET=my-bucket
DHARA_S3_PREFIX=dhara/
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1
```

### GCS Storage

```bash
DHARA_GCS_BUCKET=my-bucket
DHARA_GCS_PREFIX=dhara/
GOOGLE_APPLICATION_CREDENTIALS=/path/to/keyfile.json
```

### Azure Storage

```bash
DHARA_AZURE_CONTAINER=my-container
DHARA_AZURE_PREFIX=dhara/
AZURE_STORAGE_CONNECTION_STRING=xxx
```

### Server Configuration

```bash
DHARA_HOST=0.0.0.0
DHARA_PORT=8683
```

## Python API

### Mode Management

```python
# Create specific mode
from dhara.modes import LiteMode, StandardMode

lite = LiteMode()
lite.initialize()

standard = StandardMode()
standard.initialize()

# Auto-detect mode
from dhara.modes import get_mode
mode = get_mode()
print(f"Running in {mode.get_name()} mode")

# List all modes
from dhara.modes import list_modes
for info in list_modes():
    print(f"{info['name']}: {info['description']}")
```

### Direct Configuration

```python
from dhara.core.config import DharaSettings

# Load settings (auto-detects mode)
settings = DharaSettings.load("dhara")

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
from dhara.modes import get_mode
mode = get_mode()
print(mode.get_info())
```

### Check Configuration

```python
from dhara.core.config import DharaSettings
settings = DharaSettings.load("dhara")
print(settings.model_dump_json(indent=2))
```

### Validate Environment

```python
from dhara.modes import LiteMode
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
export DHARA_MODE=standard
export DHARA_STORAGE_BACKEND=s3
export DHARA_S3_BUCKET=my-bucket

# 3. Import data to standard mode
# (See documentation for import script)

# 4. Start in standard mode
dhara-mcp start
```

## File Locations

```
dhara/
├── modes/
│   ├── base.py          # Base mode interface
│   ├── lite.py          # Lite mode implementation
│   └── standard.py      # Standard mode implementation
├── core/
│   └── config.py        # Configuration with mode support
├── settings/
│   ├── lite.yaml        # Lite mode config
│   ├── standard.yaml    # Standard mode config
│   └── dhara.yaml      # Default config (backward compat)
├── scripts/
│   └── dev-start.sh     # Development startup script
└── docs/
    └── guides/
        └── operational-modes.md  # Full guide
```

## Quick Commands

```bash
# Start lite mode
export DHARA_MODE=lite && dhara-mcp start

# Start standard mode with S3
export DHARA_MODE=standard && \
export DHARA_STORAGE_BACKEND=s3 && \
export DHARA_S3_BUCKET=my-bucket && \
dhara-mcp start

# Check health
dhara-mcp health --probe

# Show mode info (Python)
python -c "from dhara.modes import get_mode; print(get_mode().get_info())"

# List modes (Python)
python -c "from dhara.modes import list_modes; import pprint; pprint.pprint(list_modes())"
```

## Common Patterns

### Development Workflow

```bash
# 1. Start in lite mode
./scripts/dev-start.sh lite

# 2. Develop and test
# ... work ...

# 3. Stop when done
dhara-mcp stop
```

### Production Deployment

```bash
# 1. Configure environment
export DHARA_MODE=standard
export DHARA_STORAGE_BACKEND=s3
export DHARA_S3_BUCKET=prod-bucket

# 2. Start server
dhara-mcp start

# 3. Monitor health
watch -n 5 'dhara-mcp health --probe'
```

## Summary

- **Lite Mode**: `export DHARA_MODE=lite` → Zero config dev mode
- **Standard Mode**: `export DHARA_MODE=standard` → Full production mode
- **Startup Script**: `./scripts/dev-start.sh [lite|standard]`
- **Python API**: `from dhara.modes import LiteMode, StandardMode`
- **Docs**: `docs/guides/operational-modes.md`
