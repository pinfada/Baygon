"""AI capability stub that works fully offline.

The AI is never a mandatory dependency (EF-014): this adapter produces a
deterministic summary of the gathered context so that every workflow
also works without a real model. Swapping it for a real provider
(Claude, OpenAI, local model, ...) only requires a new adapter and a
``baygon.yaml`` change.
"""

from __future__ import annotations

from typing import Any

from baygon.capabilities import AICapability


class OfflineAI(AICapability):
    identifier = "offline-ai"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str:
        lines = [f"[offline analysis] {prompt}"]
        for key, value in (context or {}).items():
            lines.append(f"- context {key}: {value!r}")
        return "\n".join(lines)
