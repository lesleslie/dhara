"""Tests for dhara.backup.storage -- all adapter classes and StorageFactory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, call, patch

import pytest

from dhara.backup.storage import (
    AzureBlobStorage,
    GCSStorage,
    S3Storage,
    StorageAdapter,
    StorageFactory,
)


# ---------------------------------------------------------------------------
# StorageAdapter ABC
# ---------------------------------------------------------------------------


class TestStorageAdapterABC:
    """Verify StorageAdapter is abstract and enforces its interface."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            StorageAdapter()

    def test_abstract_methods(self):
        import inspect

        abstract_methods = StorageAdapter.__abstractmethods__
        expected = {
            "upload_file",
            "download_file",
            "upload_json",
            "download_json",
            "list_files",
            "delete_file",
        }
        assert abstract_methods == expected

    def test_concrete_subclass_must_implement_all(self):
        """A subclass that omits even one method cannot be instantiated."""
        PartialImpl = type(
            "PartialImpl",
            (StorageAdapter,),
            {
                "upload_file": lambda self, *a: True,
                "download_file": lambda self, *a: True,
                "upload_json": lambda self, *a: True,
                "download_json": lambda self, *a: None,
                "list_files": lambda self, *a: [],
            },
            # delete_file intentionally omitted
        )
        with pytest.raises(TypeError):
            PartialImpl()


# ---------------------------------------------------------------------------
# S3Storage
# ---------------------------------------------------------------------------


class TestS3StorageInit:
    """Test S3Storage construction and boto3 client setup."""

    @patch("dhara.backup.storage.S3Storage.__init__", return_value=None)
    def _make_s3(self, mock_init):
        """Bypass real __init__ to avoid boto3 import."""
        instance = S3Storage.__new__(S3Storage)
        return instance

    def test_import_error_when_boto3_missing(self):
        with patch.dict("sys.modules", {"boto3": None, "botocore": None, "botocore.exceptions": None}):
            with pytest.raises(ImportError, match="boto3 is required"):
                S3Storage(bucket_name="test")

    def test_init_with_credentials(self):
        """Verify boto3 client is created with access_key/secret_key when provided."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        fake_client_error = type("ClientError", (Exception,), {})

        with patch.dict(
            "sys.modules",
            {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock(ClientError=fake_client_error)},
        ):
            storage = S3Storage(
                bucket_name="my-bucket",
                region="eu-west-1",
                access_key="AKID",
                secret_key="SECRET",
            )

        assert storage.bucket_name == "my-bucket"
        assert storage.region == "eu-west-1"
        mock_boto3.client.assert_called_once_with(
            "s3",
            region_name="eu-west-1",
            aws_access_key_id="AKID",
            aws_secret_access_key="SECRET",
        )

    def test_init_with_endpoint_url(self):
        """Verify endpoint_url is forwarded to boto3 client."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        fake_client_error = type("ClientError", (Exception,), {})

        with patch.dict(
            "sys.modules",
            {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock(ClientError=fake_client_error)},
        ):
            storage = S3Storage(
                bucket_name="local-bucket",
                endpoint_url="http://minio:9000",
            )

        mock_boto3.client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://minio:9000",
        )

    def test_init_without_credentials(self):
        """Minimal init uses only region_name."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        fake_client_error = type("ClientError", (Exception,), {})

        with patch.dict(
            "sys.modules",
            {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock(ClientError=fake_client_error)},
        ):
            storage = S3Storage(bucket_name="bucket")

        mock_boto3.client.assert_called_once_with("s3", region_name="us-east-1")


def _make_s3_storage():
    """Build an S3Storage instance with mocked boto3 internals."""
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    fake_client_error = type("ClientError", (Exception,), {})

    with patch.dict(
        "sys.modules",
        {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock(ClientError=fake_client_error)},
    ):
        storage = S3Storage(bucket_name="test-bucket", region="us-east-1")
    return storage, mock_client, fake_client_error


class TestS3StorageUploadFile:
    def test_upload_success(self):
        storage, mock_client, _ = _make_s3_storage()
        result = storage.upload_file("/tmp/file.txt", "remote/file.txt")
        assert result is True
        mock_client.upload_file.assert_called_once_with(
            "/tmp/file.txt", "test-bucket", "remote/file.txt"
        )

    def test_upload_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "PutObject"
        )
        result = storage.upload_file("/tmp/file.txt", "remote/file.txt")
        assert result is False


class TestS3StorageDownloadFile:
    def test_download_success(self):
        storage, mock_client, _ = _make_s3_storage()
        result = storage.download_file("remote/file.txt", "/tmp/file.txt")
        assert result is True
        mock_client.download_file.assert_called_once_with(
            "test-bucket", "remote/file.txt", "/tmp/file.txt"
        )

    def test_download_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.download_file.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
        )
        result = storage.download_file("remote/file.txt", "/tmp/file.txt")
        assert result is False


class TestS3StorageUploadJson:
    def test_upload_json_success(self):
        storage, mock_client, _ = _make_s3_storage()
        data = {"key": "value", "count": 42}
        result = storage.upload_json(data, "config.json")
        assert result is True
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args
        assert call_kwargs.kwargs["Bucket"] == "test-bucket"
        assert call_kwargs.kwargs["Key"] == "config.json"
        assert call_kwargs.kwargs["ContentType"] == "application/json"
        body_bytes = call_kwargs.kwargs["Body"]
        assert json.loads(body_bytes.decode("utf-8")) == data

    def test_upload_json_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "PutObject"
        )
        result = storage.upload_json({"a": 1}, "f.json")
        assert result is False


class TestS3StorageDownloadJson:
    def test_download_json_success(self):
        storage, mock_client, _ = _make_s3_storage()
        expected = {"result": True, "items": [1, 2, 3]}
        body_stream = BytesIO(json.dumps(expected).encode("utf-8"))
        mock_client.get_object.return_value = {"Body": body_stream}

        result = storage.download_json("data.json")
        assert result == expected
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="data.json"
        )

    def test_download_json_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
        )
        result = storage.download_json("missing.json")
        assert result is None


class TestS3StorageListFiles:
    def test_list_files_success(self):
        storage, mock_client, _ = _make_s3_storage()
        now = datetime.now(timezone.utc)
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "backup/a.db", "Size": 1024, "LastModified": now},
                    {"Key": "backup/b.db", "Size": 2048, "LastModified": now},
                ]
            },
            {
                "Contents": [
                    {"Key": "backup/c.db", "Size": 512, "LastModified": now},
                ]
            },
        ]

        files = storage.list_files(prefix="backup/")
        assert len(files) == 3
        assert files[0]["key"] == "backup/a.db"
        assert files[0]["size"] == 1024
        assert files[1]["key"] == "backup/b.db"
        assert files[2]["key"] == "backup/c.db"
        mock_client.get_paginator.assert_called_once_with("list_objects_v2")
        mock_paginator.paginate.assert_called_once_with(
            Bucket="test-bucket", Prefix="backup/"
        )

    def test_list_files_empty(self):
        storage, mock_client, _ = _make_s3_storage()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{}]

        files = storage.list_files()
        assert files == []

    def test_list_files_page_without_contents(self):
        storage, mock_client, _ = _make_s3_storage()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"IsTruncated": False},
        ]

        files = storage.list_files()
        assert files == []

    def test_list_files_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "ListObjectsV2"
        )
        files = storage.list_files()
        assert files == []


class TestS3StorageDeleteFile:
    def test_delete_success(self):
        storage, mock_client, _ = _make_s3_storage()
        result = storage.delete_file("old/backup.db")
        assert result is True
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="old/backup.db"
        )

    def test_delete_failure(self):
        storage, mock_client, ClientError = _make_s3_storage()
        mock_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "DeleteObject"
        )
        result = storage.delete_file("old/backup.db")
        assert result is False


# ---------------------------------------------------------------------------
# GCSStorage
# ---------------------------------------------------------------------------


def _make_gcs_storage():
    """Build a GCSStorage with mocked google.cloud.storage."""
    mock_gcs_module = MagicMock()
    mock_client = MagicMock()
    mock_gcs_module.Client.return_value = mock_client
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    fake_gcs_error = type("GoogleCloudError", (Exception,), {})

    mock_google_cloud = MagicMock()
    # Ensure `from google.cloud import storage` returns our mock module
    mock_google_cloud.storage = mock_gcs_module

    with patch.dict(
        "sys.modules",
        {
            "google": MagicMock(cloud=mock_google_cloud),
            "google.cloud": mock_google_cloud,
            "google.cloud.storage": mock_gcs_module,
            "google.oauth2": MagicMock(),
            "google.oauth2.service_account": MagicMock(),
            "google.cloud.exceptions": MagicMock(GoogleCloudError=fake_gcs_error),
        },
    ):
        storage = GCSStorage(bucket_name="gcs-bucket", project_id="proj-1")
    return storage, mock_bucket, mock_client, fake_gcs_error


class TestGCSStorageInit:
    def test_import_error_when_google_cloud_missing(self):
        with patch.dict(
            "sys.modules",
            {"google": None, "google.cloud": None, "google.cloud.storage": None, "google.cloud.exceptions": None},
        ):
            with pytest.raises(ImportError, match="google-cloud-storage is required"):
                GCSStorage(bucket_name="bucket")

    def test_basic_init(self):
        storage, mock_bucket, mock_gcs_client, _ = _make_gcs_storage()
        assert storage.bucket_name == "gcs-bucket"
        # The GCS constructor calls Client().bucket("gcs-bucket")
        mock_gcs_client.bucket.assert_called_once_with("gcs-bucket")

    def test_init_with_credentials_path(self):
        """Verify credentials_path triggers service_account loading.

        Note: The source code references `service_account` without importing it
        inside __init__. This test injects the name into the module namespace to
        confirm the intended behavior.
        """
        import dhara.backup.storage as storage_module

        mock_gcs_module = MagicMock()
        mock_client = MagicMock()
        mock_gcs_module.Client.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        fake_gcs_error = type("GoogleCloudError", (Exception,), {})
        mock_sa = MagicMock()
        mock_google_cloud = MagicMock()
        mock_google_cloud.storage = mock_gcs_module

        with patch.dict(
            "sys.modules",
            {
                "google": MagicMock(cloud=mock_google_cloud),
                "google.cloud": mock_google_cloud,
                "google.cloud.storage": mock_gcs_module,
                "google.oauth2": MagicMock(service_account=mock_sa),
                "google.oauth2.service_account": mock_sa,
                "google.cloud.exceptions": MagicMock(GoogleCloudError=fake_gcs_error),
            },
        ), patch(
            "dhara.backup.storage.service_account",
            mock_sa,
            create=True,
        ):
            storage = GCSStorage(
                bucket_name="bucket",
                credentials_path="/path/to/sa.json",
                project_id="proj",
            )
        # Verify _credentials was set via from_service_account_file
        mock_sa.Credentials.from_service_account_file.assert_called_once_with(
            "/path/to/sa.json"
        )

    def test_init_with_credentials_path_name_error(self):
        """Verify that credentials_path without patched import raises NameError.

        This documents the known bug: the source references `service_account`
        without importing `from google.oauth2 import service_account`.
        """
        mock_gcs_module = MagicMock()
        mock_client = MagicMock()
        mock_gcs_module.Client.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        fake_gcs_error = type("GoogleCloudError", (Exception,), {})
        mock_google_cloud = MagicMock()
        mock_google_cloud.storage = mock_gcs_module

        with patch.dict(
            "sys.modules",
            {
                "google": MagicMock(cloud=mock_google_cloud),
                "google.cloud": mock_google_cloud,
                "google.cloud.storage": mock_gcs_module,
                "google.oauth2": MagicMock(),
                "google.oauth2.service_account": MagicMock(),
                "google.cloud.exceptions": MagicMock(GoogleCloudError=fake_gcs_error),
            },
        ):
            with pytest.raises(NameError, match="service_account"):
                GCSStorage(
                    bucket_name="bucket",
                    credentials_path="/path/to/sa.json",
                    project_id="proj",
                )


class TestGCSStorageUploadFile:
    def test_upload_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        result = storage.upload_file("/local/file", "remote/path")
        assert result is True
        mock_bucket.blob.assert_called_once_with("remote/path")
        mock_blob.upload_from_filename.assert_called_once_with("/local/file")

    def test_upload_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.upload_from_filename.side_effect = GcsError("upload failed")

        result = storage.upload_file("/local/file", "remote/path")
        assert result is False


class TestGCSStorageDownloadFile:
    def test_download_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        result = storage.download_file("remote/path", "/local/file")
        assert result is True
        mock_bucket.blob.assert_called_once_with("remote/path")
        mock_blob.download_to_filename.assert_called_once_with("/local/file")

    def test_download_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.download_to_filename.side_effect = GcsError("download failed")

        result = storage.download_file("remote/path", "/local/file")
        assert result is False


class TestGCSStorageUploadJson:
    def test_upload_json_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        data = {"hello": "world", "num": 99}

        result = storage.upload_json(data, "data.json")
        assert result is True
        mock_bucket.blob.assert_called_once_with("data.json")
        mock_blob.upload_from_string.assert_called_once()
        call_args = mock_blob.upload_from_string.call_args
        assert json.loads(call_args[0][0]) == data
        assert call_args.kwargs["content_type"] == "application/json"

    def test_upload_json_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.upload_from_string.side_effect = GcsError("fail")

        result = storage.upload_json({}, "f.json")
        assert result is False


class TestGCSStorageDownloadJson:
    def test_download_json_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        expected = {"status": "ok", "items": [1, 2]}
        mock_blob.download_as_text.return_value = json.dumps(expected)

        result = storage.download_json("data.json")
        assert result == expected

    def test_download_json_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.download_as_text.side_effect = GcsError("fail")

        result = storage.download_json("data.json")
        assert result is None


class TestGCSStorageListFiles:
    def test_list_files_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        now = datetime.now(timezone.utc)
        blob_a = MagicMock(name="a", size=100, time_created=now)
        blob_a.name = "backups/a.db"
        blob_b = MagicMock(name="b", size=200, time_created=now)
        blob_b.name = "backups/b.db"
        mock_bucket.list_blobs.return_value = [blob_a, blob_b]

        files = storage.list_files(prefix="backups/")
        assert len(files) == 2
        assert files[0]["name"] == "backups/a.db"
        assert files[0]["size"] == 100
        assert files[1]["name"] == "backups/b.db"
        mock_bucket.list_blobs.assert_called_once_with(prefix="backups/")

    def test_list_files_empty(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_bucket.list_blobs.return_value = []

        files = storage.list_files()
        assert files == []

    def test_list_files_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_bucket.list_blobs.side_effect = GcsError("fail")

        files = storage.list_files()
        assert files == []


class TestGCSStorageDeleteFile:
    def test_delete_success(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        result = storage.delete_file("old/file")
        assert result is True
        mock_bucket.blob.assert_called_once_with("old/file")
        mock_blob.delete.assert_called_once()

    def test_delete_failure(self):
        storage, mock_bucket, _, GcsError = _make_gcs_storage()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.delete.side_effect = GcsError("fail")

        result = storage.delete_file("old/file")
        assert result is False


# ---------------------------------------------------------------------------
# AzureBlobStorage
# ---------------------------------------------------------------------------


def _make_azure_storage():
    """Build an AzureBlobStorage with mocked azure SDK."""
    mock_blob_service = MagicMock()
    mock_container = MagicMock()
    mock_blob_service.get_container_client.return_value = mock_container

    fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

    mock_azure_blob = MagicMock()
    mock_azure_blob.BlobServiceClient.from_connection_string.return_value = mock_blob_service

    with patch.dict(
        "sys.modules",
        {
            "azure": MagicMock(),
            "azure.core": MagicMock(),
            "azure.core.exceptions": MagicMock(ResourceExistsError=fake_resource_exists_error),
            "azure.storage": MagicMock(),
            "azure.storage.blob": mock_azure_blob,
        },
    ):
        storage = AzureBlobStorage(
            connection_string="DefaultEndpointsProtocol=https;AccountName=test;",
            container_name="my-container",
        )
    return storage, mock_blob_service, mock_container, fake_resource_exists_error


class TestAzureBlobStorageInit:
    def test_import_error_when_azure_missing(self):
        with patch.dict(
            "sys.modules",
            {"azure": None, "azure.core": None, "azure.core.exceptions": None, "azure.storage": None, "azure.storage.blob": None},
        ):
            with pytest.raises(ImportError, match="azure-storage-blob is required"):
                AzureBlobStorage(connection_string="cs")

    def test_init_with_connection_string(self):
        storage, mock_service, mock_container, _ = _make_azure_storage()
        assert storage.connection_string == "DefaultEndpointsProtocol=https;AccountName=test;"
        assert storage.container_name == "my-container"
        mock_service.get_container_client.assert_called_once_with("my-container")

    def test_init_with_account_key(self):
        """When connection_string is empty, uses account_url + credential."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure_blob = MagicMock()
        # When connection_string is empty, the code calls BlobServiceClient(account_url=..., credential=...)
        mock_azure_blob.BlobServiceClient.return_value = mock_service

        with patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.core": MagicMock(),
                "azure.core.exceptions": MagicMock(ResourceExistsError=fake_resource_exists_error),
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_azure_blob,
            },
        ):
            storage = AzureBlobStorage(
                connection_string="",
                container_name="cnt",
                account_name="myaccount",
                account_key="mykey",
            )

        assert storage.container_name == "cnt"

    def test_default_container_name(self):
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure_blob = MagicMock()
        mock_azure_blob.BlobServiceClient.from_connection_string.return_value = mock_service

        with patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.core": MagicMock(),
                "azure.core.exceptions": MagicMock(ResourceExistsError=fake_resource_exists_error),
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_azure_blob,
            },
        ):
            storage = AzureBlobStorage(connection_string="cs")

        assert storage.container_name == "durus-backups"


class TestAzureUploadFile:
    def test_upload_success(self, tmp_path):
        storage, _, mock_container, _ = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"hello azure")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client

        result = storage.upload_file(str(local_file), "backup/data.bin")
        assert result is True
        mock_container.get_blob_client.assert_called_with("backup/data.bin")
        mock_blob_client.upload_blob.assert_called_once()

    def test_upload_overwrite_on_resource_exists(self, tmp_path):
        """When ResourceExistsError fires, code retries with overwrite=True.

        Note: The source code catches `ResourceExistsError` as a bare name in
        upload_file(), but it was only stored as `self.ResourceExistsError` in
        __init__. This test patches the module namespace to make the name
        available, confirming the intended overwrite behavior.
        """
        import dhara.backup.storage as storage_module

        storage, _, mock_container, ResourceExistsError = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"hello")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        # First call raises ResourceExistsError, second call succeeds
        mock_blob_client.upload_blob.side_effect = [
            ResourceExistsError("exists"),
            None,
        ]

        with patch(
            "dhara.backup.storage.ResourceExistsError",
            ResourceExistsError,
            create=True,
        ):
            result = storage.upload_file(str(local_file), "backup/data.bin")
        assert result is True
        # Called twice: once normal, once with overwrite=True
        assert mock_blob_client.upload_blob.call_count == 2
        second_call = mock_blob_client.upload_blob.call_args_list[1]
        assert second_call.kwargs.get("overwrite") is True

    def test_upload_resource_exists_name_error(self, tmp_path):
        """Document that bare ResourceExistsError in upload_file is a bug.

        The source catches `ResourceExistsError` as a bare name, but it was only
        stored on `self` during __init__. When the exception is raised, Python
        raises NameError because the name isn't in the method's scope.
        """
        storage, _, mock_container, ResourceExistsError = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"hello")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.upload_blob.side_effect = ResourceExistsError("exists")

        with pytest.raises(NameError, match="ResourceExistsError"):
            storage.upload_file(str(local_file), "backup/data.bin")

    def test_upload_generic_exception(self, tmp_path):
        storage, _, mock_container, ResourceExistsError = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"data")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.upload_blob.side_effect = RuntimeError("boom")

        # Patch the bare name so the code reaches the generic except clause
        with patch(
            "dhara.backup.storage.ResourceExistsError",
            ResourceExistsError,
            create=True,
        ):
            result = storage.upload_file(str(local_file), "backup/data.bin")
        assert result is False


class TestAzureDownloadFile:
    def test_download_success(self, tmp_path):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.return_value.readall.return_value = b"downloaded"

        local_path = str(tmp_path / "out.bin")
        result = storage.download_file("backup/data.bin", local_path)
        assert result is True
        with open(local_path, "rb") as f:
            assert f.read() == b"downloaded"

    def test_download_failure(self, tmp_path):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.side_effect = RuntimeError("fail")

        result = storage.download_file("backup/data.bin", str(tmp_path / "out.bin"))
        assert result is False


class TestAzureUploadJson:
    def test_upload_json_success(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        data = {"key": "val", "nested": {"a": 1}}

        result = storage.upload_json(data, "config.json")
        assert result is True
        mock_container.get_blob_client.assert_called_with("config.json")
        call_args = mock_blob_client.upload_blob.call_args
        body = call_args[0][0]
        assert json.loads(body.decode("utf-8")) == data
        assert call_args.kwargs["overwrite"] is True

    def test_upload_json_failure(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.upload_blob.side_effect = RuntimeError("fail")

        result = storage.upload_json({}, "f.json")
        assert result is False


class TestAzureDownloadJson:
    def test_download_json_success(self):
        storage, _, mock_container, _ = _make_azure_storage()
        expected = {"result": True, "data": [1, 2, 3]}
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.return_value.readall.return_value = (
            json.dumps(expected).encode("utf-8")
        )

        result = storage.download_json("data.json")
        assert result == expected

    def test_download_json_failure(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.side_effect = RuntimeError("fail")

        result = storage.download_json("missing.json")
        assert result is None


class TestAzureListFiles:
    def test_list_files_success(self):
        storage, _, mock_container, _ = _make_azure_storage()
        now = datetime.now(timezone.utc)
        blob_a = MagicMock()
        blob_a.name = "backup/a.db"
        blob_a.size = 100
        blob_a.last_modified = now
        blob_b = MagicMock()
        blob_b.name = "backup/b.db"
        blob_b.size = 200
        blob_b.last_modified = now
        mock_container.list_blobs.return_value = [blob_a, blob_b]

        files = storage.list_files(prefix="backup/")
        assert len(files) == 2
        assert files[0]["name"] == "backup/a.db"
        assert files[0]["size"] == 100
        assert files[1]["name"] == "backup/b.db"
        mock_container.list_blobs.assert_called_once_with(name_starts_with="backup/")

    def test_list_files_empty(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_container.list_blobs.return_value = []

        files = storage.list_files()
        assert files == []

    def test_list_files_failure(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_container.list_blobs.side_effect = RuntimeError("fail")

        files = storage.list_files()
        assert files == []


class TestAzureDeleteFile:
    def test_delete_success(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client

        result = storage.delete_file("old/file")
        assert result is True
        mock_container.get_blob_client.assert_called_with("old/file")
        mock_blob_client.delete_blob.assert_called_once()

    def test_delete_failure(self):
        storage, _, mock_container, _ = _make_azure_storage()
        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.delete_blob.side_effect = RuntimeError("fail")

        result = storage.delete_file("old/file")
        assert result is False


# ---------------------------------------------------------------------------
# StorageFactory
# ---------------------------------------------------------------------------


class TestStorageFactory:
    """Test StorageFactory.create_storage with all provider aliases and error cases."""

    def test_create_s3(self):
        with patch("dhara.backup.storage.S3Storage") as MockS3:
            mock_instance = MagicMock()
            MockS3.return_value = mock_instance
            storage = StorageFactory.create_storage("s3", bucket_name="test")
            MockS3.assert_called_once_with(bucket_name="test")
            assert storage is mock_instance

    def test_create_s3_with_all_params(self):
        with patch("dhara.backup.storage.S3Storage") as MockS3:
            MockS3.return_value = MagicMock()
            StorageFactory.create_storage(
                "s3",
                bucket_name="b",
                region="us-west-2",
                access_key="ak",
                secret_key="sk",
                endpoint_url="http://minio:9000",
            )
            MockS3.assert_called_once_with(
                bucket_name="b",
                region="us-west-2",
                access_key="ak",
                secret_key="sk",
                endpoint_url="http://minio:9000",
            )

    def test_create_gcs(self):
        with patch("dhara.backup.storage.GCSStorage") as MockGCS:
            mock_instance = MagicMock()
            MockGCS.return_value = mock_instance
            storage = StorageFactory.create_storage("gcs", bucket_name="test")
            MockGCS.assert_called_once_with(bucket_name="test")
            assert storage is mock_instance

    def test_create_gcs_google_alias(self):
        with patch("dhara.backup.storage.GCSStorage") as MockGCS:
            MockGCS.return_value = MagicMock()
            StorageFactory.create_storage("google", bucket_name="test")
            MockGCS.assert_called_once()

    def test_create_gcs_google_cloud_alias(self):
        with patch("dhara.backup.storage.GCSStorage") as MockGCS:
            MockGCS.return_value = MagicMock()
            StorageFactory.create_storage("google-cloud", bucket_name="test")
            MockGCS.assert_called_once()

    def test_create_azure(self):
        with patch("dhara.backup.storage.AzureBlobStorage") as MockAzure:
            mock_instance = MagicMock()
            MockAzure.return_value = mock_instance
            storage = StorageFactory.create_storage("azure", connection_string="cs")
            MockAzure.assert_called_once_with(connection_string="cs")
            assert storage is mock_instance

    def test_create_azure_blob_alias(self):
        with patch("dhara.backup.storage.AzureBlobStorage") as MockAzure:
            MockAzure.return_value = MagicMock()
            StorageFactory.create_storage("azure-blob", connection_string="cs")
            MockAzure.assert_called_once()

    def test_create_azure_with_all_params(self):
        with patch("dhara.backup.storage.AzureBlobStorage") as MockAzure:
            MockAzure.return_value = MagicMock()
            StorageFactory.create_storage(
                "azure",
                connection_string="cs",
                container_name="custom",
                account_name="acct",
                account_key="key",
            )
            MockAzure.assert_called_once_with(
                connection_string="cs",
                container_name="custom",
                account_name="acct",
                account_key="key",
            )

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unsupported storage provider"):
            StorageFactory.create_storage("unknown_provider")

    def test_case_insensitive(self):
        with patch("dhara.backup.storage.S3Storage") as MockS3:
            MockS3.return_value = MagicMock()
            StorageFactory.create_storage("S3", bucket_name="test")
            MockS3.assert_called_once()

    def test_case_insensitive_azure(self):
        with patch("dhara.backup.storage.AzureBlobStorage") as MockAzure:
            MockAzure.return_value = MagicMock()
            StorageFactory.create_storage("AZURE", connection_string="cs")
            MockAzure.assert_called_once()

    def test_case_insensitive_gcs(self):
        with patch("dhara.backup.storage.GCSStorage") as MockGCS:
            MockGCS.return_value = MagicMock()
            StorageFactory.create_storage("GCS", bucket_name="test")
            MockGCS.assert_called_once()
