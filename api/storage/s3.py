"""
Storage backend: S3 in production, local /tmp filesystem in development.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

import aiofiles
import boto3
from botocore.exceptions import ClientError

from config import settings

# ─── Dev local storage path ───────────────────────────────────────────────────

_LOCAL_BASE = Path("/tmp/synthiq-dev/sources")


class StorageBackend(Protocol):
    async def upload(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload bytes and return the storage key."""
        ...

    async def download(self, key: str) -> bytes:
        """Download and return bytes for the given key."""
        ...

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a presigned download URL."""
        ...

    async def delete(self, key: str) -> None:
        """Delete the object at the given key."""
        ...


# ─── Local filesystem backend (dev) ───────────────────────────────────────────


class LocalStorage:
    """Writes files to /tmp/synthiq-dev/sources for local development."""

    def __init__(self) -> None:
        _LOCAL_BASE.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "__")
        return _LOCAL_BASE / safe

    async def upload(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        return key

    async def download(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(f"Local storage: key not found: {key}")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # In dev, return a local file URI
        return f"file://{self._path(key)}"

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


# ─── S3 backend (production) ──────────────────────────────────────────────────


class S3Storage:
    """Wraps boto3 S3 client with async-compatible calls via executor."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self._bucket = settings.aws_s3_bucket

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous boto3 call in a thread pool."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def upload(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        import io
        await self._run_sync(
            self._client.upload_fileobj,
            io.BytesIO(content),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    async def download(self, key: str) -> bytes:
        import io
        buf = io.BytesIO()
        await self._run_sync(self._client.download_fileobj, self._bucket, key, buf)
        return buf.getvalue()

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        url = await self._run_sync(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    async def delete(self, key: str) -> None:
        await self._run_sync(self._client.delete_object, Bucket=self._bucket, Key=key)


# ─── Factory ──────────────────────────────────────────────────────────────────


def get_storage() -> LocalStorage | S3Storage:
    """Return the appropriate storage backend based on configuration."""
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        return S3Storage()
    return LocalStorage()
