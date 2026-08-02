"""Project Manager — several projects, one Shell (EF-001).

Each project is fully described by its own baygon.yaml and runs in its
own kernel: projects are completely independent (separate providers,
permissions, history). Adding a project requires no core change
(Article 14): drop a baygon.yaml in a subdirectory and it is
discovered. A broken project is isolated; the others keep working.
"""

from __future__ import annotations

import re
from pathlib import Path

from baygon.core.errors import BaygonError, UnknownProjectError
from baygon.core.kernel import Kernel


class SingleProject:
    """One project behind the same interface as ProjectManager.

    Lets every interface (terminal, API, web) talk to one abstraction,
    whether the Shell serves one application or several.
    """

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel
        self.failures: dict[str, str] = dict(kernel.plugins.failures)

    def projects(self) -> list[str]:
        return [self._kernel.config.project_name]

    def kernel(self, name: str) -> Kernel:
        if name != self._kernel.config.project_name:
            raise UnknownProjectError(name, self.projects())
        return self._kernel

    def resolve(self, text: str = "", explicit: str | None = None) -> Kernel:
        if explicit is not None:
            return self.kernel(explicit)
        return self._kernel


class ProjectManager:
    def __init__(self) -> None:
        self._kernels: dict[str, Kernel] = {}
        self.failures: dict[str, str] = {}

    @classmethod
    def discover(cls, root: str | Path) -> "ProjectManager":
        """Load every project found in root (itself or its direct children)."""
        manager = cls()
        base = Path(root)
        candidates = []
        if (base / "baygon.yaml").exists():
            candidates.append(base)
        candidates += sorted(
            child for child in base.iterdir()
            if child.is_dir() and (child / "baygon.yaml").exists()
        )
        for directory in candidates:
            try:
                kernel = Kernel.start(directory)
                manager._kernels[kernel.config.project_name] = kernel
            except BaygonError as exc:
                # Isolate the broken project; the others keep working.
                manager.failures[directory.name] = str(exc)
        return manager

    def projects(self) -> list[str]:
        return sorted(self._kernels)

    def kernel(self, name: str) -> Kernel:
        kernel = self._kernels.get(name)
        if kernel is None:
            raise UnknownProjectError(name, self.projects())
        return kernel

    def resolve(self, text: str, explicit: str | None = None) -> Kernel:
        """Pick the target project: explicit > named in text > sole project."""
        if explicit is not None:
            return self.kernel(explicit)
        lowered = text.lower()
        matches = [
            name for name in self.projects()
            if re.search(rf"\b{re.escape(name.lower())}\b", lowered)
        ]
        if len(matches) == 1:
            return self._kernels[matches[0]]
        if len(self._kernels) == 1:
            return next(iter(self._kernels.values()))
        raise UnknownProjectError(None, self.projects())
