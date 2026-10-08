"""Create the configured LLM backend chain."""
from __future__ import annotations

from .fallback import FallbackBackend
from .hobot_llamacpp_backend import HobotLlamaCppBackend
from .hobot_xlm_backend import HobotXlmBackend
from .ollama_backend import OllamaBackend


VALID = ("hobot_xlm", "hobot_llamacpp", "ollama")


def _names(primary, fallbacks):
    result = [str(primary or "ollama").strip().lower()]
    if isinstance(fallbacks, str):
        fallbacks = [item for item in fallbacks.split(",") if item.strip()]
    for item in fallbacks or []:
        name = str(item).strip().lower()
        if name and name not in result:
            result.append(name)
    for name in result:
        if name not in VALID:
            raise ValueError(f"unsupported LLM backend: {name}")
    return result


def create_llm_backend(node, primary, fallbacks, ollama_client,
                       timeout_sec=12.0):
    backends = []
    for name in _names(primary, fallbacks):
        if name == "hobot_xlm":
            backends.append(HobotXlmBackend(node, timeout_sec=timeout_sec))
        elif name == "hobot_llamacpp":
            backends.append(HobotLlamaCppBackend(node, timeout_sec=timeout_sec))
        else:
            backends.append(OllamaBackend(ollama_client))
    return backends[0] if len(backends) == 1 else FallbackBackend(backends)
