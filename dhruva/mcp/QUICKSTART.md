# Durus MCP Authentication Quick Start

## 1. Generate Your First Token

```bash
# Create a read-only token for your app
python deployment/scripts/generate_token.py \
  --token-id myapp \
  --role readonly

# Create an admin token (use carefully!)
python deployment/scripts/generate_token.py \
  --token-id admin \
  --role admin \
  --expires-in 2592000  # 30 days
```

**IMPORTANT**: Save the token securely! You won't see it again.

## 2. Configure Your Server

Edit `/etc/durus/production.yaml`:

```yaml
security:
  authentication:
    enabled: true
    method: token
    token:
      tokens_file: /etc/durus/tokens.json
      require_auth: true
```

## 3. Use the Token in Your Code

```python
from durus.mcp.server import DurusMCPServer
from durus.mcp.auth import AuthContext, TokenAuth, AuthMiddleware

# Setup authentication
token_auth = TokenAuth(tokens_file="/etc/durus/tokens.json")
auth_middleware = AuthMiddleware(token_auth=token_auth)

# Create server
server = DurusMCPServer(
    storage_path="/data/durus.durus",
    auth_middleware=auth_middleware
)

# Call tools with authentication
auth_context = AuthContext(token="YOUR_TOKEN_HERE")

result = await server.call_tool(
    tool_name="durus_get",
    arguments={"key": "my_key"},
    auth_context=auth_context
)
```

## 4. Token Management Commands

```bash
# List all tokens
python deployment/scripts/generate_token.py --list

# Revoke a token
python deployment/scripts/generate_token.py --token-id myapp --revoke

# Validate tokens file
python deployment/scripts/generate_token.py --validate

# Export as environment variable
python deployment/scripts/generate_token.py --token-id myapp --export-env
```

## 5. Common Patterns

### Read-Only Token (Safe for clients)

```bash
python deployment/scripts/generate_token.py \
  --token-id client_app \
  --role readonly \
  --rate-limit 100
```

### Read-Write Token (For data operations)

```bash
python deployment/scripts/generate_token.py \
  --token-id data_service \
  --role readwrite \
  --rate-limit 1000
```

### Admin Token (For maintenance)

```bash
python deployment/scripts/generate_token.py \
  --token-id admin \
  --role admin \
  --expires-in 86400  # 1 day, rotate frequently
```

### Service Token (No expiration)

```bash
python deployment/scripts/generate_token.py \
  --token-id background_worker \
  --role readwrite
  # No --expires-in = no expiration
```

## 6. Troubleshooting

### "Authentication failed"

- Check token is correct: `--list`
- Verify token file path
- Ensure `authentication.enabled: true`

### "Permission denied"

- Check token role: `--list`
- Verify role has required permission
- Upgrade role if needed: revoke and recreate

### "Rate limit exceeded"

- Wait 1 minute for window to reset
- Increase rate limit: revoke and recreate with higher `--rate-limit`
- Use multiple tokens for high throughput

## 7. Security Checklist

- [ ] Authentication enabled in production
- [ ] Strong, randomly generated tokens
- [ ] Appropriate token expiration
- [ ] Rate limiting configured
- [ ] Audit logging enabled
- [ ] Regular token rotation
- [ ] Secure token file permissions (0600)
- [ ] Tokens never committed to git
- [ ] Admin tokens have short expiration
- [ ] Read-only tokens for clients

## 8. Permissions by Role

| Operation | Readonly | Readwrite | Admin |
|-----------|----------|-----------|-------|
| Read data | ✅ | ✅ | ✅ |
| List keys | ✅ | ✅ | ✅ |
| Write data | ❌ | ✅ | ✅ |
| Delete data | ❌ | ✅ | ✅ |
| Create checkpoint | ❌ | ❌ | ✅ |
| Restore checkpoint | ❌ | ❌ | ✅ |

## 9. File Locations

| File | Location |
|------|----------|
| Tokens | `/etc/durus/tokens.json` |
| Config | `/etc/durus/production.yaml` |
| Audit log | `/var/log/durus/audit.log` |
| Token generator | `deployment/scripts/generate_token.py` |

## 10. Quick API Reference

```python
# Authentication
from durus.mcp.auth import (
    TokenAuth,           # Token-based auth
    HMACAuth,            # HMAC-based auth
    EnvironmentAuth,     # Environment variable auth
    AuthMiddleware,      # Auth middleware
    AuthContext,         # Request auth context
    Role,                # Role enum
    Permission,          # Permission enum
)

# Servers
from durus.mcp.server import DurusMCPServer
from durus.mcp.oneiric_server import OneiricMCPServer

# Create auth context
auth_context = AuthContext(
    token="your_token",           # For token auth
    hmac_signature="sig",         # For HMAC auth
    timestamp="1234567890",       # For HMAC auth
    client_id="client1",          # For HMAC auth
)

# Call tool with auth
result = await server.call_tool(
    tool_name="durus_get",
    arguments={"key": "my_key"},
    auth_context=auth_context
)
```

## Need Help?

- Full documentation: `/Users/les/Projects/durus/durus/mcp/README.md`
- Implementation details: `/Users/les/Projects/durus/IMPLEMENTATION_SUMMARY.md`
- Test examples: `/Users/les/Projects/durus/test/test_mcp_auth.py`
