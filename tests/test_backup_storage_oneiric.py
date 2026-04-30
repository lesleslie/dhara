"""Tests for dhara.backup.storage -- Oneiric adapter delegation."""

from __future__ import annotations

import pytest

from dhara.backup.storage import (
    StorageAdapterFactory,
    create_storage_adapter,
    S3StorageAdapter,
    GCSStorageAdapter,
    AzureBlobStorageAdapter,
    LocalStorageAdapter,
)


class TestCreateStorageAdapterErrors:
    """Test error handling in create_storage_adapter."""

    def test_create_storage_adapter_raises_for_unknown_provider(self):
        """Unsupported provider should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported"):
            create_storage_adapter("ftp", settings={})

    def test_create_storage_adapter_case_insensitive(self):
        """Provider names should be case-insensitive."""
        from oneiric.adapters.storage import LocalStorageSettings

        settings = LocalStorageSettings()
        adapter = create_storage_adapter("LOCAL", settings=settings)
        assert isinstance(adapter, LocalStorageAdapter)


class TestStorageAdapterFactoryErrors:
    """Test error handling in StorageAdapterFactory."""

    def test_factory_raises_for_unknown_provider(self):
        """Unsupported provider should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported"):
            StorageAdapterFactory.create_storage("ftp")

    def test_factory_case_insensitive(self):
        """Provider names should be case-insensitive."""
        adapter = StorageAdapterFactory.create_storage("s3", bucket="test-bucket")
        assert isinstance(adapter, S3StorageAdapter)


class TestFactoryS3Creation:
    """Test S3 adapter creation via factory."""

    def test_factory_create_s3_basic(self):
        """Factory should create S3 adapter with minimal config."""
        adapter = StorageAdapterFactory.create_storage("s3", bucket="test-bucket")
        assert isinstance(adapter, S3StorageAdapter)

    def test_factory_create_s3_with_region(self):
        """Factory should pass region to S3 settings."""
        adapter = StorageAdapterFactory.create_storage(
            "s3", bucket="test-bucket", region="eu-west-1"
        )
        assert isinstance(adapter, S3StorageAdapter)

    def test_factory_create_s3_with_credentials(self):
        """Factory should accept S3 credentials."""
        adapter = StorageAdapterFactory.create_storage(
            "s3",
            bucket="test-bucket",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        assert isinstance(adapter, S3StorageAdapter)


class TestFactoryGCSCreation:
    """Test GCS adapter creation via factory."""

    def test_factory_create_gcs_basic(self):
        """Factory should create GCS adapter with bucket."""
        adapter = StorageAdapterFactory.create_storage("gcs", bucket="test-bucket")
        assert isinstance(adapter, GCSStorageAdapter)

    def test_factory_create_gcs_with_project(self):
        """Factory should pass project_id to GCS settings."""
        adapter = StorageAdapterFactory.create_storage(
            "gcs", bucket="test-bucket", project="my-project"
        )
        assert isinstance(adapter, GCSStorageAdapter)

    def test_factory_create_gcs_alias_google(self):
        """Factory should accept 'google' as GCS alias."""
        adapter = StorageAdapterFactory.create_storage("google", bucket="test-bucket")
        assert isinstance(adapter, GCSStorageAdapter)

    def test_factory_create_gcs_alias_google_cloud(self):
        """Factory should accept 'google-cloud' as GCS alias."""
        adapter = StorageAdapterFactory.create_storage(
            "google-cloud", bucket="test-bucket"
        )
        assert isinstance(adapter, GCSStorageAdapter)


class TestFactoryAzureCreation:
    """Test Azure adapter creation via factory."""

    def test_factory_create_azure_basic(self):
        """Factory should create Azure adapter with connection string."""
        adapter = StorageAdapterFactory.create_storage(
            "azure", container="test-container", connection_string="DefaultEndpointsProtocol=https;..."
        )
        assert isinstance(adapter, AzureBlobStorageAdapter)

    def test_factory_create_azure_alias_azure_blob(self):
        """Factory should accept 'azure-blob' as Azure alias."""
        adapter = StorageAdapterFactory.create_storage(
            "azure-blob", container="test-container", connection_string="DefaultEndpointsProtocol=https;..."
        )
        assert isinstance(adapter, AzureBlobStorageAdapter)


class TestFactoryLocalCreation:
    """Test local filesystem adapter creation via factory."""

    def test_factory_create_local_basic(self, tmp_path):
        """Factory should create local adapter with base path."""
        adapter = StorageAdapterFactory.create_storage(
            "local", base_path=str(tmp_path)
        )
        assert isinstance(adapter, LocalStorageAdapter)

    def test_factory_create_local_default(self):
        """Factory should create local adapter with defaults."""
        adapter = StorageAdapterFactory.create_storage("local")
        assert isinstance(adapter, LocalStorageAdapter)


class TestDirectCreationWithSettings:
    """Test direct adapter creation using create_storage_adapter with settings objects."""

    def test_create_s3_with_settings(self):
        """Direct creation with S3 settings object."""
        from oneiric.adapters.storage import S3StorageSettings

        settings = S3StorageSettings(bucket="test-bucket", region="us-west-2")
        adapter = create_storage_adapter("s3", settings=settings)
        assert isinstance(adapter, S3StorageAdapter)

    def test_create_gcs_with_settings(self):
        """Direct creation with GCS settings object."""
        from oneiric.adapters.storage import GCSStorageSettings

        settings = GCSStorageSettings(bucket="test-bucket", project="my-project")
        adapter = create_storage_adapter("gcs", settings=settings)
        assert isinstance(adapter, GCSStorageAdapter)

    def test_create_azure_with_settings(self):
        """Direct creation with Azure settings object."""
        from oneiric.adapters.storage import AzureBlobStorageSettings

        settings = AzureBlobStorageSettings(
            container="test-container",
            connection_string="DefaultEndpointsProtocol=https;...",
        )
        adapter = create_storage_adapter("azure", settings=settings)
        assert isinstance(adapter, AzureBlobStorageAdapter)

    def test_create_local_with_settings(self, tmp_path):
        """Direct creation with local storage settings object."""
        from oneiric.adapters.storage import LocalStorageSettings

        settings = LocalStorageSettings(base_path=tmp_path)
        adapter = create_storage_adapter("local", settings=settings)
        assert isinstance(adapter, LocalStorageAdapter)


class TestBackwardCompatibilityAliases:
    """Test backward compatibility alias names."""

    def test_s3storage_alias(self):
        """S3Storage should be an alias for S3StorageAdapter."""
        from dhara.backup.storage import S3Storage

        assert S3Storage is S3StorageAdapter

    def test_gcsstorage_alias(self):
        """GCSStorage should be an alias for GCSStorageAdapter."""
        from dhara.backup.storage import GCSStorage

        assert GCSStorage is GCSStorageAdapter

    def test_azureblobstorage_alias(self):
        """AzureBlobStorage should be an alias for AzureBlobStorageAdapter."""
        from dhara.backup.storage import AzureBlobStorage

        assert AzureBlobStorage is AzureBlobStorageAdapter
