from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional


def _resolve(value: Any, variables: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return variables.get(value[1:], "")
    if isinstance(value, dict):
        return {key: _resolve(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, variables) for item in value]
    return value


class WorkflowEngine:
    """Small deterministic sequencer; ROS handlers complete each step asynchronously."""

    def __init__(self, workflows: Dict[str, Any]):
        self._workflows = workflows
        self.name = ""
        self.variables: Dict[str, Any] = {}
        self.index = 0
        self.active = False

    def start(self, name: str, variables: Dict[str, Any]) -> None:
        if name not in self._workflows:
            raise ValueError(f"unknown workflow {name!r}")
        steps = self._workflows[name].get("steps") or []
        if not steps:
            raise ValueError(f"workflow {name!r} has no steps")
        self.name = name
        self.variables = deepcopy(variables)
        self.index = 0
        self.active = True

    def current(self) -> Optional[Dict[str, Any]]:
        if not self.active:
            return None
        steps = self._workflows[self.name]["steps"]
        if self.index >= len(steps):
            self.active = False
            return None
        return _resolve(deepcopy(steps[self.index]), self.variables)

    def advance(self) -> bool:
        if not self.active:
            return True
        self.index += 1
        if self.index >= len(self._workflows[self.name]["steps"]):
            self.active = False
            return True
        return False

    def cancel(self) -> None:
        self.active = False
        self.name = ""
        self.variables = {}
        self.index = 0

