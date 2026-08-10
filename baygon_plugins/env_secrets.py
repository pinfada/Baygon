"""Secrets capability backed by environment variables.

Secrets are never stored in clear text by Baygon: this adapter reads
them from the process environment where the secret manager put them.
"""

from __future__ import annotations

import os
from typing import Any

from baygon.capabilities import ActionableError, SecretsCapability


class EnvSecrets(SecretsCapability):
    identifier = "env-secrets"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def get(self, name: str, **params: Any) -> str:
        prefix = self.config.get("prefix", "")
        value = os.environ.get(f"{prefix}{name}")
        if value is None:
            raise ActionableError(
                f"secret {name!r} is not available",
                [f"export {prefix}{name}=… ; the name is the prefix plus the secret"],
            )
        return value
