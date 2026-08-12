"""Database capability backed by PostgreSQL connection info.

Baygon gives access to the database (EF-010) without replacing psql:
it returns the connection information and the console command. The DSN
is read from the environment (EF-011) and the password is never
exposed — the console command references the variable, not its value.

    providers:
      db:
        type: database
        plugin: baygon_plugins.postgres_database:PostgresDatabase
        options:
          dsn_env:
            staging: STAGING_DATABASE_URL
            production: PROD_DATABASE_URL
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

from baygon.capabilities import ActionableError, DatabaseCapability


class PostgresDatabase(DatabaseCapability):
    identifier = "postgres"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def _dsn_var(self, environment: str) -> str:
        mapping = self.config.get("dsn_env") or {}
        variable = mapping.get(environment)
        if not variable:
            declared = ", ".join(sorted(mapping)) or "none"
            raise ActionableError(
                f"no DSN variable declared for environment {environment!r}",
                [
                    f"declare options.dsn_env.{environment} in baygon.yaml",
                    f"or target a declared environment: {declared}",
                ],
            )
        return str(variable)

    def health_check(self) -> bool:
        return bool(self.config.get("dsn_env"))

    def info(self, environment: str, **params: Any) -> dict[str, Any]:
        variable = self._dsn_var(environment)
        dsn = os.environ.get(variable)
        if not dsn:
            raise ActionableError(
                f"environment variable {variable!r} is not set",
                [
                    f"export {variable}=postgres://user:password@host:port/database",
                    "the value stays in the environment; Baygon never stores it (EF-011)",
                ],
            )
        parsed = urllib.parse.urlsplit(dsn)
        return {
            "environment": environment,
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "database": parsed.path.lstrip("/"),
            "user": parsed.username,
            # Reference the variable, never the secret it contains.
            "console": f'psql "${variable}"',
        }
