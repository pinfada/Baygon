"""Event Manager.

The core publishes events; it never analyses them. Subscribers (plugins,
audit, shell) react. A failing subscriber is isolated: it can never stop
the core or prevent other subscribers from receiving the event.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

# Well-known event names. Plugins may publish their own.
PROJECT_OPENED = "ProjectOpened"
PROJECT_RELOADED = "ProjectReloaded"
PLAN_CREATED = "PlanCreated"
PLAN_SUSPENDED = "PlanSuspended"
EXECUTION_STARTED = "ExecutionStarted"
EXECUTION_FINISHED = "ExecutionFinished"
STEP_STARTED = "StepStarted"
STEP_FINISHED = "StepFinished"
PROVIDER_FAILED = "ProviderFailed"
PLUGIN_LOADED = "PluginLoaded"
PLUGIN_FAILED = "PluginFailed"
IMPLEMENTATION_SELECTED = "ImplementationSelected"
COMMAND_EXECUTED = "CommandExecuted"


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._catch_all: list[Callable[[Event], None]] = []

    def subscribe(self, name: str | None, handler: Callable[[Event], None]) -> None:
        """Subscribe to a named event, or to every event when name is None."""
        if name is None:
            self._catch_all.append(handler)
        else:
            self._subscribers.setdefault(name, []).append(handler)

    def publish(self, name: str, **payload: Any) -> Event:
        event = Event(name=name, payload=payload)
        for handler in self._subscribers.get(name, []) + self._catch_all:
            try:
                handler(event)
            except Exception:
                # A subscriber failure must never propagate to the core.
                continue
        return event
