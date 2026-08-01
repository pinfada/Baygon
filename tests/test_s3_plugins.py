"""TDD — real storage/backup/recovery adapters (S3-compatible).

Chapter 8 lists Storage, Backup and Recovery among the minimal
capabilities. These adapters talk to any S3-compatible endpoint (AWS,
MinIO, ...) with a pure-stdlib SigV4 signature; credentials come from
the environment (EF-011). Baygon moves files produced by specialized
tools — it never creates the dumps itself.
"""

import datetime
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from baygon_plugins.s3 import S3Backup, S3Recovery, S3Storage, sigv4_headers

CONFIG = {
    "endpoint": "https://s3.example.invalid",
    "region": "eu-west-1",
    "bucket": "baygon-demo",
}

LIST_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Contents><Key>backups/production/db.dump-20260801T100000</Key><Size>2048</Size></Contents>
  <Contents><Key>backups/production/db.dump-20260801T120000</Key><Size>4096</Size></Contents>
</ListBucketResult>"""


class SigV4Test(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AWS_ACCESS_KEY_ID"] = "AKIDEXAMPLE"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "secret-one"
        self.addCleanup(os.environ.pop, "AWS_ACCESS_KEY_ID", None)
        self.addCleanup(os.environ.pop, "AWS_SECRET_ACCESS_KEY", None)
        self.now = datetime.datetime(2026, 8, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def test_authorization_header_structure(self) -> None:
        headers = sigv4_headers(CONFIG, "GET", "/baygon-demo/", "list-type=2", b"", now=self.now)
        auth = headers["Authorization"]
        self.assertTrue(auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260801/"))
        self.assertIn("eu-west-1/s3/aws4_request", auth)
        self.assertIn("SignedHeaders=host;x-amz-content-sha256;x-amz-date", auth)
        self.assertIn("Signature=", auth)
        self.assertEqual(headers["x-amz-date"], "20260801T120000Z")

    def test_signature_is_deterministic_and_secret_sensitive(self) -> None:
        first = sigv4_headers(CONFIG, "GET", "/b/", "", b"", now=self.now)["Authorization"]
        second = sigv4_headers(CONFIG, "GET", "/b/", "", b"", now=self.now)["Authorization"]
        self.assertEqual(first, second)
        os.environ["AWS_SECRET_ACCESS_KEY"] = "secret-two"
        third = sigv4_headers(CONFIG, "GET", "/b/", "", b"", now=self.now)["Authorization"]
        self.assertNotEqual(first, third)


class FakeTransportMixin:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requests: list[tuple[str, str, str]] = []
        self.bodies: list[bytes] = []
        self.responses: list[bytes] = []

    def _s3_request(self, method: str, key: str, query: str = "", body: bytes = b"") -> bytes:
        self.requests.append((method, key, query))
        self.bodies.append(body)
        return self.responses.pop(0) if self.responses else b""


class FakeStorage(FakeTransportMixin, S3Storage):
    pass


class FakeBackup(FakeTransportMixin, S3Backup):
    pass


class FakeRecovery(FakeTransportMixin, S3Recovery):
    pass


class S3StorageTest(unittest.TestCase):
    def test_list_parses_keys_and_sizes(self) -> None:
        adapter = FakeStorage(CONFIG)
        adapter.responses = [LIST_XML]
        entries = adapter.list(prefix="backups/")
        self.assertEqual(
            entries,
            [
                {"key": "backups/production/db.dump-20260801T100000", "size": 2048},
                {"key": "backups/production/db.dump-20260801T120000", "size": 4096},
            ],
        )
        method, key, query = adapter.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("list-type=2", query)
        self.assertIn("prefix=backups%2F", query)


class S3BackupTest(unittest.TestCase):
    def test_backup_uploads_the_declared_dump(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dump = Path(tmp.name) / "db.dump"
        dump.write_bytes(b"dump-bytes")
        adapter = FakeBackup({**CONFIG, "sources": {"production": str(dump)}})
        result = adapter.backup("production")
        method, key, _ = adapter.requests[0]
        self.assertEqual(method, "PUT")
        self.assertTrue(key.startswith("backups/production/db.dump-"))
        self.assertEqual(adapter.bodies[0], b"dump-bytes")
        self.assertEqual(result["state"], "backed-up")
        self.assertEqual(result["bytes"], len(b"dump-bytes"))

    def test_unmapped_environment_raises(self) -> None:
        adapter = FakeBackup({**CONFIG, "sources": {}})
        with self.assertRaisesRegex(ValueError, "staging"):
            adapter.backup("staging")


class S3RecoveryTest(unittest.TestCase):
    def test_restore_downloads_the_latest_backup(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        adapter = FakeRecovery({**CONFIG, "restore_dir": tmp.name})
        adapter.responses = [LIST_XML, b"restored-bytes"]
        result = adapter.restore("production")
        self.assertEqual(result["state"], "restored")
        # The most recent key wins.
        self.assertEqual(result["key"], "backups/production/db.dump-20260801T120000")
        restored = Path(result["path"])
        self.assertEqual(restored.read_bytes(), b"restored-bytes")
        self.assertEqual(restored.parent, Path(tmp.name))

    def test_restore_without_any_backup_raises(self) -> None:
        adapter = FakeRecovery({**CONFIG, "restore_dir": "."})
        adapter.responses = [b"<ListBucketResult></ListBucketResult>"]
        with self.assertRaisesRegex(ValueError, "no backup"):
            adapter.restore("staging")


class StorageIntentTest(unittest.TestCase):
    def test_storage_intent_resolves_to_storage_list(self) -> None:
        import textwrap

        from baygon.core.kernel import Kernel

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(
            textwrap.dedent(
                """
                version: 1
                project: {name: demo}
                providers: {}
                environments:
                  development: {}
                  staging: {}
                  production: {}
                """
            ),
            encoding="utf-8",
        )
        kernel = Kernel.start(tmp.name)
        plan = kernel.plan("liste les fichiers du stockage")
        self.assertEqual(plan.intent.name, "ShowStorage")
        self.assertEqual(plan.steps[0].capability, "storage")
        self.assertEqual(plan.steps[0].action, "list")


if __name__ == "__main__":
    unittest.main()
