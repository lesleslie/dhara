# Dhara Service Dependencies

## Overview

Dhara is a **standalone persistence service** that can operate independently or integrate with the broader Mahavishnu ecosystem.

## Required Services

**None**

Dhara is a self-contained persistence system that requires no external services for basic operation:

- No database server required (uses file-based storage by default)
- No message broker required
- No external dependencies for core functionality

## Optional Integrations

### Mahavishnu (Orchestrator)

**Role**: Storage backend for orchestration workflows

Dhara can serve as the persistence layer for Mahavishnu orchestration workflows:

```python
# In Mahavishnu configuration
from dhara.core.connection import Connection
from dhara.storage.file import FileStorage

# Dhara provides persistent storage for workflow state
connection = Connection(FileStorage("mahavishnu_workflows.dhara"))
root = connection.get_root()
root["workflows"] = {}
```

**Integration Benefits**:

- ACID guarantees for workflow state
- Transactional workflow execution
- Persistent workflow history
- Optimized for read-heavy workflow queries

### Storage Backends

Dhara supports multiple storage backends:

**File Storage (Default)**

```bash
# No external service needed
dhara db start --file data.dhara
```

**SQLite Storage**

```python
from dhara.storage import SqliteStorage
# Uses SQLite3 (included in Python standard library)
connection = Connection(SqliteStorage("data.db"))
```

**Client/Server Mode**

```bash
# Server (standalone)
dhara db start --port 2973

# Client (connects to server)
from dhara.core.connection import Connection
from dhara.storage.client import ClientStorage
connection = Connection(ClientStorage(address=("localhost", 2973)))
```

### MCP (Model Context Protocol)

**Role**: AI/agent workflow integration

Dhara includes an MCP server for modern AI/agent workflows:

```bash
dhara mcp start
```

**MCP Server Features**:

- Query operations
- Transaction management
- Schema inspection
- Authentication and authorization

**Dependencies**:

- None (MCP protocol is built-in)

### Oneiric (Configuration)

**Role**: Configuration and logging management

Dhara uses Oneiric for configuration management:

```yaml
# dhara.yaml
storage:
  backend: file
  path: /var/lib/dhara/data.dhara

server:
  host: localhost
  port: 2972
  gcbytes: 1000000

serialization:
  backend: msgspec

logging:
  level: INFO
  format: structured
```

**Dependencies**:

- Oneiric library (for configuration loading)
- Environment variables (for secrets)

Canonical runtime settings surface:

```python
from dhara.core.config import DharaSettings

settings = DharaSettings.load("dhara")
```

The older `dhara.config` dataclass helpers remain available for compatibility,
but `DharaSettings` is the primary settings API for CLI and MCP runtime flows.

### Secret Management

**Role**: Secure credential storage

Dhara integrates with Oneiric for secret management:

**Supported Backends**:

- Environment variables (default)
- HashiCorp Vault (optional)
- AWS Secrets Manager (optional)
- In-memory (development only)

```bash
# Environment variables (recommended)
export DHARA_SECRET_KEY="your-secret-key"
export DHARA_DB_PASSWORD="database-password"
```

### Logging Infrastructure

**Role**: Structured logging and monitoring

Dhara uses structured logging via Oneiric:

```yaml
# dhara.yaml
logging:
  level: INFO
  format: structured
  outputs:
    - type: console
      format: json
    - type: file
      path: /var/log/dhara/dhara.log
```

**Optional Integrations**:

- **Logfire**: Python observability (via Oneiric)
- **Sentry**: Error tracking (via Oneiric)
- **Cloud logging**: Any service supporting structured JSON logs

## Network Dependencies

### Local Operation

**No network required**

```bash
# Direct file access (no network)
dhara db client --file data.dhara
```

### Client/Server Mode

**Network protocols**:

- TCP (default port: 2972)
- Unix domain sockets (local only)

```bash
# TCP server
dhara db start --host 0.0.0.0 --port 2973

# Unix domain socket
dhara db start --socket /var/run/dhara.sock
```

**Firewall considerations**:

- Allow TCP port 2972 (or custom port)
- Use TLS/SSL for production deployments
- Consider Unix domain sockets for local communication

## Development Dependencies

### Testing

```bash
# Required for development
pip install -e ".[dev]"

# Preferred validation path
python -m crackerjack qa-health
python -m crackerjack run-tests

# Lower-level testing tools
pytest          # Test framework
pytest-cov      # Coverage reporting
hypothesis      # Property-based testing
```

### Code Quality

```bash
# Quality tools (via Crackerjack)
python -m crackerjack qa-health

# Individual tools
ruff            # Linting and formatting
pyright         # Type checking
bandit          # Security scanning
complexipy      # Complexity analysis
```

### C Extension

```bash
# Build C extension (optional, for CPython)
python setup.py build_ext --inplace
```

**Dependencies**:

- Python.h (CPython headers)
- C compiler (gcc, clang, or MSVC)

## Deployment Scenarios

### Standalone Deployment

**Minimum requirements**:

- Python 3.13+
- Disk space for storage files
- No network required

```bash
# Simple standalone deployment
pip install dhara
dhara db start --file /var/lib/dhara/data.dhara
```

### Client/Server Deployment

**Requirements**:

- Network connectivity
- Server: TCP port 2972 (or custom)
- Client: Server address

```bash
# Server
dhara db start --host 0.0.0.0 --port 2973

# Client (on remote machine)
from dhara.core.connection import Connection
from dhara.storage.client import ClientStorage
connection = Connection(ClientStorage(address=("server.example.com", 2973)))
```

### Container Deployment

**Docker example**:

```dockerfile
FROM python:3.13

RUN pip install dhara

VOLUME /var/lib/dhara
EXPOSE 2972

CMD ["dhara", "db", "start", "--file", "/var/lib/dhara/data.dhara"]
```

**Kubernetes example**:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: dhara
spec:
  serviceName: dhara
  replicas: 1
  selector:
    matchLabels:
      app: dhara
  template:
    metadata:
      labels:
        app: dhara
    spec:
      containers:
      - name: dhara
        image: dhara:latest
        ports:
        - containerPort: 2972
        volumeMounts:
        - name: data
          mountPath: /var/lib/dhara
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

## Service Dependencies Summary

| Service | Required | Optional | Purpose |
|---------|----------|----------|---------|
| **Database Server** | ❌ | ❌ | Uses file-based storage |
| **Message Broker** | ❌ | ❌ | Not needed |
| **Mahavishnu** | ❌ | ✅ | Workflow orchestration |
| **Oneiric** | ❌ | ✅ | Configuration management |
| **MCP Server** | ❌ | ✅ | AI/agent integration |
| **Secret Store** | ❌ | ✅ | Production secret management |
| **Log Aggregator** | ❌ | ✅ | Centralized logging |
| **Network** | ❌ | ✅ | Client/server mode |

## Dependency-Free Operation

Dhara is designed to operate with **zero external dependencies**:

```python
# Complete standalone operation
from dhara import Connection, Persistent

class User(Persistent):
    def __init__(self, name):
        self.name = name

# No external services needed
connection = Connection("users.dhara")
root = connection.get_root()
root["users"] = {}
root["users"]["alice"] = User("Alice")
connection.commit()
```

## Integration Benefits

When integrated with the ecosystem, Dhara provides:

1. **For Mahavishnu**:

   - Persistent workflow state
   - Transactional execution history
   - ACID guarantees for orchestration

1. **For Session-Buddy**:

   - Persistent session storage
   - Long-term memory retention

1. **For Akosha**:

   - Knowledge graph persistence
   - Vector database backend

1. **For MCP Agents**:

   - Stateful agent memory
   - Transactional operations

## Security Considerations

### Standalone Mode

- File permissions on storage files
- Local access control
- No network exposure

### Client/Server Mode

- Network security (TLS/SSL recommended)
- Authentication via MCP server
- Unix domain sockets for local communication

### Secret Management

- Use environment variables or secret stores
- Never hardcode secrets in configuration
- Rotate secrets periodically

## Monitoring

### Built-in Monitoring

- Connection stats
- Cache hit rates
- Transaction metrics
- Storage statistics

### Optional Integrations

- Prometheus metrics (via custom exporters)
- OpenTelemetry tracing
- Structured logging to external services

## Backup and Recovery

Dhara supports various backup strategies:

### File Storage

```bash
# Hot backup (safe to copy while running)
cp data.dhara data.dhara.backup

# Pack before backup (removes garbage)
dhara -p --file data.dhara
```

### Point-in-Time Recovery

FileStorage supports point-in-time recovery (until pack):

```bash
# Recover to specific transaction
# (requires implementation)
```

For detailed backup procedures, see [docs/BACKUP_RECOVERY.md](../BACKUP_RECOVERY.md).

## Next Steps

- See [README.md](../../README.md) for usage examples
- See [ARCHITECTURE.md](../../ARCHITECTURE.md) for architecture details
- See [CLAUDE.md](../../CLAUDE.md) for development guidelines
- See [docs/BACKUP_RECOVERY.md](../BACKUP_RECOVERY.md) for backup procedures
