"""Baygon error hierarchy.

Errors are isolated by origin so that a provider failure can never be
mistaken for (or escalate into) a core failure.
"""


class BaygonError(Exception):
    """Base class for every error raised by Baygon."""


class ConfigError(BaygonError):
    """baygon.yaml is missing, unreadable or invalid. Execution is forbidden."""


class UnknownIntentError(BaygonError):
    """The input could not be resolved to a supported intention.

    The message names what *this* project can do rather than everything
    Baygon knows: listing sixteen intentions when two are possible here
    is an enumeration of the impossible, not guidance. The full list
    stays on `supported` for programs that want it.
    """

    def __init__(
        self,
        text: str,
        supported: list[str],
        usable: list[str] | None = None,
        commands: list[str] | None = None,
    ):
        self.text = text
        self.supported = supported
        self.usable = list(usable) if usable is not None else list(supported)
        self.commands = list(commands or [])
        message = f"Unable to resolve intention from input: {text!r}."
        if self.usable:
            message += f" Usable here: {', '.join(self.usable)}."
        else:
            message += " No intention is usable here: no provider is declared."
        if self.commands:
            message += f" Declared commands, by name: {', '.join(self.commands)}."
        message += " Run 'baygon doctor' to see what is missing and why."
        super().__init__(message)


class UnknownProjectError(BaygonError):
    """The intention targets no identifiable project."""

    def __init__(self, requested: str | None, known: list[str]):
        self.requested = requested
        self.known = known
        detail = f"unknown project {requested!r}" if requested else "no project identified"
        super().__init__(
            f"{detail}; name one in the intention or pass --project. "
            f"Known projects: {', '.join(known) or 'none'}"
        )


class CapabilityUnavailableError(BaygonError):
    """No usable implementation is registered for a capability."""

    def __init__(self, capability: str, detail: str = ""):
        self.capability = capability
        message = f"No implementation available for capability {capability!r}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class PluginError(BaygonError):
    """A plugin could not be loaded or is not compliant with its contract."""


class ValidationRequiredError(BaygonError):
    """The plan contains sensitive actions and was not explicitly approved."""

    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        super().__init__(
            f"Plan {plan_id} requires explicit validation before execution"
        )


class StepExecutionError(BaygonError):
    """A plan step failed. Carries the failed step, the cause and options."""

    def __init__(self, step_id: str, cause: str, options: list[str]):
        self.step_id = step_id
        self.cause = cause
        self.options = options
        super().__init__(f"Step {step_id} failed: {cause}")
