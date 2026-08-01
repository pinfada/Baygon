import unittest

from baygon.capabilities import ImplementationState
from baygon.core.errors import CapabilityUnavailableError, PluginError
from baygon.core.events import EventBus
from baygon.core.registry import CapabilityRegistry
from tests.helpers import BrokenDeployment, FakeDeployment, FakeRepository


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)

    def test_register_activates_healthy_implementation(self) -> None:
        impl = FakeDeployment()
        self.registry.register(impl)
        self.assertEqual(impl.state, ImplementationState.ACTIVE)
        self.assertTrue(self.registry.is_available("deployment"))

    def test_resolve_explicit_request_wins(self) -> None:
        first, second = FakeDeployment(), FakeDeployment()
        second.identifier = "other-deploy"
        self.registry.register(first, default=True)
        self.registry.register(second)
        resolved = self.registry.resolve("deployment", requested="other-deploy")
        self.assertIs(resolved, second)

    def test_resolve_prefers_default(self) -> None:
        first, second = FakeDeployment(), FakeDeployment()
        second.identifier = "other-deploy"
        self.registry.register(first)
        self.registry.register(second, default=True)
        self.assertIs(self.registry.resolve("deployment"), second)

    def test_resolve_falls_back_to_any_active(self) -> None:
        impl = FakeDeployment()
        self.registry.register(impl)
        self.assertIs(self.registry.resolve("deployment"), impl)

    def test_resolve_unknown_capability_errors(self) -> None:
        with self.assertRaises(CapabilityUnavailableError):
            self.registry.resolve("deployment")

    def test_unknown_requested_implementation_errors(self) -> None:
        self.registry.register(FakeDeployment())
        with self.assertRaises(CapabilityUnavailableError):
            self.registry.resolve("deployment", requested="missing")

    def test_failed_health_check_marks_failed_but_does_not_raise(self) -> None:
        class Unhealthy(FakeDeployment):
            identifier = "unhealthy"

            def health_check(self) -> bool:
                raise RuntimeError("cannot connect")

        impl = Unhealthy()
        self.registry.register(impl)
        self.assertEqual(impl.state, ImplementationState.FAILED)
        with self.assertRaises(CapabilityUnavailableError):
            self.registry.resolve("deployment")

    def test_contract_violation_rejected(self) -> None:
        class Impostor(FakeRepository):
            capability = "deployment"
            identifier = "impostor"

        with self.assertRaises(PluginError):
            self.registry.register(Impostor())

    def test_capabilities_exposes_metadata(self) -> None:
        self.registry.register(FakeDeployment())
        self.registry.register(BrokenDeployment())
        listing = self.registry.capabilities()
        self.assertEqual(len(listing["deployment"]), 2)
        self.assertEqual(listing["deployment"][0]["capability"], "deployment")


if __name__ == "__main__":
    unittest.main()
