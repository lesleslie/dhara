"""
Cloud storage adapters for Durus backups.

This module provides adapters for:
- Amazon S3
- Google Cloud Storage
- Azure Blob Storage
- Local filesystem

All adapters are implemented via Oneiric's unified storage adapter system.
"""

from __future__ import annotations

from typing import Any

from oneiric.adapters.storage import (
    AzureBlobStorageAdapter,
    AzureBlobStorageSettings,
    GCSStorageAdapter,
    GCSStorageSettings,
    LocalStorageAdapter,
    LocalStorageSettings,
    S3StorageAdapter,
    S3StorageSettings,
)

# Re-export Oneiric adapters for backward compatibility
__all__ = [
    "S3StorageAdapter",
    "S3StorageSettings",
    "GCSStorageAdapter",
    "GCSStorageSettings",
    "AzureBlobStorageAdapter",
    "AzureBlobStorageSettings",
    "LocalStorageAdapter",
    "LocalStorageSettings",
    "StorageAdapter",
    "StorageAdapterFactory",
    "StorageFactory",
    "create_storage_adapter",
    "S3Storage",
    "GCSStorage",
    "AzureBlobStorage",
]

# For backward compatibility with old names
S3Storage = S3StorageAdapter
GCSStorage = GCSStorageAdapter
AzureBlobStorage = AzureBlobStorageAdapter
StorageAdapter = S3StorageAdapter  # Base interface reference


_PROVIDERS: dict[str, tuple[type, type]] = {
    "s3": (S3StorageAdapter, S3StorageSettings),
    "gcs": (GCSStorageAdapter, GCSStorageSettings),
    "google": (GCSStorageAdapter, GCSStorageSettings),
    "google-cloud": (GCSStorageAdapter, GCSStorageSettings),
    "azure": (AzureBlobStorageAdapter, AzureBlobStorageSettings),
    "azure-blob": (AzureBlobStorageAdapter, AzureBlobStorageSettings),
    "local": (LocalStorageAdapter, LocalStorageSettings),
}


def create_storage_adapter(provider: str, *, settings: Any) -> Any:
    """Create a storage adapter instance from a provider name and settings object.

    Args:
        provider: The storage provider name (e.g., "s3", "gcs", "azure", "local").
        settings: A Pydantic settings object (e.g., S3StorageSettings).

    Returns:
        An instance of the appropriate storage adapter.

    Raises:
        ValueError: If the provider is not supported.
    """
    key = provider.lower()
    if key not in _PROVIDERS:
        raise ValueError(
            f"Unsupported storage provider: {provider!r}. Choose from: {sorted(_PROVIDERS)}"
        )
    adapter_cls, _ = _PROVIDERS[key]
    return adapter_cls(settings)


class StorageAdapterFactory:
    """Factory for creating storage adapters.

    Provides a static method to instantiate storage adapters from provider names
    and keyword arguments. This class maintains backward compatibility with the
    previous API.
    """

    @staticmethod
    def create_storage(provider: str, **kwargs: Any) -> Any:
        """Create a storage adapter based on provider and kwargs.

        Args:
            provider: The storage provider name (e.g., "s3", "gcs", "azure", "local").
            **kwargs: Provider-specific configuration arguments.

        Returns:
            An instance of the appropriate storage adapter.

        Raises:
            ValueError: If the provider is not supported.

        Examples:
            >>> # S3 adapter
            >>> storage = StorageAdapterFactory.create_storage(
            ...     "s3",
            ...     bucket="my-bucket",
            ...     region="us-east-1"
            ... )
            >>> # GCS adapter
            >>> storage = StorageAdapterFactory.create_storage(
            ...     "gcs",
            ...     bucket="my-bucket",
            ...     project_id="my-project"
            ... )
            >>> # Azure adapter
            >>> storage = StorageAdapterFactory.create_storage(
            ...     "azure",
            ...     connection_string="...",
            ...     container="my-container"
            ... )
        """
        key = provider.lower()
        if key not in _PROVIDERS:
            raise ValueError(
                f"Unsupported storage provider: {provider!r}. Choose from: {sorted(_PROVIDERS)}"
            )
        adapter_cls, settings_cls = _PROVIDERS[key]
        settings = settings_cls(**kwargs)
        return adapter_cls(settings)


# Backward compatibility alias for StorageAdapterFactory
StorageFactory = StorageAdapterFactory
