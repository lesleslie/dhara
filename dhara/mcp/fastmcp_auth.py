from __future__ import annotations

"""FastMCP auth integration for the canonical Dhara server."""

from pathlib import Path

from fastmcp.server.auth.authorization import require_scopes
from fastmcp.server.auth.providers.jwt import AccessToken, TokenVerifier

from dhara.mcp.auth import Role, TokenAuth


ROLE_MAP: dict[str, Role] = {
    "readonly": Role.READONLY,
    "readwrite": Role.READWRITE,
    "admin": Role.ADMIN,
}


def tool_auth(*scopes: str):
    """Return a FastMCP auth check for the given scopes."""
    return require_scopes(*scopes)


class DharaTokenVerifier(TokenVerifier):
    """Adapter from Dhara token auth to FastMCP bearer-token auth."""

    def __init__(
        self,
        *,
        tokens_file: Path,
        require_auth: bool = True,
        default_role: Role = Role.READONLY,
        required_scopes: list[str] | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self.tokens_file = Path(tokens_file).expanduser()
        self.token_auth = TokenAuth(
            tokens_file=str(self.tokens_file),
            require_auth=require_auth,
            default_role=default_role,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token against the Dhara token store."""
        result = self.token_auth.authenticate(token)
        if not result.success:
            return None

        scopes = sorted(permission.value for permission in result.permissions)
        if result.role is not None:
            scopes.append(result.role.value)

        if self.required_scopes:
            token_scopes = set(scopes)
            if not set(self.required_scopes).issubset(token_scopes):
                return None

        expires_at = result.expires_at.timestamp() if result.expires_at else None

        return AccessToken(
            token=token,
            client_id=result.token_id or "dhara",
            scopes=scopes,
            expires_at=expires_at,
            claims={
                "token_id": result.token_id,
                "role": result.role.value if result.role else None,
                "permissions": sorted(permission.value for permission in result.permissions),
            },
        )


def build_token_verifier(
    *,
    enabled: bool,
    tokens_file: Path | None,
    require_auth: bool,
    default_role: str,
    required_scopes: list[str] | None = None,
) -> DharaTokenVerifier | None:
    """Build the canonical FastMCP token verifier from Dhara auth settings."""
    if not enabled:
        return None

    if tokens_file is None:
        raise ValueError("authentication enabled but no token file is configured")

    resolved_tokens_file = Path(tokens_file).expanduser()
    if not resolved_tokens_file.exists():
        raise ValueError(f"authentication token file not found: {resolved_tokens_file}")

    return DharaTokenVerifier(
        tokens_file=resolved_tokens_file,
        require_auth=require_auth,
        default_role=ROLE_MAP.get(default_role, Role.READONLY),
        required_scopes=required_scopes or [],
    )
