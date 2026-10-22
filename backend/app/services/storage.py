"""Object storage abstraction.

Two buckets with different exposure:

* **public**  watermarked previews and thumbnails, served through a CDN.
* **private** originals and release documents. Never publicly addressable;
  delivered only through short-lived signed download links after an
  entitlement check.

``LocalStorage`` mirrors that layout on disk for development. ``S3Storage``
works with any S3-compatible service (AWS S3, Cloudflare R2, Backblaze B2,
Railway buckets, MinIO).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put_file(self, key: str, path: Path, content_type: str, public: bool) -> None: ...
    def put_bytes(self, key: str, data: bytes, content_type: str, public: bool) -> None: ...
    def public_url(self, key: str) -> str: ...
    def private_download_url(self, key: str, filename: str, seconds: int) -> str | None: ...
    def open_private(self, key: str) -> Iterator[bytes]: ...
    def local_path(self, key: str, public: bool) -> Path | None: ...


class LocalStorage:
    def __init__(self, root: Path, public_base_url: str):
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        (root / "public").mkdir(parents=True, exist_ok=True)
        (root / "private").mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, public: bool) -> Path:
        base = (self.root / ("public" if public else "private")).resolve()
        path = (base / key).resolve()
        if not path.is_relative_to(base):
            raise ValueError("invalid storage key")
        return path

    def put_file(self, key: str, path: Path, content_type: str, public: bool) -> None:
        dest = self._path(key, public)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    def put_bytes(self, key: str, data: bytes, content_type: str, public: bool) -> None:
        dest = self._path(key, public)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"

    def private_download_url(self, key: str, filename: str, seconds: int) -> str | None:
        return None  # streamed by the API instead

    def open_private(self, key: str) -> Iterator[bytes]:
        with self._path(key, public=False).open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                yield chunk

    def local_path(self, key: str, public: bool) -> Path | None:
        return self._path(key, public)


class S3Storage:
    def __init__(self, settings):
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        self.public_bucket = settings.s3_public_bucket
        self.private_bucket = settings.s3_private_bucket
        self.public_base_url = (settings.public_media_base_url or "").rstrip("/")

    def _bucket(self, public: bool) -> str:
        return self.public_bucket if public else self.private_bucket

    def put_file(self, key: str, path: Path, content_type: str, public: bool) -> None:
        with path.open("rb") as fh:
            self._put(key, fh, content_type, public)

    def put_bytes(self, key: str, data: bytes, content_type: str, public: bool) -> None:
        import io

        self._put(key, io.BytesIO(data), content_type, public)

    def _put(self, key: str, fh: BinaryIO, content_type: str, public: bool) -> None:
        extra = {"ContentType": content_type}
        if public:
            extra["CacheControl"] = "public, max-age=31536000, immutable"
        self.client.upload_fileobj(fh, self._bucket(public), key, ExtraArgs=extra)

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"

    def private_download_url(self, key: str, filename: str, seconds: int) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.private_bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=seconds,
        )

    def open_private(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.private_bucket, Key=key)["Body"]
        yield from body.iter_chunks(1024 * 1024)

    def local_path(self, key: str, public: bool) -> Path | None:
        return None


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_path, "/media-public")
