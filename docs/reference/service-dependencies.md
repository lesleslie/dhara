# Druva Service Dependencies

## Overview

Druva is a **standalone persistence service** that can operate independently or integrate with the broader Mahavishnu ecosystem.

## Required Services

**None**

Druva is a self-contained persistence system that requires no external services for basic operation:

- No database server required (uses file-based storage by default)
- No message broker required
- No external dependencies for core functionality

## Optional Integrations

### Mahavishnu (Orchestrator)

**Role**: Storage backend for orchestration workflows

Druva can serve as the persistence layer for Mahavishnu orchestration workflows:

```python
# In Mahavishnu configuration
from druva import Connection, FileStorage

# Druva provides persistent storage for workflow state
connection = Connection(FileStorage("mahavishnu_workflows.druva"))
root = connection.get_root()
root["workflows"] = {}
```

**Integration Benefits**:

- ACID guarantees for workflow state
- Transactional workflow execution
- Persistent workflow history
- Optimized for read-heavy workflow queries

### Storage Backends

Druva supports multiple storage backends:

**File Storage (Default)**

```bash
# No external service needed
druva -s --file data.druva
```

**SQLite Storage**

```python
from druva.storage import SqliteStorage
# Uses SQLite3 (included in Python standard library)
connection = Connection(SqliteStorage("data.db"))
```

**Client/Server Mode**

```bash
# Server (standalone)
druva -s --port 2973

# Client (connects to server)
from druva.storage import ClientStorage
connection = Connection(ClientStorage(address=("localhost", 2973)))
```

### MCP (Model Context Protocol)

**Role**: AI/agent workflow integration

Druva includes an MCP server for modern AI/agent workflows:

```python
from druva.mcp import create_server

server = create_server(config="druva.yaml")
server.run()
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

Druva uses Oneiric for configuration management:

```yaml
# druva.yaml
storage:
  backend: file
  path: /var/lib/druva/data.druva

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

### Secret Management

**Role**: Secure credential storage

Druva integrates with Oneiric for secret management:

**Supported Backends**:

- Environment variables (default)
- HashiCorp Vault (optional)
- AWS Secrets Manager (optional)
- In-memory (development only)

```bash
# Environment variables (recommended)
export DRUVA_SECRET_KEY="your-secret-key"
export DRUVA_DB_PASSWORD="database-password"
```

### Logging Infrastructure

**Role**: Structured logging and monitoring

Druva uses structured logging via Oneiric:

```yaml
# druva.yaml
logging:
  level: INFO
  format: structured
  outputs:
    - type: console
      format: json
    - type: file
      path: /var/log/druva/druva.log
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
druva -c --file data.druva
```

### Client/Server Mode

**Network protocols**:

- TCP (default port: 2972)
- Unix domain sockets (local only)

```bash
# TCP server
druva -s --host 0.0.0.0 --port 2973

# Unix domain socket
druva -s --socket /var/run/druva.sock
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

# Testing tools
pytest          # Test framework
pytest-cov      # Coverage reporting
hypothesis      # Property-based testing
```

### Code Quality

```bash
# Quality tools (via Crackerjack)
python -m crackerjack check

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
pip install druva
druva -s --file /var/lib/druva/data.druva
```

### Client/Server Deployment

**Requirements**:

- Network connectivity
- Server: TCP port 2972 (or custom)
- Client: Server address

```bash
# Server
druva -s --host 0.0.0.0 --port 2973

# Client (on remote machine)
from druva.storage import ClientStorage
connection = Connection(ClientStorage(address=("server.example.com", 2973)))
```

### Container Deployment

**Docker example**:

```dockerfile
FROM python:3.13

RUN pip install druva

VOLUME /var/lib/druva
EXPOSE 2972

CMD ["druva", "-s", "--file", "/var/lib/druva/data.druva"]
```

**Kubernetes example**:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: druva
spec:
  serviceName: druva
  replicas: 1
  selector:
    matchLabels:
      app: druva
  template:
    metadata:
      labels:
        app: druva
    spec:
      containers:
      - name: druva
        image: druva:latest
        ports:
        - containerPort: 2972
        volumeMounts:
        - name: data
          mountPath: /var/lib/druva
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

Druva is designed to operate with **zero external dependencies**:

```python
# Complete standalone operation
from druva import Connection, Persistent

class User(Persistent):
    def __init__(self, name):
        self.name = name

# No external services needed
connection = Connection("users.druva")
root = connection.get_root()
root["users"] = {}
root["users"]["alice"] = User("Alice")
connection.commit()
```

## Integration Benefits

When integrated with the ecosystem, Druva provides:

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

Druva supports various backup strategies:

### File Storage

```bash
# Hot backup (safe to copy while running)
cp data.druva data.druva.backup

# Pack before backup (removes garbage)
druva -p --file data.druva
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
