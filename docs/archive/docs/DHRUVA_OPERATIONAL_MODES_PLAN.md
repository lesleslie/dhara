# Dhara Operational Modes Implementation Plan

## Executive Summary

This document outlines the implementation of operational modes for Dhara, creating a "lite" mode similar to Mahavishnu's architecture. The goal is to dramatically simplify setup and operation for development use cases while maintaining full production capabilities.

## Current State Analysis

### Existing Architecture
- **Storage Backends**: File, SQLite, Memory (currently implemented)
- **Cloud Storage**: S3, GCS, Azure (available via `dhara/backup/storage.py`)
- **Configuration**: Oneiric-based with YAML + environment variables
- **Server Models**: Direct file access, client/server over TCP
- **Dependencies**: FastMCP, mcp-common, oneiric, uvicorn, IPython

### Operational Complexity
Current deployment requires:
1. Understanding multiple storage backends
2. Configuration file setup (YAML)
3. Optional cloud storage credentials
4. Multiple deployment patterns (native, buildpack, kubernetes)

## Proposed Mode System

### Mode Definitions

#### Lite Mode (Development)
- **Purpose**: Quick start for development and testing
- **Setup Time**: < 2 minutes
- **Services**: 1 (Dhara only)
- **Storage**: Local filesystem with auto-creation
- **Configuration**: Zero config required (sensible defaults)
- **Ideal For**:
  - Local development
  - Quick prototyping
  - Testing and experimentation
  - Single-machine deployments

#### Standard Mode (Production)
- **Purpose**: Production deployments with cloud storage
- **Setup Time**: 10-15 minutes
- **Services**: 2 (Dhara + cloud storage)
- **Storage**: Configurable backend (file/s3/gcs/azure)
- **Configuration**: Full YAML + environment variables
- **Ideal For**:
  - Production deployments
  - Multi-server setups
  - Cloud-native applications
  - Disaster recovery scenarios

### Feature Comparison Matrix

| Feature | Lite Mode | Standard Mode |
|---------|-----------|---------------|
| **Setup Time** | < 2 min | 10-15 min |
| **Services Required** | 1 (Dhara) | 2+ (Dhara + Cloud) |
| **Storage Backend** | Local filesystem | Configurable (file/S3/GCS/Azure) |
| **Configuration** | Zero config (defaults) | YAML + env vars |
| **Data Persistence** | Local disk | Configurable (local/cloud) |
| **Backup Integration** | Manual file copy | Automated cloud backups |
| **High Availability** | No | Yes (with cloud storage) |
| **Scaling** | Single instance | Horizontal scaling capable |
| **Ideal Use Case** | Development, testing | Production, multi-server |

## Implementation Plan

### Phase 1: Mode System Foundation (Day 1)

**Objective**: Create mode system architecture

**Tasks**:
1. Create `dhara/modes/` directory structure
2. Implement base mode interface (`base.py`)
3. Implement lite mode (`lite.py`)
4. Implement standard mode (`standard.py`)

**Deliverables**:
- `dhara/modes/__init__.py`
- `dhara/modes/base.py` - Base mode interface
- `dhara/modes/lite.py` - Lite mode implementation
- `dhara/modes/standard.py` - Standard mode implementation

**Success Criteria**:
- Mode system architecture complete
- Base interface defined and documented
- Lite and standard modes stubbed out

### Phase 2: Configuration Management (Day 1)

**Objective**: Create mode-specific configurations

**Tasks**:
1. Create `settings/lite.yaml` - Lite mode defaults
2. Create `settings/standard.yaml` - Standard mode defaults
3. Update `DharaSettings` to support mode detection
4. Add mode validation logic

**Deliverables**:
- `settings/lite.yaml` - Lite mode configuration
- `settings/standard.yaml` - Standard mode configuration
- Updated `dhara/core/config.py` with mode support

**Success Criteria**:
- Configuration files created and validated
- Mode detection logic working
- Settings load correctly for each mode

### Phase 3: Mode Implementations (Day 2)

**Objective**: Complete mode-specific logic

**Tasks**:
1. Implement Lite Mode:
   - Auto-create storage directory
   - Use local filesystem storage
   - Set sensible defaults (localhost:8683)
   - Disable cloud features

2. Implement Standard Mode:
   - Support configurable storage backends
   - Enable cloud storage integration
   - Support full YAML configuration
   - Enable all production features

**Deliverables**:
- Complete `dhara/modes/lite.py` implementation
- Complete `dhara/modes/standard.py` implementation

**Success Criteria**:
- Lite mode starts without any configuration
- Standard mode supports all storage backends
- Both modes tested and working

### Phase 4: CLI Integration (Day 2)

**Objective**: Add mode selection to CLI

**Tasks**:
1. Update `dhara/cli.py` with `--mode` parameter
2. Add `mode` subcommand group
3. Implement mode-specific commands
4. Update help text and documentation

**Deliverables**:
- Updated `dhara/cli.py` with mode integration
- New `dhara mode <lite|standard>` command group
- Updated help documentation

**Success Criteria**:
- CLI accepts `--mode` parameter
- Mode-specific commands working
- Help text clear and accurate

### Phase 5: Startup Script (Day 3)

**Objective**: Create easy startup script

**Tasks**:
1. Create `scripts/dev-start.sh`
2. Add mode detection and validation
3. Implement auto-configuration logic
4. Add error handling and validation

**Deliverables**:
- `scripts/dev-start.sh` - Development startup script
- Documentation for script usage

**Success Criteria**:
- Script starts Dhara in specified mode
- Auto-configuration working
- Error handling comprehensive

### Phase 6: Documentation (Day 3)

**Objective**: Create comprehensive documentation

**Tasks**:
1. Create `docs/guides/operational-modes.md`
2. Update README.md with mode information
3. Update DEPLOYMENT.md with mode-specific instructions
4. Create migration guide (lite → standard)

**Deliverables**:
- `docs/guides/operational-modes.md` - Complete mode guide
- Updated README.md
- Updated DEPLOYMENT.md
- Migration guide document

**Success Criteria**:
- Documentation complete and accurate
- Examples provided for both modes
- Migration path clear

### Phase 7: Testing (Day 4)

**Objective**: Comprehensive test coverage

**Tasks**:
1. Create `tests/unit/test_modes/` directory
2. Write unit tests for mode system
3. Write integration tests for each mode
4. Test mode switching and migration

**Deliverables**:
- `tests/unit/test_modes/test_base.py`
- `tests/unit/test_modes/test_lite.py`
- `tests/unit/test_modes/test_standard.py`
- `tests/integration/test_mode_switching.py`

**Success Criteria**:
- Unit tests passing (>90% coverage)
- Integration tests passing
- Mode switching tested

### Phase 8: Examples and Demos (Day 4)

**Objective**: Provide working examples

**Tasks**:
1. Create `examples/lite_mode_demo.py`
2. Create `examples/standard_mode_demo.py`
3. Create `examples/mode_migration_demo.py`
4. Update existing examples

**Deliverables**:
- Working examples for both modes
- Migration example
- Updated documentation

**Success Criteria**:
- Examples run successfully
- Clear and well-documented code

## Technical Architecture

### Mode System Design

```python
# Base Mode Interface
class OperationalMode(ABC):
    """Base class for operational modes."""

    @abstractmethod
    def get_name(self) -> str:
        """Return mode name."""

    @abstractmethod
    def get_config_path(self) -> Path:
        """Return path to mode-specific config."""

    @abstractmethod
    def validate_environment(self) -> bool:
        """Validate environment prerequisites."""

    @abstractmethod
    def configure_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure storage backend for this mode."""

    @abstractmethod
    def get_startup_options(self) -> dict:
        """Get default startup options."""
```

### Mode Detection Logic

```python
def detect_mode(settings: DharaSettings) -> OperationalMode:
    """Detect operational mode from configuration.

    Priority:
    1. Explicit DHARA_MODE environment variable
    2. settings.dhara.yaml mode field
    3. Auto-detect based on storage configuration
    """
    # Check environment variable
    mode = os.getenv("DHARA_MODE", "").lower()
    if mode in ("lite", "standard"):
        return create_mode(mode)

    # Check settings file
    if hasattr(settings, "mode"):
        return create_mode(settings.mode)

    # Auto-detect
    if settings.storage.backend == "file" and settings.storage.path == DEFAULT_LITE_PATH:
        return LiteMode()
    else:
        return StandardMode()
```

### Configuration File Structure

**settings/lite.yaml**:
```yaml
mode: lite
server_name: "Dhara Lite (Development)"

storage:
  path: ~/.local/share/dhara/lite.dhara
  backend: file
  read_only: false

# Server configuration
host: 127.0.0.1
port: 8683

# Disable cloud features
cloud_storage:
  enabled: false

# Logging
logging:
  level: DEBUG
  format: text
```

**settings/standard.yaml**:
```yaml
mode: standard
server_name: "Dhara (Production)"

storage:
  path: /data/dhara/production.dhara
  backend: file  # or sqlite, s3, gcs, azure
  read_only: false

# Server configuration
host: 0.0.0.0
port: 8683

# Enable cloud storage
cloud_storage:
  enabled: true
  provider: s3  # or gcs, azure
  bucket: dhara-production
  prefix: backups/

# Logging
logging:
  level: INFO
  format: json
```

## CLI Usage Examples

### Lite Mode (Zero Config)
```bash
# Start in lite mode (no configuration required)
dhara start --mode=lite

# Or use the shorthand
dhara start -m lite

# Environment variable
export DHARA_MODE=lite
dhara start
```

### Standard Mode
```bash
# Start in standard mode
dhara start --mode=standard

# With custom configuration
dhara start --mode=standard --config=settings/production.yaml

# With S3 storage
export DHARA_STORAGE_BACKEND=s3
export DHARA_S3_BUCKET=my-bucket
dhara start --mode=standard
```

### Mode Management
```bash
# Show current mode
dhara mode status

# Switch modes (interactive)
dhara mode switch

# Validate mode configuration
dhara mode validate

# Compare modes
dhara mode diff lite standard
```

## Migration Path

### Lite → Standard Migration

**Scenario**: Growing from development to production

```bash
# 1. Export data from lite mode
dhara export --source=~/.local/share/dhara/lite.dhara \
              --output=/tmp/dhara-export.json

# 2. Configure standard mode
cat > settings/production.yaml <<EOF
mode: standard
storage:
  backend: s3
  bucket: dhara-production
EOF

# 3. Import to standard mode
dhara import --source=/tmp/dhara-export.json \
              --config=settings/production.yaml

# 4. Start in standard mode
dhara start --mode=standard --config=settings/production.yaml
```

## Success Metrics

### Operational Metrics
- Lite mode setup time: < 2 minutes
- Standard mode setup time: < 15 minutes
- Mode switch time: < 5 minutes
- Documentation coverage: 100%

### Quality Metrics
- Test coverage: >90%
- All tests passing
- Zero critical bugs
- Clear error messages

### User Experience Metrics
- Zero configuration required for lite mode
- Clear documentation for both modes
- Intuitive CLI interface
- Helpful error messages

## Risks and Mitigations

### Risk 1: Mode Confusion
**Risk**: Users may not understand which mode they're using
**Mitigation**:
- Clear mode indicator in startup banner
- `dhara mode status` command
- Mode displayed in logs

### Risk 2: Configuration Conflicts
**Risk**: Conflicting configuration between modes
**Mitigation**:
- Separate config files per mode
- Validation on startup
- Clear error messages

### Risk 3: Data Loss During Migration
**Risk**: Data loss when switching modes
**Mitigation**:
- Export/import tools
- Backup before migration
- Validation after migration
- Rollback capability

## Timeline

- **Day 1**: Phase 1-2 (Foundation + Configuration)
- **Day 2**: Phase 3-4 (Implementations + CLI)
- **Day 3**: Phase 5-6 (Script + Documentation)
- **Day 4**: Phase 7-8 (Testing + Examples)

## Conclusion

This operational mode system will dramatically simplify Dhara's development experience while maintaining full production capabilities. The lite mode enables zero-configuration startup for developers, while standard mode provides enterprise-grade features for production deployments.

The implementation follows Mahavishnu's proven pattern of operational simplification, making Dhara more accessible to new users while preserving power-user capabilities.

## Next Steps

1. Review and approve this plan
2. Begin Phase 1 implementation
3. Track progress with daily updates
4. Adjust timeline based on feedback
