"""Baygon error hierarchy.

Errors are isolated by origin so that a provider failure can never be
mistaken for (or escalate into) a core failure.
"""


class BaygonError(Exception):
    """Base class for every error raised by Baygon."""


class ConfigError(BaygonError):
    """baygon.yaml is missing, unreadable or invalid. Execution is forbidden."""


class UnknownIntentError(BaygonError):
    """The input could not be resolved to a supported intention."""

    def __init__(self, text: str, supported: list[str]):
        self.text = text
        self.supported = supported
        super().__init__(
            f"Unable to resolve intention from input: {text!r}. "
            f"Supported intentions: {', '.join(supported)}"
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
