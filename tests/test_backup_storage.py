"""Tests for dhara.backup.storage -- all adapter classes and StorageFactory."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, call, patch

import pytest

from dhara.backup.storage import (
    AzureBlobStorage,
    GCSStorage,
    S3Storage,
    _DelegatingStorageAdapter,
    _settings_to_kwargs,
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


class TestDelegatingStorageAdapter:
    def test_forwards_all_operations(self):
        adapter = MagicMock()
        adapter.upload_file.return_value = True
        adapter.download_file.return_value = True
        adapter.upload_json.return_value = True
        adapter.download_json.return_value = {"ok": True}
        adapter.list_files.return_value = [{"key": "a"}]
        adapter.delete_file.return_value = True

        wrapper = _DelegatingStorageAdapter(adapter)

        assert wrapper.upload_file("local", "remote") is True
        assert wrapper.download_file("remote", "local") is True
        assert wrapper.upload_json({"a": 1}, "remote") is True
        assert wrapper.download_json("remote") == {"ok": True}
        assert wrapper.list_files(prefix="x") == [{"key": "a"}]
        assert wrapper.delete_file("remote") is True
        assert wrapper.some_attr == adapter.some_attr

    def test_missing_attr_raises(self):
        wrapper = _DelegatingStorageAdapter(None)
        with pytest.raises(AttributeError, match="missing"):
            _ = wrapper.missing


class TestSettingsConversion:
    def test_settings_to_kwargs_for_known_settings(self, tmp_path):
        from oneiric.adapters.storage import (
            AzureBlobStorageSettings,
            GCSStorageSettings,
            LocalStorageSettings,
            S3StorageSettings,
        )

        s3 = S3StorageSettings(bucket="bucket", region="eu-west-1", use_accelerate_endpoint=True)
        gcs = GCSStorageSettings(bucket="bucket", project="proj", credentials_file=tmp_path / "creds.json")
        azure = AzureBlobStorageSettings(container="container", connection_string="conn", credential="cred")
        local = LocalStorageSettings(base_path=tmp_path)

        assert _settings_to_kwargs(s3)["bucket_name"] == "bucket"
        assert _settings_to_kwargs(gcs)["project_id"] == "proj"
        assert _settings_to_kwargs(azure)["container_name"] == "container"
        assert _settings_to_kwargs(local)["base_path"] == tmp_path

    def test_settings_to_kwargs_model_dump_and_dict(self):
        class ModelDumpOnly:
            def model_dump(self):
                return {"alpha": 1}

        assert _settings_to_kwargs(ModelDumpOnly()) == {"alpha": 1}
        assert _settings_to_kwargs({"beta": 2}) == {"beta": 2}

    def test_settings_to_kwargs_unsupported(self):
        with pytest.raises(TypeError, match="Unsupported settings object"):
            _settings_to_kwargs(object())


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

    def test_init_from_settings_object(self):
        from oneiric.adapters.storage import S3StorageSettings

        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        fake_client_error = type("ClientError", (Exception,), {})
        settings = S3StorageSettings(
            bucket="my-bucket",
            region="eu-central-1",
            endpoint_url="http://minio:9000",
            profile_name="profile",
            access_key_id="AKID",
            secret_access_key="SECRET",
            session_token="TOKEN",
            healthcheck_key="health",
            use_accelerate_endpoint=True,
        )

        with patch.dict(
            "sys.modules",
            {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock(ClientError=fake_client_error)},
        ):
            storage = S3Storage(settings)

        assert storage.bucket_name == "my-bucket"
        assert storage.settings is settings
        mock_boto3.client.assert_called_once_with(
            "s3",
            region_name="eu-central-1",
            endpoint_url="http://minio:9000",
            aws_access_key_id="AKID",
            aws_secret_access_key="SECRET",
            aws_session_token="TOKEN",
        )

    def test_init_rejects_unexpected_kwargs(self):
        with pytest.raises(TypeError, match="Unexpected keyword arguments"):
            S3Storage(bucket_name="bucket", extra="nope")

    def test_init_requires_bucket_name(self):
        with pytest.raises(TypeError, match="bucket_name is required"):
            S3Storage(region="us-east-1")


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

    def test_download_json_string_body_branch(self):
        storage, mock_client, _ = _make_s3_storage()

        class _Body:
            def read(self):
                return json.dumps({"hello": "world"})

        mock_client.get_object.return_value = {"Body": _Body()}

        result = storage.download_json("data.json")
        assert result == {"hello": "world"}


class TestS3StorageAsyncMethods:
    @pytest.mark.asyncio
    async def test_async_upload_and_download(self):
        storage, mock_client, _ = _make_s3_storage()

        async def _put_object(*args, **kwargs):
            return None

        class _Body:
            def read(self):
                async def _read():
                    return b"hello"

                return _read()

        async def _get_object(*args, **kwargs):
            return {"Body": _Body()}

        mock_client.put_object.return_value = _put_object()
        mock_client.get_object.return_value = _get_object()

        await storage.upload("remote", b"payload")
        data = await storage.download("remote")

        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_async_upload_and_download_sync_return_branches(self):
        storage, mock_client, _ = _make_s3_storage()

        class _Body:
            def read(self):
                return b"world"

        mock_client.put_object.return_value = None
        mock_client.get_object.return_value = {"Body": _Body()}

        await storage.upload("remote", b"payload")
        data = await storage.download("remote")

        assert data == b"world"


class TestS3StorageAsyncDownloads:
    @pytest.mark.asyncio
    async def test_async_download_with_string_body(self):
        storage, mock_client, _ = _make_s3_storage()

        class _Response:
            def __init__(self):
                self.Body = None

        async def _get_object(*args, **kwargs):
            class _Body:
                def read(self):
                    return "hello"

            return {"Body": _Body()}

        mock_client.get_object.return_value = _get_object()

        data = await storage.download("remote")

        assert data == b"hello"


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
        """Verify credentials_path is normalized into the settings object."""

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
            storage = GCSStorage(
                bucket_name="bucket",
                credentials_path="/path/to/sa.json",
                project_id="proj",
            )
        assert str(storage.settings.credentials_file) == "/path/to/sa.json"
        assert storage.project_id == "proj"

    def test_init_from_settings_object(self):
        from oneiric.adapters.storage import GCSStorageSettings

        mock_gcs_module = MagicMock()
        mock_client = MagicMock()
        mock_gcs_module.Client.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        fake_gcs_error = type("GoogleCloudError", (Exception,), {})
        mock_google_cloud = MagicMock()
        mock_google_cloud.storage = mock_gcs_module
        settings = GCSStorageSettings(bucket="bucket", project="proj")

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
            storage = GCSStorage(settings)

        assert storage.bucket_name == "bucket"
        assert storage.settings is settings
        mock_gcs_module.Client.assert_called_once_with(project="proj", credentials=None)

    def test_init_requires_bucket_name(self):
        with pytest.raises(TypeError, match="bucket_name is required"):
            GCSStorage(project_id="proj")

    def test_init_rejects_unexpected_kwargs(self):
        with pytest.raises(TypeError, match="Unexpected keyword arguments"):
            GCSStorage(bucket_name="bucket", extra="nope")


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


class TestGCSStorageAsyncMethods:
    @pytest.mark.asyncio
    async def test_async_upload_and_download_bytes(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()
        class _Blob:
            def upload_from_string(self, data):
                class _Awaitable:
                    def __await__(self):
                        async def _inner():
                            return None

                        return _inner().__await__()

                return _Awaitable()

            def download_as_bytes(self):
                class _Awaitable:
                    def __await__(self):
                        async def _inner():
                            return b"payload"

                        return _inner().__await__()

                return _Awaitable()

        mock_bucket.blob.return_value = _Blob()

        await storage.upload("remote", b"payload")
        data = await storage.download("remote")

        assert data == b"payload"

    @pytest.mark.asyncio
    async def test_async_upload_and_download_sync_return_branches(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def upload_from_filename(self, data):
                return None

            def download_as_bytes(self):
                return b"payload"

        mock_bucket.blob.return_value = _Blob()

        await storage.upload("remote", b"payload")
        data = await storage.download("remote")

        assert data == b"payload"

    @pytest.mark.asyncio
    async def test_async_download_text_branch(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def upload_from_string(self, *args, **kwargs):
                async def _upload():
                    return None

                return _upload()

            def download_as_text(self):
                async def _download():
                    return "hello"

                return _download()

        mock_blob = _Blob()
        mock_bucket.blob.return_value = mock_blob

        await storage.upload("remote", b"payload")
        data = await storage.download("remote")

        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_async_download_text_sync_branch(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def download_as_text(self):
                return "hello"

        mock_bucket.blob.return_value = _Blob()

        data = await storage.download("remote")

        assert data == b"hello"

    def test_upload_file_from_filename_branch(self, tmp_path):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def upload_from_filename(self, local_path):
                self.local_path = local_path

        blob = _Blob()
        mock_bucket.blob.return_value = blob

        file_path = tmp_path / "file.bin"
        file_path.write_bytes(b"x")

        assert storage.upload_file(str(file_path), "remote") is True
        assert blob.local_path == str(file_path)

    @pytest.mark.asyncio
    async def test_async_download_text_only_branch(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def download_as_text(self):
                class _Awaitable:
                    def __await__(self):
                        async def _inner():
                            return "hello"

                        return _inner().__await__()

                return _Awaitable()

        mock_bucket.blob.return_value = _Blob()
        data = await storage.download("remote")
        assert data == b"hello"

    def test_upload_from_filename_branch(self, tmp_path):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def upload_from_filename(self, local_path):
                self.local_path = local_path

        blob = _Blob()
        mock_bucket.blob.return_value = blob

        path = tmp_path / "file.bin"
        path.write_bytes(b"x")

        assert storage.upload_file(str(path), "remote") is True
        assert blob.local_path == str(path)

    def test_download_as_text_branch(self):
        storage, mock_bucket, _, _ = _make_gcs_storage()

        class _Blob:
            def download_as_text(self):
                return "hello"

        mock_bucket.blob.return_value = _Blob()

        assert storage.download_json("remote") is None


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


class TestAzureBlobStorageSettingsInit:
    def test_init_from_settings_and_account_values(self):
        from oneiric.adapters.storage import AzureBlobStorageSettings

        mock_blob_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_container_client.return_value = mock_container
        mock_blob_module.BlobServiceClient.return_value = mock_client
        mock_blob_module.BlobServiceClient.from_connection_string.side_effect = Exception("nope")
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)
        settings = AzureBlobStorageSettings(container="container", connection_string="conn")

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(settings, client=mock_client)

        assert storage.container_name == "container"
        assert storage.settings is settings
        assert storage.container_client is mock_container

    def test_init_derives_account_url_and_credential(self):
        mock_blob_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_container_client.return_value = mock_container
        mock_blob_module.BlobServiceClient.return_value = mock_client
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(
                container_name="container",
                account_name="acct",
                account_key="key",
                client=mock_client,
            )

        assert storage.account_url == "https://acct.blob.core.windows.net"
        assert storage.credential == "key"

    def test_init_from_settings_object(self):
        from oneiric.adapters.storage import AzureBlobStorageSettings

        mock_blob_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_container_client.return_value = mock_container
        mock_blob_module.BlobServiceClient.return_value = mock_client
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)
        settings = AzureBlobStorageSettings(container="container", default_content_type="text/plain")

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(settings)

        assert storage.settings is settings
        assert storage.container_name == "container"

    def test_init_from_settings_object_copies_optional_fields(self):
        from types import SimpleNamespace

        mock_blob_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_container_client.return_value = mock_container
        mock_blob_module.BlobServiceClient.return_value = mock_client
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)
        settings = SimpleNamespace(
            container="container",
            connection_string="conn",
            account_url="https://example.blob.core.windows.net",
            credential="cred",
            default_content_type="text/plain",
        )

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(settings)

        assert storage.connection_string == "conn"
        assert storage.account_url == "https://example.blob.core.windows.net"
        assert storage.credential == "cred"
        assert storage.settings.default_content_type == "text/plain"

    def test_init_rejects_unexpected_kwargs(self):
        with pytest.raises(TypeError, match="Unexpected keyword arguments"):
            AzureBlobStorage(container_name="container", extra="nope")

    def test_fallback_client_paths(self, tmp_path):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})
        mock_blob_module = MagicMock()
        mock_blob_module.BlobServiceClient.from_connection_string.side_effect = Exception(
            "boom"
        )
        mock_blob_module.BlobServiceClient.side_effect = Exception("boom")
        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(container_name="container")

        path = tmp_path / "tmp_azure_storage.txt"
        path.write_text("data")
        try:
            assert storage.upload_file(str(path), "remote.txt") is True
            assert storage.download_file("remote.txt", str(path.with_name("copy.txt"))) is True
            assert storage.upload_json({"a": 1}, "data.json") is True
            assert storage.download_json("data.json") is None
            assert storage.list_files() == []
            assert storage.delete_file("remote.txt") is True
        finally:
            if path.exists():
                path.unlink()
            copy_path = path.with_name("copy.txt")
            if copy_path.exists():
                copy_path.unlink()

    def test_fallback_client_direct_methods(self):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})
        mock_blob_module = MagicMock()
        mock_blob_module.BlobServiceClient.from_connection_string.side_effect = Exception(
            "boom"
        )
        mock_blob_module.BlobServiceClient.side_effect = Exception("boom")
        mock_azure = MagicMock()
        mock_azure.storage.blob = mock_blob_module
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": mock_blob_module,
            },
        ):
            storage = AzureBlobStorage(container_name="container")

        blob_client = storage.client.get_container_client("container").get_blob_client(
            "remote.txt"
        )
        assert blob_client.upload_blob(b"data") is None
        assert blob_client.download_blob().readall() == b""
        assert blob_client.delete_blob() is None
        assert storage.client.get_container_client("container").list_blobs() == []

    def test_fallback_client_download_awaitable_branch(self):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        class _AwaitableDownload:
            def __await__(self):
                async def _inner():
                    class _Download:
                        def readall(self):
                            class _Awaitable:
                                def __await__(self):
                                    async def _inner2():
                                        return b""

                                    return _inner2().__await__()

                            return _Awaitable()

                    return _Download()

                return _inner().__await__()

        class _Blob:
            def upload_blob(self, *args, **kwargs):
                return None

            def download_blob(self):
                return _AwaitableDownload()

        class _Container:
            def get_blob_client(self, _name):
                return _Blob()

            def list_blobs(self, name_starts_with=""):
                return []

        class _Client:
            def get_container_client(self, _name):
                return _Container()

        mock_azure = MagicMock()
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": MagicMock(BlobServiceClient=MagicMock()),
            },
        ):
            adapter = AzureBlobStorage(container_name="container", client=_Client())

        import asyncio

        async def _run():
            return await adapter.download("remote")

        assert asyncio.run(_run()) == b""

    def test_upload_file_overwrite_on_resource_exists(self, tmp_path):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})
        mock_blob = MagicMock()
        mock_blob.upload_blob.side_effect = [fake_resource_exists_error(), None]
        mock_container = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob
        adapter = AzureBlobStorage.__new__(AzureBlobStorage)
        adapter.container_client = mock_container
        adapter._resource_exists_error = fake_resource_exists_error

        file_path = tmp_path / "backup.bin"
        file_path.write_bytes(b"content")

        assert adapter.upload_file(str(file_path), "remote.bin") is True
        mock_blob.upload_blob.assert_any_call(b"content")
        mock_blob.upload_blob.assert_any_call(b"content", overwrite=True)


class TestAzureBlobStorageAsyncMethods:
    @pytest.mark.asyncio
    async def test_async_upload_and_download(self):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        class _Blob:
            def upload_blob(self, data, **kwargs):
                async def _upload():
                    return None

                return _upload()

            def download_blob(self):
                class _Download:
                    def readall(self):
                        async def _read():
                            return b"azure"

                        return _read()

                return _Download()

        class _Container:
            def get_blob_client(self, _name):
                return _Blob()

            def list_blobs(self, name_starts_with=""):
                return []

        class _Client:
            def get_container_client(self, _name):
                return _Container()

        mock_azure = MagicMock()
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": MagicMock(BlobServiceClient=MagicMock()),
            },
        ):
            adapter = AzureBlobStorage(container_name="container", client=_Client())

        await adapter.upload("remote", b"payload")
        data = await adapter.download("remote")
        assert data == b"azure"

    @pytest.mark.asyncio
    async def test_async_upload_and_download_sync_return_branches(self):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        class _Blob:
            def upload_blob(self, data, **kwargs):
                return None

            def download_blob(self):
                class _Download:
                    def readall(self):
                        return b"azure"

                return _Download()

        class _Container:
            def get_blob_client(self, _name):
                return _Blob()

            def list_blobs(self, name_starts_with=""):
                return []

        class _Client:
            def get_container_client(self, _name):
                return _Container()

        mock_azure = MagicMock()
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": MagicMock(BlobServiceClient=MagicMock()),
            },
        ):
            adapter = AzureBlobStorage(container_name="container", client=_Client())

        await adapter.upload("remote", b"payload")
        assert await adapter.download("remote") == b"azure"

    @pytest.mark.asyncio
    async def test_async_download_blob_awaitable_branch(self):
        fake_resource_exists_error = type("ResourceExistsError", (Exception,), {})

        class _AwaitableDownload:
            def __await__(self):
                async def _inner():
                    class _Download:
                        def readall(self):
                            return b"azure"

                    return _Download()

                return _inner().__await__()

        class _Blob:
            def upload_blob(self, data, **kwargs):
                return None

            def download_blob(self):
                return _AwaitableDownload()

        class _Container:
            def get_blob_client(self, _name):
                return _Blob()

        class _Client:
            def get_container_client(self, _name):
                return _Container()

        mock_azure = MagicMock()
        mock_azure.core.exceptions = MagicMock(ResourceExistsError=fake_resource_exists_error)

        with patch.dict(
            "sys.modules",
            {
                "azure": mock_azure,
                "azure.core": mock_azure.core,
                "azure.core.exceptions": mock_azure.core.exceptions,
                "azure.storage": MagicMock(),
                "azure.storage.blob": MagicMock(BlobServiceClient=MagicMock()),
            },
        ):
            adapter = AzureBlobStorage(container_name="container", client=_Client())

        assert await adapter.download("remote") == b"azure"


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

        assert storage.container_name == "dhara-backups"


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

    def test_upload_file_overwrite_failure(self, tmp_path):
        storage, _, mock_container, ResourceExistsError = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"hello")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.upload_blob.side_effect = [
            ResourceExistsError("exists"),
            RuntimeError("still failing"),
        ]

        with patch(
            "dhara.backup.storage.ResourceExistsError",
            ResourceExistsError,
            create=True,
        ):
            result = storage.upload_file(str(local_file), "backup/data.bin")

        assert result is False

    def test_upload_resource_exists_retries_with_overwrite(self, tmp_path):
        """ResourceExistsError should retry upload with overwrite=True."""
        storage, _, mock_container, ResourceExistsError = _make_azure_storage()
        local_file = tmp_path / "data.bin"
        local_file.write_bytes(b"hello")

        mock_blob_client = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_blob_client.upload_blob.side_effect = [ResourceExistsError("exists"), None]
        result = storage.upload_file(str(local_file), "backup/data.bin")
        assert result is True
        assert mock_blob_client.upload_blob.call_count == 2

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
