#!/usr/bin/env python3
"""
Token Generation Utility for Durus MCP Servers

This script generates and manages authentication tokens for Durus MCP servers.
Tokens are stored as SHA-256 hashes and include role-based permissions.

Usage:
    # Generate a new read-only token
    python generate_token.py --token-id myapp --role readonly

    # Generate a write token with expiration
    python generate_token.py --token-id admin --role admin --expires-in 86400

    # Revoke a token
    python generate_token.py --token-id myapp --revoke

    # List all tokens
    python generate_token.py --list

    # Export token as environment variable
    python generate_token.py --token-id myapp --export-env
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path to import durus
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from druva.mcp.auth import generate_token

# Default paths
DEFAULT_TOKENS_FILE = "/etc/durus/tokens.json"
DEFAULT_OUTPUT_DIR = Path("/etc/durus")


def print_token_safe(token: str, token_id: str):
    """
    Print token with safety warnings

    Args:
        token: The token string
        token_id: Token identifier
    """
    print("\n" + "=" * 70)
    print("  SECURITY WARNING: Store this token securely!")
    print("  This is the ONLY time you will see it.")
    print("=" * 70)
    print(f"\n  Token ID:    {token_id}")
    print(f"  Token:       {token}")
    print("\n  Use this token in the Authorization header:")
    print(f"  Authorization: Bearer {token}")
    print("\n" + "=" * 70 + "\n")


def hash_token(token: str) -> str:
    """Hash a token using SHA-256"""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_new_token(
    token_id: str,
    role: str,
    expires_in: Optional[int] = None,
    rate_limit: int = 1000,
    tokens_file: str = DEFAULT_TOKENS_FILE,
    metadata: Optional[dict] = None,
) -> str:
    """
    Generate a new authentication token

    Args:
        token_id: Unique identifier for the token
        role: Role (readonly, readwrite, admin)
        expires_in: Expiration time in seconds (None = no expiration)
        rate_limit: Rate limit (requests per minute)
        tokens_file: Path to tokens file
        metadata: Additional metadata

    Returns:
        Generated token
    """
    # Load existing tokens
    tokens_data = {}
    if os.path.exists(tokens_file):
        with open(tokens_file) as f:
            tokens_data = json.load(f)

    # Check if token already exists
    if "tokens" in tokens_data and token_id in tokens_data["tokens"]:
        print(f"Error: Token '{token_id}' already exists", file=sys.stderr)
        print("Use --revoke to revoke the existing token first", file=sys.stderr)
        sys.exit(1)

    # Generate token
    token = generate_token(32)
    token_hash = hash_token(token)

    # Create token info
    token_info = {
        "token_hash": token_hash,
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
        "rate_limit": rate_limit,
        "metadata": metadata or {},
    }

    # Add expiration if specified
    if expires_in:
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        token_info["expires_at"] = expires_at.isoformat()

    # Save to tokens file
    if "tokens" not in tokens_data:
        tokens_data["tokens"] = {}

    tokens_data["tokens"][token_id] = token_info

    # Ensure directory exists
    os.makedirs(os.path.dirname(tokens_file), exist_ok=True)

    # Write tokens file
    with open(tokens_file, "w") as f:
        json.dump(tokens_data, f, indent=2)

    # Set secure permissions
    os.chmod(tokens_file, 0o600)

    print(f"Token '{token_id}' created successfully")
    print(f"Tokens file: {tokens_file}")

    return token


def revoke_token(
    token_id: str,
    tokens_file: str = DEFAULT_TOKENS_FILE,
) -> bool:
    """
    Revoke a token

    Args:
        token_id: Token identifier
        tokens_file: Path to tokens file

    Returns:
        True if revoked
    """
    if not os.path.exists(tokens_file):
        print(f"Error: Tokens file not found: {tokens_file}", file=sys.stderr)
        sys.exit(1)

    with open(tokens_file) as f:
        tokens_data = json.load(f)

    if "tokens" not in tokens_data or token_id not in tokens_data["tokens"]:
        print(f"Error: Token '{token_id}' not found", file=sys.stderr)
        sys.exit(1)

    # Mark as revoked
    tokens_data["tokens"][token_id]["is_revoked"] = True
    tokens_data["tokens"][token_id]["revoked_at"] = datetime.utcnow().isoformat()

    # Write back
    with open(tokens_file, "w") as f:
        json.dump(tokens_data, f, indent=2)

    print(f"Token '{token_id}' revoked successfully")
    return True


def list_tokens(tokens_file: str = DEFAULT_TOKENS_FILE) -> None:
    """
    List all tokens

    Args:
        tokens_file: Path to tokens file
    """
    if not os.path.exists(tokens_file):
        print(f"No tokens file found: {tokens_file}")
        return

    with open(tokens_file) as f:
        tokens_data = json.load(f)

    if "tokens" not in tokens_data or not tokens_data["tokens"]:
        print("No tokens defined")
        return

    print("\n" + "=" * 70)
    print("  Durus MCP Tokens")
    print("=" * 70)

    for token_id, info in tokens_data["tokens"].items():
        print(f"\n  Token ID: {token_id}")
        print(f"    Role:       {info['role']}")
        print(f"    Created:    {info['created_at']}")
        print(f"    Rate Limit: {info.get('rate_limit', 1000)} req/min")
        print(f"    Status:     {'REVOKED' if info.get('is_revoked') else 'ACTIVE'}")

        if info.get("expires_at"):
            expires_at = datetime.fromisoformat(info["expires_at"])
            print(f"    Expires:    {info['expires_at']}")
            if expires_at < datetime.utcnow():
                print("    WARNING:   Token is expired!")

    print("\n" + "=" * 70 + "\n")


def export_env_variable(
    token_id: str,
    tokens_file: str = DEFAULT_TOKENS_FILE,
    export_format: str = "bash",
) -> None:
    """
    Export token as environment variable

    Args:
        token_id: Token identifier
        tokens_file: Path to tokens file
        export_format: Export format (bash, json, dotenv)
    """
    if not os.path.exists(tokens_file):
        print(f"Error: Tokens file not found: {tokens_file}", file=sys.stderr)
        sys.exit(1)

    with open(tokens_file) as f:
        tokens_data = json.load(f)

    if "tokens" not in tokens_data or token_id not in tokens_data["tokens"]:
        print(f"Error: Token '{token_id}' not found", file=sys.stderr)
        sys.exit(1)

    token_info = tokens_data["tokens"][token_id]

    if export_format == "bash":
        print(f'\nexport DURUS_TOKEN_ID="{token_id}"')
        print(f'export DURUS_TOKEN_HASH="{token_info["token_hash"]}"')
        print("\n# Add to ~/.bashrc or ~/.zshrc")

    elif export_format == "json":
        print(json.dumps({"token_id": token_id, **token_info}, indent=2))

    elif export_format == "dotenv":
        print(f"\nDURUS_TOKEN_ID={token_id}")
        print(f"DURUS_TOKEN_HASH={token_info['token_hash']}")
        print("\n# Add to .env file")


def validate_tokens(tokens_file: str = DEFAULT_TOKENS_FILE) -> None:
    """
    Validate tokens file and check for issues

    Args:
        tokens_file: Path to tokens file
    """
    if not os.path.exists(tokens_file):
        print(f"Error: Tokens file not found: {tokens_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating tokens file: {tokens_file}\n")

    with open(tokens_file) as f:
        try:
            tokens_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)

    issues = []

    if "tokens" not in tokens_data:
        issues.append("Missing 'tokens' key")
    else:
        for token_id, info in tokens_data["tokens"].items():
            # Check required fields
            required_fields = ["token_hash", "role", "created_at"]
            for field in required_fields:
                if field not in info:
                    issues.append(f"Token '{token_id}': missing '{field}'")

            # Check role validity
            if info.get("role") not in ["readonly", "readwrite", "admin"]:
                issues.append(f"Token '{token_id}': invalid role '{info.get('role')}'")

            # Check expiration
            if info.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(info["expires_at"])
                    if expires_at < datetime.utcnow() and not info.get("is_revoked"):
                        issues.append(f"Token '{token_id}': expired but not revoked")
                except ValueError:
                    issues.append(f"Token '{token_id}': invalid expires_at format")

    if issues:
        print("Issues found:\n")
        for issue in issues:
            print(f"  - {issue}")
        print(f"\nFound {len(issues)} issue(s)")
        sys.exit(1)
    else:
        print("No issues found!")
        print(f"Tokens file is valid with {len(tokens_data['tokens'])} token(s)")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate and manage authentication tokens for Durus MCP servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a new read-only token
  %(prog)s --token-id myapp --role readonly

  # Generate an admin token that expires in 30 days
  %(prog)s --token-id admin --role admin --expires-in 2592000

  # Revoke a token
  %(prog)s --token-id myapp --revoke

  # List all tokens
  %(prog)s --list

  # Validate tokens file
  %(prog)s --validate
        """,
    )

    parser.add_argument(
        "--token-id",
        help="Token identifier (required for generate/revoke)",
    )

    parser.add_argument(
        "--role",
        choices=["readonly", "readwrite", "admin"],
        help="Token role",
    )

    parser.add_argument(
        "--expires-in",
        type=int,
        help="Token expiration time in seconds (None = no expiration)",
    )

    parser.add_argument(
        "--rate-limit",
        type=int,
        default=1000,
        help="Rate limit (requests per minute, default: 1000)",
    )

    parser.add_argument(
        "--tokens-file",
        default=DEFAULT_TOKENS_FILE,
        help=f"Path to tokens file (default: {DEFAULT_TOKENS_FILE})",
    )

    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke the specified token",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all tokens",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate tokens file",
    )

    parser.add_argument(
        "--export-env",
        action="store_true",
        help="Export token as environment variable",
    )

    parser.add_argument(
        "--export-format",
        choices=["bash", "json", "dotenv"],
        default="bash",
        help="Export format (default: bash)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for tokens file (default: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()

    # Handle special actions
    if args.list:
        list_tokens(args.tokens_file)
        return

    if args.validate:
        validate_tokens(args.tokens_file)
        return

    # Revoke token
    if args.revoke:
        if not args.token_id:
            parser.error("--token-id required for --revoke")
        revoke_token(args.token_id, args.tokens_file)
        return

    # Export environment variable
    if args.export_env:
        if not args.token_id:
            parser.error("--token-id required for --export-env")
        export_env_variable(args.token_id, args.tokens_file, args.export_format)
        return

    # Generate new token
    if not args.token_id:
        parser.error("--token-id required")

    if not args.role:
        parser.error("--role required (choose from: readonly, readwrite, admin)")

    # Update tokens file path with output dir
    tokens_file = args.tokens_file
    if not os.path.isabs(tokens_file):
        tokens_file = os.path.join(args.output_dir, tokens_file)

    # Generate token
    token = generate_new_token(
        token_id=args.token_id,
        role=args.role,
        expires_in=args.expires_in,
        rate_limit=args.rate_limit,
        tokens_file=tokens_file,
    )

    # Display token
    print_token_safe(token, args.token_id)


if __name__ == "__main__":
    main()
