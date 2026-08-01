"""Audit journal.

Every plan is journalized with, at minimum: date, user, intention,
generated plan and result. The journal is an append-only JSONL file and
constitutes the consultable history (EF-012).

This is operating data of Baygon itself, not business state: deleting
the journal loses history but never breaks the system (EF-016).
"""

from __future__ import annotations

import datetime
import getpass
import json
from pathlib import Path
from typing import Any

from baygon.core.executor import ExecutionResult
from baygon.core.intent import Plan


class AuditJournal:
    def __init__(self, directory: str | Path) -> None:
        self._file = Path(directory) / "history.jsonl"

    def record(self, plan: Plan, result: ExecutionResult | None, status: str) -> dict[str, Any]:
        entry = {
            "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "user": getpass.getuser(),
            "intent": plan.intent.name,
            "input": plan.intent.raw_input,
            "plan": plan.to_dict(),
            "status": status,
            "result": result.to_dict() if result else None,
        }
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with self._file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def entries(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self._file.exists():
            return []
        lines = self._file.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
