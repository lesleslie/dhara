# Durus MCP Authentication and Authorization

## Overview

This module provides comprehensive authentication and authorization for Durus MCP (Model Context Protocol) servers, enabling secure AI assistant access to Durus persistent object databases.

## Features

### Authentication Methods

1. **Token-based Authentication**
   - Bearer token authentication
   - SHA-256 hashed token storage
   - Constant-time token comparison (timing attack resistant)
   - Token expiration and revocation
   - Per-token rate limiting

2. **HMAC-based Authentication**
   - HMAC-SHA256 signature verification
   - Request payload signing
   - Timestamp validation to prevent replay attacks
   - Shared secret management

3. **Environment-based Authentication**
   - Environment variable authentication
   - Ideal for local development
   - Configurable role assignment

4. **mTLS Authentication (Future)**
   - Certificate-based authentication
   - Client certificate validation

### Authorization Model

- **Role-based Access Control (RBAC)**
  - `readonly`: Read and list operations
  - `readwrite`: Read, list, write, and delete operations
  - `admin`: Full administrative access including checkpoints and restores

- **Granular Permissions**
  - `READ`: Read data
  - `WRITE`: Write data
  - `DELETE`: Delete data
  - `LIST`: List keys/objects
  - `CHECKPOINT`: Create checkpoints
  - `RESTORE`: Restore from checkpoints
  - `ADMIN`: Administrative operations

### Security Features

1. **Rate Limiting**
   - Per-token rate limiting (requests per minute)
   - Token bucket algorithm
   - Configurable limits per token

2. **Audit Logging**
   - Authentication events
   - Authorization events
   - Data access logging (optional)
   - Configurable retention policy

3. **Secure Token Storage**
   - Tokens stored as SHA-256 hashes
   - Never log tokens or secrets
   - Secure random generation
   - File-based persistence with secure permissions

4. **Token Management**
   - Token expiration
   - Token revocation
   - Token validation
   - Last used tracking

## Installation

The MCP authentication system is included with Durus 5.0. No additional installation required.

## Configuration

### Production Configuration

Edit `/etc/durus/production.yaml`:

```yaml
security:
  authentication:
    enabled: true
    method: token

    token:
      tokens_file: /etc/durus/tokens.json
      require_auth: true
      default_role: readonly
      default_rate_limit: 1000

  authorization:
    enabled: true

    rbac:
      roles:
        readonly:
          permissions:
            - read
            - list

        readwrite:
          permissions:
            - read
            - list
            - write
            - delete

        admin:
          permissions:
            - read
            - list
            - write
            - delete
            - checkpoint
            - restore
            - admin

  audit:
    enabled: true
    file: /var/log/durus/audit.log
    log_auth_events: true
    log_authz_events: true
    retention_days: 90
```

## Usage

### Generating Tokens

Use the token generation utility:

```bash
# Generate a read-only token
python deployment/scripts/generate_token.py \
  --token-id myapp \
  --role readonly \
  --tokens-file /etc/durus/tokens.json

# Generate an admin token with 30-day expiration
python deployment/scripts/generate_token.py \
  --token-id admin \
  --role admin \
  --expires-in 2592000 \
  --tokens-file /etc/durus/tokens.json

# List all tokens
python deployment/scripts/generate_token.py \
  --list \
  --tokens-file /etc/durus/tokens.json

# Revoke a token
python deployment/scripts/generate_token.py \
  --token-id myapp \
  --revoke \
  --tokens-file /etc/durus/tokens.json

# Validate tokens file
python deployment/scripts/generate_token.py \
  --validate \
  --tokens-file /etc/durus/tokens.json
```

### Using Tokens in MCP Clients

When connecting to an MCP server, include the token in the Authorization header:

```python
from durus.mcp.auth import AuthContext

# Create authentication context
auth_context = AuthContext(
    token="your_token_here"
)

# Call MCP tool with authentication
result = await server.call_tool(
    tool_name="durus_get",
    arguments={"key": "my_key"},
    auth_context=auth_context
)
```

### Programmatic Usage

```python
from durus.mcp.auth import TokenAuth, Role, AuthMiddleware
from durus.mcp.server import DurusMCPServer

# Create token authentication
token_auth = TokenAuth(
    tokens_file="/etc/durus/tokens.json",
    require_auth=True,
    default_role=Role.READONLY
)

# Add a token programmatically
token_auth.add_token(
    token_id="myapp",
    token="secret_token_here",
    role=Role.READWRITE,
    expires_in=86400  # 24 hours
)

# Create authentication middleware
auth_middleware = AuthMiddleware(token_auth=token_auth)

# Create MCP server with authentication
server = DurusMCPServer(
    storage_path="/data/durus.durus",
    auth_middleware=auth_middleware,
    enable_auth=True
)
```

## MCP Tools

### Durus MCP Server Tools

| Tool | Permission Required | Description |
|------|-------------------|-------------|
| `durus_connect` | READ | Connect to Durus storage |
| `durus_get` | READ | Get a value by key |
| `durus_set` | WRITE | Set a value |
| `durus_list` | LIST | List all keys |
| `durus_delete` | DELETE | Delete a key |
| `durus_checkpoint` | CHECKPOINT | Create a checkpoint |
| `durus_restore_checkpoint` | RESTORE | Restore from checkpoint |

### Oneiric MCP Server Tools

| Tool | Permission Required | Description |
|------|-------------------|-------------|
| `oneiric_register_adapter` | WRITE | Register a new adapter |
| `oneiric_get_adapter` | READ | Get adapter information |
| `oneiric_list_adapters` | LIST | List all adapters |
| `oneiric_search_adapters` | READ | Search adapters by capability |

## Security Best Practices

### Production Deployment

1. **Always enable authentication in production**
   ```yaml
   security:
     authentication:
       enabled: true
   ```

2. **Use strong, randomly generated tokens**
   ```bash
   # Use the token generation utility
   python deployment/scripts/generate_token.py --token-id myapp --role admin
   ```

3. **Set appropriate token expiration**
   ```bash
   # Admin tokens: 30 days
   # App tokens: 90 days
   # Service tokens: No expiration (rotate manually)
   ```

4. **Configure rate limiting**
   ```yaml
   token:
     default_rate_limit: 1000  # Adjust based on usage
   ```

5. **Enable audit logging**
   ```yaml
   audit:
     enabled: true
     log_auth_events: true
     log_authz_events: true
   ```

6. **Secure token storage**
   ```bash
   # Ensure proper file permissions
   chmod 600 /etc/durus/tokens.json
   chown durus:durus /etc/durus/tokens.json
   ```

7. **Regular token rotation**
   ```bash
   # Revoke old token
   python deployment/scripts/generate_token.py --token-id old_token --revoke

   # Generate new token
   python deployment/scripts/generate_token.py --token-id new_token --role admin
   ```

### Development Environment

For local development, you can use environment-based authentication:

```python
from durus.mcp.auth import EnvironmentAuth

export DURUS_AUTH_TOKEN="dev_token"

# In code
env_auth = EnvironmentAuth(
    env_var="DURUS_AUTH_TOKEN",
    require_auth=False,  # Not required for dev
    role=Role.ADMIN
)
```

## API Reference

### TokenAuth

```python
class TokenAuth:
    def __init__(
        self,
        tokens: Optional[Dict[str, TokenInfo]] = None,
        tokens_file: Optional[str] = None,
        require_auth: bool = True,
        default_role: Role = Role.READONLY
    )

    def add_token(
        self,
        token_id: str,
        token: str,
        role: Role = Role.READONLY,
        expires_in: Optional[int] = None,
        rate_limit: int = 1000,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TokenInfo

    def revoke_token(self, token_id: str) -> bool

    def authenticate(self, token: str) -> AuthResult

    def load_tokens(self, filepath: str) -> None

    def save_tokens(self, filepath: Optional[str] = None) -> None
```

### AuthMiddleware

```python
class AuthMiddleware:
    def __init__(
        self,
        token_auth: Optional[TokenAuth] = None,
        hmac_auth: Optional[HMACAuth] = None,
        env_auth: Optional[EnvironmentAuth] = None,
        require_auth: bool = True,
        audit_log: Optional[logging.Logger] = None
    )

    def authenticate(self, context: AuthContext) -> AuthResult

    def check_permission(
        self,
        auth_result: AuthResult,
        required_permission: Permission
    ) -> bool

    def require_permission(self, permission: Permission) -> Callable
```

### Permission Enum

```python
class Permission(Enum):
    READ = "read"
    LIST = "list"
    WRITE = "write"
    DELETE = "delete"
    CHECKPOINT = "checkpoint"
    RESTORE = "restore"
    ADMIN = "admin"
```

### Role Enum

```python
class Role(Enum):
    READONLY = "readonly"
    READWRITE = "readwrite"
    ADMIN = "admin"
```

## Testing

Run the authentication tests:

```bash
# Run all tests
python -m pytest test/test_mcp_auth.py -v

# Run specific test class
python -m pytest test/test_mcp_auth.py::TestTokenAuth -v

# Run with coverage
python -m pytest test/test_mcp_auth.py --cov=durus/mcp/auth --cov=durus/mcp/middleware
```

## Troubleshooting

### Authentication Failed

**Problem**: `Authentication failed: invalid or expired token`

**Solutions**:
1. Verify token is correct: `python deployment/scripts/generate_token.py --list`
2. Check token hasn't expired
3. Ensure token hasn't been revoked
4. Verify tokens file path is correct

### Permission Denied

**Problem**: `Permission denied for tool 'durus_set'`

**Solutions**:
1. Check token role: `python deployment/scripts/generate_token.py --list`
2. Verify role has required permission
3. Upgrade token role if needed

### Rate Limit Exceeded

**Problem**: `Rate limit exceeded`

**Solutions**:
1. Wait for rate limit window to expire (1 minute)
2. Increase token rate limit
3. Use multiple tokens for high-throughput applications

## File Structure

```
durus/mcp/
├── __init__.py           # Package initialization
├── auth.py               # Authentication and authorization classes
├── middleware.py         # MCP middleware
├── server.py             # Durus MCP server implementation
└── oneiric_server.py     # Oneiric-compatible MCP server

deployment/
├── config/
│   └── production.yaml   # Production configuration
└── scripts/
    └── generate_token.py # Token generation utility

test/
└── test_mcp_auth.py      # Comprehensive test suite
```

## License

This authentication system is part of Durus 5.0 and is released under the same license.

## Support

For issues, questions, or contributions, please refer to the main Durus project repository.
