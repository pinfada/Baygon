"""S3-compatible adapters: storage, backup and recovery.

Talks to any S3-compatible endpoint (AWS S3, MinIO, ...) with a
pure-stdlib AWS SigV4 signature — no SDK dependency. Credentials come
from the environment (EF-011); the endpoint, region and bucket from
baygon.yaml. Baygon moves files produced by specialized tools — it
never creates database dumps itself (Article 3).

    providers:
      storage:
        type: storage
        plugin: baygon_plugins.s3:S3Storage
        options: &s3
          endpoint: https://s3.eu-west-1.amazonaws.com
          region: eu-west-1
          bucket: my-project-backups
      vault:
        type: backup
        plugin: baygon_plugins.s3:S3Backup
        options:
          <<: *s3
          sources:
            production: /var/backups/prod.dump
      restorer:
        type: recovery
        plugin: baygon_plugins.s3:S3Recovery
        options:
          <<: *s3
          restore_dir: /var/restore
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from baygon.capabilities import BackupCapability, RecoveryCapability, StorageCapability


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(
    config: dict[str, Any],
    method: str,
    path: str,
    query: str,
    payload: bytes,
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """Build AWS SigV4 headers for an S3 request (pure stdlib)."""
    access_key = os.environ.get(str(config.get("access_key_env", "AWS_ACCESS_KEY_ID")), "")
    secret_key = os.environ.get(str(config.get("secret_key_env", "AWS_SECRET_ACCESS_KEY")), "")
    region = str(config.get("region", "us-east-1"))
    host = urllib.parse.urlsplit(str(config["endpoint"])).netloc
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    canonical_headers = (
        f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [method, path, query, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    key = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    key = _hmac(key, region)
    key = _hmac(key, "s3")
    key = _hmac(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }


class _S3Mixin:
    """Shared transport for the three adapters. Single overridable seam."""

    config: dict[str, Any]

    def _s3_request(self, method: str, key: str, query: str = "", body: bytes = b"") -> bytes:
        bucket = str(self.config["bucket"])
        path = f"/{bucket}/" + urllib.parse.quote(key)
        headers = sigv4_headers(self.config, method, path, query, body)
        url = str(self.config["endpoint"]).rstrip("/") + path + (f"?{query}" if query else "")
        request = urllib.request.Request(url, data=body or None, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    def _credentials_present(self) -> bool:
        access = os.environ.get(str(self.config.get("access_key_env", "AWS_ACCESS_KEY_ID")))
        secret = os.environ.get(str(self.config.get("secret_key_env", "AWS_SECRET_ACCESS_KEY")))
        return bool(access and secret and self.config.get("bucket"))

    def _list_keys(self, prefix: str) -> list[dict[str, Any]]:
        query = "list-type=2&" + urllib.parse.urlencode({"prefix": prefix})
        raw = self._s3_request("GET", "", query=query)
        entries = []
        for contents in ET.fromstring(raw).findall(".//{*}Contents"):
            key = contents.findtext("{*}Key", "")
            size = int(contents.findtext("{*}Size", "0"))
            entries.append({"key": key, "size": size})
        return entries


class S3Storage(_S3Mixin, StorageCapability):
    identifier = "s3-storage"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def health_check(self) -> bool:
        return self._credentials_present()

    def list(self, prefix: str = "", **params: Any) -> list[dict[str, Any]]:
        return self._list_keys(prefix)


class S3Backup(_S3Mixin, BackupCapability):
    identifier = "s3-backup"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def health_check(self) -> bool:
        return self._credentials_present()

    def backup(self, environment: str, **params: Any) -> dict[str, Any]:
        sources = self.config.get("sources") or {}
        source = sources.get(environment)
        if not source:
            raise ValueError(
                f"no backup source declared for environment {environment!r}; "
                "declare it under options.sources in baygon.yaml"
            )
        data = Path(source).read_bytes()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        key = f"backups/{environment}/{Path(source).name}-{stamp}"
        self._s3_request("PUT", key, body=data)
        return {"environment": environment, "key": key, "bytes": len(data), "state": "backed-up"}


class S3Recovery(_S3Mixin, RecoveryCapability):
    identifier = "s3-recovery"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def health_check(self) -> bool:
        return self._credentials_present()

    def restore(self, environment: str, **params: Any) -> dict[str, Any]:
        prefix = f"backups/{environment}/"
        entries = self._list_keys(prefix)
        if not entries:
            raise ValueError(f"no backup found under {prefix!r}")
        latest = max(entries, key=lambda entry: entry["key"])["key"]
        data = self._s3_request("GET", latest)
        target = Path(str(self.config.get("restore_dir", "."))) / Path(latest).name
        target.write_bytes(data)
        return {
            "environment": environment,
            "key": latest,
            "path": str(target),
            "state": "restored",
        }
