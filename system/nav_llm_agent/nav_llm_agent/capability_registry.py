from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

import yaml


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    handler: str = ""
    workflow: str = ""
    exposed: bool = True
    arguments: Dict[str, Dict[str, Any]] = None


class CapabilityRegistry:
    """Loads the model-facing tool catalog and reusable workflow definitions."""

    def __init__(self, path: str):
        with open(path, "r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        if int(raw.get("version", 0)) != 1:
            raise ValueError("capability registry version must be 1")
        self.capabilities: Dict[str, Capability] = {}
        for name, spec in (raw.get("capabilities") or {}).items():
            if not isinstance(spec, dict):
                raise ValueError(f"capability {name!r} must be an object")
            handler = str(spec.get("handler") or "")
            workflow = str(spec.get("workflow") or "")
            if bool(handler) == bool(workflow):
                raise ValueError(
                    f"capability {name!r} must define exactly one handler or workflow"
                )
            self.capabilities[name] = Capability(
                name=name,
                description=str(spec.get("description") or name),
                handler=handler,
                workflow=workflow,
                exposed=bool(spec.get("exposed", True)),
                arguments=dict(spec.get("arguments") or {}),
            )
        self.workflows = dict(raw.get("workflows") or {})
        for capability in self.capabilities.values():
            if capability.workflow and capability.workflow not in self.workflows:
                raise ValueError(
                    f"capability {capability.name!r} references unknown workflow "
                    f"{capability.workflow!r}"
                )

    def exposed(self) -> Iterable[Capability]:
        return (item for item in self.capabilities.values() if item.exposed)

    def validate_call(self, name: str, arguments: Any) -> Dict[str, Any]:
        capability = self.capabilities.get(name)
        if capability is None or not capability.exposed:
            raise ValueError(f"unknown capability {name!r}")
        values = dict(arguments or {}) if isinstance(arguments, dict) else {}
        unknown = set(values) - set(capability.arguments or {})
        if unknown:
            raise ValueError(f"unknown arguments for {name}: {sorted(unknown)}")
        result: Dict[str, Any] = {}
        for key, rule in (capability.arguments or {}).items():
            if key in values:
                value = values[key]
            elif "default" in rule:
                value = rule["default"]
            elif bool(rule.get("required", False)):
                raise ValueError(f"missing required argument {key!r} for {name}")
            else:
                continue
            expected = str(rule.get("type") or "string")
            if expected == "string" and not isinstance(value, str):
                raise ValueError(f"argument {key!r} for {name} must be a string")
            allowed = rule.get("enum")
            if allowed is not None and value not in allowed:
                raise ValueError(
                    f"argument {key!r} for {name} must be one of {allowed}"
                )
            result[key] = value
        return result

    def prompt_lines(self) -> list[str]:
        lines = []
        for item in self.exposed():
            args = []
            for key, rule in (item.arguments or {}).items():
                label = key
                if rule.get("enum"):
                    label += "=" + "|".join(str(v) for v in rule["enum"])
                elif rule.get("required"):
                    label += "=<必填>"
                if "default" in rule:
                    label += f"(默认{rule['default']})"
                args.append(label)
            suffix = f" 参数：{', '.join(args)}" if args else " 无参数"
            lines.append(f"- {item.name}: {item.description}；{suffix}")
        return lines

