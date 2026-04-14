"""
Cloud storage adapters for Durus backups.

This module provides adapters for:
- Amazon S3
- Google Cloud Storage
- Azure Blob Storage
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class StorageAdapter(ABC):
    """Abstract base class for storage adapters."""

    @abstractmethod
    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload a file to cloud storage."""
        pass

    @abstractmethod
    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download a file from cloud storage."""
        pass

    @abstractmethod
    def upload_json(self, data: dict[str, Any], remote_path: str) -> bool:
        """Upload JSON data to cloud storage."""
        pass

    @abstractmethod
    def download_json(self, remote_path: str) -> dict[str, Any] | None:
        """Download JSON data from cloud storage."""
        pass

    @abstractmethod
    def list_files(self, prefix: str = "") -> list:
        """List files in cloud storage with optional prefix."""
        pass

    @abstractmethod
    def delete_file(self, remote_path: str) -> bool:
        """Delete a file from cloud storage."""
        pass


class S3Storage(StorageAdapter):
    """Amazon S3 storage adapter."""

    def __init__(
        self,
        bucket_name: str,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
    ):
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 storage. Install with: pip install boto3"
            )

        self.bucket_name = bucket_name
        self.region = region
        self.ClientError = ClientError

        # Create S3 client
        session_kwargs = {"region_name": region}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key

        if endpoint_url:
            session_kwargs["endpoint_url"] = endpoint_url

        self.s3_client = boto3.client("s3", **session_kwargs)

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload file to S3."""
        try:
            self.s3_client.upload_file(local_path, self.bucket_name, remote_path)
            logger.info(f"Uploaded to S3: {remote_path}")
            return True
        except self.ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download file from S3."""
        try:
            self.s3_client.download_file(self.bucket_name, remote_path, local_path)
            logger.info(f"Downloaded from S3: {remote_path}")
            return True
        except self.ClientError as e:
            logger.error(f"S3 download failed: {e}")
            return False

    def upload_json(self, data: dict[str, Any], remote_path: str) -> bool:
        """Upload JSON to S3."""
        try:
            json_str = json.dumps(data, indent=2)
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=remote_path,
                Body=json_str.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info(f"Uploaded JSON to S3: {remote_path}")
            return True
        except self.ClientError as e:
            logger.error(f"S3 JSON upload failed: {e}")
            return False

    def download_json(self, remote_path: str) -> dict[str, Any] | None:
        """Download JSON from S3."""
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=remote_path
            )
            json_str = response["Body"].read().decode("utf-8")
            return json.loads(json_str)
        except self.ClientError as e:
            logger.error(f"S3 JSON download failed: {e}")
            return None

    def list_files(self, prefix: str = "") -> list:
        """List files in S3 bucket."""
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)

            files = []
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        files.append(
                            {
                                "key": obj["Key"],
                                "size": obj["Size"],
                                "last_modified": obj["LastModified"],
                            }
                        )
            return files
        except self.ClientError as e:
            logger.error(f"S3 list files failed: {e}")
            return []

    def delete_file(self, remote_path: str) -> bool:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=remote_path)
            logger.info(f"Deleted from S3: {remote_path}")
            return True
        except self.ClientError as e:
            logger.error(f"S3 delete failed: {e}")
            return False


class GCSStorage(StorageAdapter):
    """Google Cloud Storage adapter."""

    def __init__(
        self,
        bucket_name: str,
        credentials_path: str | None = None,
        project_id: str | None = None,
    ):
        try:
            from google.cloud import storage
            from google.cloud.exceptions import GoogleCloudError
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for GCS. Install with: pip install google-cloud-storage"
            )

        self.bucket_name = bucket_name
        self.GoogleCloudError = GoogleCloudError
        self.client = storage.Client(project=project_id)
        if credentials_path:
            self.client._credentials = (
                service_account.Credentials.from_service_account_file(credentials_path)
            )
        self.bucket = self.client.bucket(bucket_name)

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload file to GCS."""
        try:
            blob = self.bucket.blob(remote_path)
            blob.upload_from_filename(local_path)
            logger.info(f"Uploaded to GCS: {remote_path}")
            return True
        except self.GoogleCloudError as e:
            logger.error(f"GCS upload failed: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download file from GCS."""
        try:
            blob = self.bucket.blob(remote_path)
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded from GCS: {remote_path}")
            return True
        except self.GoogleCloudError as e:
            logger.error(f"GCS download failed: {e}")
            return False

    def upload_json(self, data: dict[str, Any], remote_path: str) -> bool:
        """Upload JSON to GCS."""
        try:
            blob = self.bucket.blob(remote_path)
            json_str = json.dumps(data, indent=2)
            blob.upload_from_string(json_str, content_type="application/json")
            logger.info(f"Uploaded JSON to GCS: {remote_path}")
            return True
        except self.GoogleCloudError as e:
            logger.error(f"GCS JSON upload failed: {e}")
            return False

    def download_json(self, remote_path: str) -> dict[str, Any] | None:
        """Download JSON from GCS."""
        try:
            blob = self.bucket.blob(remote_path)
            json_str = blob.download_as_text()
            return json.loads(json_str)
        except self.GoogleCloudError as e:
            logger.error(f"GCS JSON download failed: {e}")
            return None

    def list_files(self, prefix: str = "") -> list:
        """List files in GCS bucket."""
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            files = []
            for blob in blobs:
                files.append(
                    {
                        "name": blob.name,
                        "size": blob.size,
                        "time_created": blob.time_created,
                    }
                )
            return files
        except self.GoogleCloudError as e:
            logger.error(f"GCS list files failed: {e}")
            return []

    def delete_file(self, remote_path: str) -> bool:
        """Delete file from GCS."""
        try:
            blob = self.bucket.blob(remote_path)
            blob.delete()
            logger.info(f"Deleted from GCS: {remote_path}")
            return True
        except self.GoogleCloudError as e:
            logger.error(f"GCS delete failed: {e}")
            return False


class AzureBlobStorage(StorageAdapter):
    """Azure Blob Storage adapter."""

    def __init__(
        self,
        connection_string: str,
        container_name: str = "durus-backups",
        account_name: str | None = None,
        account_key: str | None = None,
    ):
        try:
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import BlobClient, BlobServiceClient
        except ImportError:
            raise ImportError(
                "azure-storage-blob is required for Azure. Install with: pip install azure-storage-blob"
            )

        self.connection_string = connection_string
        self.container_name = container_name
        self.ResourceExistsError = ResourceExistsError

        if connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
        else:
            self.blob_service_client = BlobServiceClient(
                account_url=f"https://{account_name}.blob.core.windows.net",
                credential=account_key,
            )

        self.container_client = self.blob_service_client.get_container_client(
            container_name
        )

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload file to Azure Blob Storage."""
        try:
            blob_client = self.container_client.get_blob_client(remote_path)
            with open(local_path, "rb") as data:
                blob_client.upload_blob(data)
            logger.info(f"Uploaded to Azure Blob: {remote_path}")
            return True
        except ResourceExistsError:
            # Blob already exists, overwrite
            blob_client = self.container_client.get_blob_client(remote_path)
            with open(local_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)
            logger.info(f"Uploaded (overwritten) to Azure Blob: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Azure upload failed: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download file from Azure Blob Storage."""
        try:
            blob_client = self.container_client.get_blob_client(remote_path)
            with open(local_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
            logger.info(f"Downloaded from Azure Blob: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Azure download failed: {e}")
            return False

    def upload_json(self, data: dict[str, Any], remote_path: str) -> bool:
        """Upload JSON to Azure Blob Storage."""
        try:
            blob_client = self.container_client.get_blob_client(remote_path)
            json_str = json.dumps(data, indent=2)
            blob_client.upload_blob(json_str.encode("utf-8"), overwrite=True)
            logger.info(f"Uploaded JSON to Azure Blob: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Azure JSON upload failed: {e}")
            return False

    def download_json(self, remote_path: str) -> dict[str, Any] | None:
        """Download JSON from Azure Blob Storage."""
        try:
            blob_client = self.container_client.get_blob_client(remote_path)
            json_str = blob_client.download_blob().readall().decode("utf-8")
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Azure JSON download failed: {e}")
            return None

    def list_files(self, prefix: str = "") -> list:
        """List files in Azure Blob Storage container."""
        try:
            files = []
            blob_list = self.container_client.list_blobs(name_starts_with=prefix)
            for blob in blob_list:
                files.append(
                    {
                        "name": blob.name,
                        "size": blob.size,
                        "last_modified": blob.last_modified,
                    }
                )
            return files
        except Exception as e:
            logger.error(f"Azure list files failed: {e}")
            return []

    def delete_file(self, remote_path: str) -> bool:
        """Delete file from Azure Blob Storage."""
        try:
            blob_client = self.container_client.get_blob_client(remote_path)
            blob_client.delete_blob()
            logger.info(f"Deleted from Azure Blob: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Azure delete failed: {e}")
            return False


class StorageFactory:
    """Factory for creating storage adapters."""

    @staticmethod
    def create_storage(provider: str, **kwargs) -> StorageAdapter:
        """Create a storage adapter based on provider."""
        if provider.lower() == "s3":
            return S3Storage(**kwargs)
        elif provider.lower() in ["gcs", "google", "google-cloud"]:
            return GCSStorage(**kwargs)
        elif provider.lower() in ["azure", "azure-blob"]:
            return AzureBlobStorage(**kwargs)
        else:
            raise ValueError(f"Unsupported storage provider: {provider}")
